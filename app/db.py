"""MongoDB access layer — all database operations live here."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from pymongo import MongoClient
from pymongo.collection import Collection

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_client: Optional[MongoClient] = None


def get_client() -> MongoClient:
    """Return the singleton MongoClient, creating it on first call."""
    global _client
    if _client is None:
        _client = MongoClient(settings.mongo_uri)
    return _client


def get_collection() -> Collection:
    """Return the incidents collection."""
    return get_client()[settings.mongo_db]["incidents"]


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def list_incidents(limit: int = 500) -> List[dict]:
    """Return all incidents, newest first, with _id stripped."""
    col = get_collection()
    docs = list(col.find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
    return docs


def get_incident(incident_id: str) -> Optional[dict]:
    """Fetch a single incident by incident_id; return None if not found."""
    col = get_collection()
    doc = col.find_one({"incident_id": incident_id}, {"_id": 0})
    return doc


def get_stats() -> dict:
    """Compute aggregate statistics over the incidents collection."""
    col = get_collection()
    total = col.count_documents({})
    resolved = col.count_documents({"status": "resolved"})

    pipeline = [
        {"$match": {"status": "resolved", "resolution_minutes": {"$gt": 0}}},
        {"$group": {"_id": None, "avg": {"$avg": "$resolution_minutes"}}},
    ]
    agg = list(col.aggregate(pipeline))
    avg_min = round(agg[0]["avg"], 1) if agg else 0.0

    memories_retained = col.count_documents({"status": "resolved"})

    return {
        "total_incidents": total,
        "resolved": resolved,
        "avg_resolution_minutes": avg_min,
        "memories_retained": memories_retained,
    }


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def next_incident_id() -> str:
    """Generate the next sequential incident ID in the format INC-XXXX."""
    col = get_collection()
    count = col.count_documents({})
    return f"INC-{count + 1:04d}"


def insert_incident(doc: dict) -> str:
    """Insert a new incident document and return its incident_id."""
    col = get_collection()
    col.insert_one(doc)
    return doc["incident_id"]


def resolve_incident(
    incident_id: str,
    root_cause: str,
    fix_steps: List[str],
    resolution_minutes: int,
) -> bool:
    """
    Mark an incident as resolved and populate resolution fields.

    Returns True if a document was updated, False if not found.
    """
    col = get_collection()
    result = col.update_one(
        {"incident_id": incident_id},
        {
            "$set": {
                "status": "resolved",
                "root_cause": root_cause,
                "fix_steps": fix_steps,
                "resolution_minutes": resolution_minutes,
                "resolved_at": datetime.now(timezone.utc),
            }
        },
    )
    return result.matched_count > 0


def clear_incidents() -> int:
    """Delete all incident documents. Returns number deleted."""
    col = get_collection()
    result = col.delete_many({})
    return result.deleted_count
