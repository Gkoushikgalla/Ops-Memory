"""Hindsight memory integration — ALL Hindsight calls live here only.

Uses hindsight-client to retain resolved incidents as memories and
recall similar past incidents when a new one arrives.
"""

from __future__ import annotations

import logging
from typing import List

from hindsight_client import Hindsight

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class MemoryUnavailableError(RuntimeError):
    """Raised when a retain call fails and we cannot store the memory."""


# ---------------------------------------------------------------------------
# Client initialisation (lazy singleton)
# ---------------------------------------------------------------------------

_client: Hindsight | None = None


def _get_client() -> Hindsight:
    """Return the singleton Hindsight client, created on first call."""
    global _client
    if _client is None:
        kwargs: dict = {}
        if settings.hindsight_base_url:
            kwargs["base_url"] = settings.hindsight_base_url
        if settings.hindsight_api_key:
            kwargs["api_key"] = settings.hindsight_api_key
        _client = Hindsight(**kwargs)
    return _client


# ---------------------------------------------------------------------------
# Content builder
# ---------------------------------------------------------------------------


def _build_content(incident: dict) -> str:
    """
    Construct the memory content string from a resolved incident document.

    Includes: title, service, severity, symptoms, error_log (first 15 lines),
    root_cause, fix_steps, resolution_minutes, incident_id.
    """
    error_lines = (incident.get("error_log") or "").split("\n")[:15]
    error_snippet = "\n".join(error_lines)

    steps = incident.get("fix_steps") or []
    steps_text = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(steps))

    return (
        f"Incident ID: {incident.get('incident_id', 'N/A')}\n"
        f"Title: {incident.get('title', '')}\n"
        f"Service: {incident.get('service', '')}\n"
        f"Severity: {incident.get('severity', '')}\n"
        f"Symptoms: {incident.get('symptoms', '')}\n"
        f"Error Log (first 15 lines):\n{error_snippet}\n"
        f"Root Cause: {incident.get('root_cause', '')}\n"
        f"Fix Steps:\n{steps_text}\n"
        f"Resolution Time: {incident.get('resolution_minutes', 0)} minutes"
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def retain_incident(incident: dict) -> None:
    """
    Store one resolved incident as a memory in the Hindsight bank.

    Raises MemoryUnavailableError on failure so callers can surface a
    clear error rather than silently losing the memory.
    """
    incident_id = incident.get("incident_id", "unknown")
    content = _build_content(incident)
    try:
        client = _get_client()
        client.retain(bank_id=settings.hindsight_bank_id, content=content)
        logger.info("MEMORY RETAIN | incident_id=%s | bank=%s", incident_id, settings.hindsight_bank_id)
    except Exception as exc:
        logger.error("MEMORY RETAIN FAILED | incident_id=%s | error=%s", incident_id, exc)
        raise MemoryUnavailableError(
            f"Failed to retain memory for {incident_id}: {exc}"
        ) from exc


def recall_similar(query: str, top_k: int = 3) -> List[dict]:
    """
    Recall the top-k most relevant past incidents for a given query.

    Returns a list of dicts with keys: incident_id, text, score.
    Returns an empty list on any Hindsight failure (the app must not crash).
    """
    try:
        client = _get_client()
        results = client.recall(bank_id=settings.hindsight_bank_id, query=query)

        # Normalise the response — hindsight-client returns a list of memory objects
        memories: List[dict] = []
        items = results if isinstance(results, list) else []
        for item in items[:top_k]:
            # Each item may be a dict or an object with attributes
            if isinstance(item, dict):
                text = item.get("content") or item.get("text") or str(item)
                score = item.get("score") or item.get("relevance_score") or 0.0
            else:
                text = getattr(item, "content", None) or getattr(item, "text", None) or str(item)
                score = getattr(item, "score", None) or getattr(item, "relevance_score", 0.0)

            # Try to extract incident_id from the content text
            inc_id = "unknown"
            for line in (text or "").split("\n"):
                if line.startswith("Incident ID:"):
                    inc_id = line.split(":", 1)[1].strip()
                    break

            memories.append({"incident_id": inc_id, "text": text, "score": float(score)})

        logger.info(
            "MEMORY RECALL | query_len=%d | bank=%s | results=%d",
            len(query),
            settings.hindsight_bank_id,
            len(memories),
        )
        return memories

    except Exception as exc:
        logger.error("MEMORY RECALL FAILED | error=%s", exc)
        return []


def reset_bank() -> None:
    """
    Clear all memories in the configured Hindsight bank.

    Uses the REST delete endpoint directly since the Python client
    may not expose a dedicated reset method.
    """
    import httpx

    base = (settings.hindsight_base_url or "https://api.hindsight.vectorize.io").rstrip("/")
    headers: dict = {}
    if settings.hindsight_api_key:
        headers["Authorization"] = f"Bearer {settings.hindsight_api_key}"

    try:
        resp = httpx.delete(
            f"{base}/api/v1/banks/{settings.hindsight_bank_id}/memories",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        logger.info("MEMORY RESET | bank=%s | status=%s", settings.hindsight_bank_id, resp.status_code)
    except Exception as exc:
        logger.error("MEMORY RESET FAILED | bank=%s | error=%s", settings.hindsight_bank_id, exc)
        raise
