"""
BureauFlow — Phase 3 setup: add the agent-layer tables to your EXISTING
bureauflow.db without touching fact_dispute, dim_*, or etl_rejects.

Safe to run more than once (CREATE TABLE IF NOT EXISTS).
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"
AGENT_SCHEMA_PATH = ROOT / "sql" / "agent_schema.sql"


def main():
    if not DB_PATH.exists():
        raise SystemExit(
            f"{DB_PATH.name} doesn't exist yet. Run src/init_db.py, "
            "src/generate_raw_data.py and src/etl.py first (Phase 1)."
        )

    conn = sqlite3.connect(DB_PATH)
    with open(AGENT_SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"Agent-layer tables added to {DB_PATH.name} (existing data untouched).")


if __name__ == "__main__":
    main()
