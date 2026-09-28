"""Groq LLM integration — ALL Groq calls live here only.

Exposes a single public function: diagnose().
"""

from __future__ import annotations

import json
import logging
import re
from typing import List

from groq import Groq

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq client (lazy singleton)
# ---------------------------------------------------------------------------

_client: Groq | None = None


def _get_client() -> Groq:
    """Return the singleton Groq client."""
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


# ---------------------------------------------------------------------------
# System prompt (verbatim from spec)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are OpsMemory, an on-call incident assistant. "
    "You will receive a NEW incident and, optionally, PAST INCIDENTS recalled from memory. "
    "If past incidents are provided, use them: name the most relevant one by its incident_id, "
    "explain why it matches, and base the fix on what worked before. "
    "If no past incidents are provided, give a generic diagnosis and say clearly that no "
    "historical context was available. "
    "Respond with ONLY valid JSON and no markdown, in this shape: "
    '{"diagnosis": string, "likely_root_cause": string, '
    '"recommended_steps": [string], "confidence": "low"|"medium"|"high", '
    '"matched_incident_id": string|null, "match_reason": string}'
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_user_message(incident_text: str, recalled: List[dict]) -> str:
    """Combine new incident description with recalled memories into a prompt."""
    parts = [f"NEW INCIDENT:\n{incident_text}"]

    if recalled:
        parts.append("\nPAST INCIDENTS RECALLED FROM MEMORY:")
        for i, mem in enumerate(recalled, 1):
            score_str = f" (relevance: {mem.get('score', 0):.2f})" if mem.get("score") else ""
            parts.append(
                f"\n[{i}] {mem.get('incident_id', 'N/A')}{score_str}\n{mem.get('text', '')}"
            )
    else:
        parts.append("\nNo past incidents were retrieved from memory.")

    return "\n".join(parts)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if the LLM wrapped the JSON anyway."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _parse_json(raw: str) -> dict:
    """Strip fences and parse JSON; raise ValueError on failure."""
    cleaned = _strip_fences(raw)
    return json.loads(cleaned)


def _call_model(model: str, user_message: str) -> dict:
    """
    Call the specified Groq model and parse the JSON response.

    Retries parsing once if the first attempt fails.
    """
    client = _get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
    )
    raw = response.choices[0].message.content or ""

    # First parse attempt
    try:
        return _parse_json(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("JSON parse failed on first attempt; retrying once")

    # Retry: ask again with same prompt
    retry_resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": "Your response was not valid JSON. Respond with ONLY the JSON object, no markdown.",
            },
        ],
        temperature=0.0,
    )
    raw2 = retry_resp.choices[0].message.content or ""
    return _parse_json(raw2)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def diagnose(incident_text: str, recalled: List[dict]) -> dict:
    """
    Send the incident + recalled memories to Groq and return a parsed diagnosis.

    Strategy:
      1. Try primary model (GROQ_MODEL).
      2. On any error, retry once with primary model.
      3. If still failing, fall back to GROQ_FALLBACK_MODEL.
      4. If all fail, return a friendly error dict.
    """
    user_message = _build_user_message(incident_text, recalled)

    # Attempt with primary model
    for model in [settings.groq_model, settings.groq_model]:  # one retry on primary
        try:
            result = _call_model(model, user_message)
            logger.info("LLM DIAGNOSE | model=%s | confidence=%s", model, result.get("confidence"))
            return result
        except Exception as exc:
            logger.warning("LLM call failed | model=%s | error=%s", model, exc)
            break  # stop retrying primary, move to fallback

    # Fallback model
    try:
        result = _call_model(settings.groq_fallback_model, user_message)
        logger.info(
            "LLM DIAGNOSE (fallback) | model=%s | confidence=%s",
            settings.groq_fallback_model,
            result.get("confidence"),
        )
        return result
    except Exception as exc:
        logger.error("LLM fallback also failed | error=%s", exc)

    # All models failed — return friendly error object
    return {
        "diagnosis": "Unable to generate a diagnosis at this time. The LLM service is unavailable.",
        "likely_root_cause": "Unknown — please investigate manually.",
        "recommended_steps": [
            "Check service logs for recent errors",
            "Review recent deployments for changes",
            "Escalate to senior engineer if unresolved",
        ],
        "confidence": "low",
        "matched_incident_id": None,
        "match_reason": "LLM service unavailable; no AI-assisted matching was performed.",
    }
