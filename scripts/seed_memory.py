"""Seed MongoDB and Hindsight memory with 40 synthetic resolved incidents.

Run after generating the seed data:
    python data/generate_incidents.py
    python scripts/seed_memory.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import db, memory

SEED_FILE = Path(__file__).parent.parent / "data" / "incidents_seed.json"


def main() -> None:
    """Load seed incidents into MongoDB and retain each one in Hindsight."""
    if not SEED_FILE.exists():
        print(f"Seed file not found: {SEED_FILE}")
        print("Run: python data/generate_incidents.py first")
        sys.exit(1)

    incidents = json.loads(SEED_FILE.read_text())
    print(f"Loaded {len(incidents)} incidents from {SEED_FILE}")

    # Clear existing data first to avoid duplicates
    deleted = db.clear_incidents()
    print(f"Cleared {deleted} existing incidents from MongoDB")

    ok_mongo = 0
    ok_memory = 0
    fail_memory = 0

    for inc in incidents:
        # Insert into MongoDB
        db.insert_incident(inc)
        ok_mongo += 1

        # Retain into Hindsight
        try:
            memory.retain_incident(inc)
            ok_memory += 1
            print(f"  ✓ retained {inc['incident_id']} — {inc['title'][:60]}")
        except memory.MemoryUnavailableError as exc:
            fail_memory += 1
            print(f"  ✗ memory retain failed for {inc['incident_id']}: {exc}")

    print(f"\nDone. Mongo: {ok_mongo} inserted. Memory: {ok_memory} retained, {fail_memory} failed.")


if __name__ == "__main__":
    main()
