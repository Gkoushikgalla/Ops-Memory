"""FastAPI application — all routes and static file serving."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Path as FPath
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import agent, db, memory
from app.models import AnalyzeRequest, AnalysisResult, ResolveRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="OpsMemory", version="1.0.0", description="Incident Response Agent with Hindsight memory")

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Root — serve index.html
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root():
    """Serve the single-page frontend."""
    from fastapi.responses import FileResponse
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["system"])
async def health():
    """Liveness probe — returns ok if the service is running."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Incidents — analyze
# ---------------------------------------------------------------------------


@app.post("/api/incidents/analyze", tags=["incidents"])
async def analyze(req: AnalyzeRequest):
    """
    Create a new open incident, run the agent analysis, and return the diagnosis.

    Body: {title, service, severity, error_log, symptoms, use_memory}
    """
    # Validate required fields
    if not req.title or not req.service or not req.severity:
        raise HTTPException(status_code=400, detail="title, service, and severity are required")

    if req.service not in (
        "payments-api",
        "auth-service",
        "order-service",
        "inventory-service",
        "notification-service",
        "search-service",
    ):
        raise HTTPException(status_code=400, detail=f"Unknown service: {req.service}")

    if req.severity not in ("SEV1", "SEV2", "SEV3"):
        raise HTTPException(status_code=400, detail=f"severity must be SEV1, SEV2, or SEV3")

    # Persist the new incident
    incident_id = db.next_incident_id()
    doc = {
        "incident_id": incident_id,
        "title": req.title,
        "service": req.service,
        "severity": req.severity,
        "error_log": req.error_log,
        "symptoms": req.symptoms,
        "root_cause": "",
        "fix_steps": [],
        "resolution_minutes": 0,
        "status": "open",
        "created_at": datetime.now(timezone.utc),
        "resolved_at": None,
    }
    db.insert_incident(doc)
    logger.info("Created incident %s", incident_id)

    # Build query text for memory recall
    incident_text = (
        f"Title: {req.title}\n"
        f"Service: {req.service}\n"
        f"Severity: {req.severity}\n"
        f"Symptoms: {req.symptoms}\n"
        f"Error Log:\n{req.error_log}"
    )

    try:
        result = agent.analyze_incident(incident_text, req.use_memory)
    except Exception as exc:
        logger.error("Agent analysis failed for %s: %s", incident_id, exc)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    return {"incident_id": incident_id, **result}


# ---------------------------------------------------------------------------
# Incidents — resolve
# ---------------------------------------------------------------------------


@app.post("/api/incidents/{incident_id}/resolve", tags=["incidents"])
async def resolve(
    incident_id: str = FPath(..., description="Incident ID, e.g. INC-0001"),
    req: ResolveRequest = ...,
):
    """
    Resolve an open incident: update Mongo and retain the resolution into memory.

    Body: {root_cause, fix_steps, resolution_minutes}
    """
    if not req.root_cause:
        raise HTTPException(status_code=400, detail="root_cause is required")
    if not req.fix_steps:
        raise HTTPException(status_code=400, detail="fix_steps must not be empty")
    if req.resolution_minutes <= 0:
        raise HTTPException(status_code=400, detail="resolution_minutes must be positive")

    try:
        result = agent.resolve_incident(
            incident_id, req.root_cause, req.fix_steps, req.resolution_minutes
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Resolve failed for %s: %s", incident_id, exc)
        raise HTTPException(status_code=500, detail=f"Resolve failed: {exc}")

    return result


# ---------------------------------------------------------------------------
# Incidents — list
# ---------------------------------------------------------------------------


@app.get("/api/incidents", tags=["incidents"])
async def list_incidents():
    """Return all incidents, newest first."""
    incidents = db.list_incidents()
    return {"incidents": incidents}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@app.get("/api/stats", tags=["system"])
async def stats():
    """Return aggregate stats: total, resolved, avg resolution time, memories retained."""
    return db.get_stats()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@app.post("/api/reset", tags=["system"])
async def reset():
    """
    Clear all incidents from MongoDB and all memories from the Hindsight bank.

    Intended for demo resets only.
    """
    deleted = db.clear_incidents()
    try:
        memory.reset_bank()
        mem_reset = True
    except Exception as exc:
        logger.warning("Hindsight bank reset failed: %s", exc)
        mem_reset = False

    return {
        "incidents_deleted": deleted,
        "memory_reset": mem_reset,
    }
