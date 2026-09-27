"""
BureauFlow — Phase 4 setup: adds AI Ops instrumentation to your EXISTING
bureauflow.db. Adds 3 columns to agent_review_queue (latency + a simulated
cost estimate) and a new eval_runs table. Additive only — rows already in
agent_review_queue from before this get NULL for the new columns until
you run run_intake.py again on a fresh batch.

Safe to run more than once.
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"
OPS_SCHEMA_PATH = ROOT / "sql" / "ops_schema.sql"

NEW_COLUMNS = [
    ("classify_latency_ms", "REAL"),
    ("retrieve_latency_ms", "REAL"),
    ("simulated_cost_usd", "REAL"),
]


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"{DB_PATH.name} doesn't exist yet — run Phase 1 first.")

    conn = sqlite3.connect(DB_PATH)

    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_review_queue)")}
    for col, coltype in NEW_COLUMNS:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE agent_review_queue ADD COLUMN {col} {coltype}")
            print(f"Added column agent_review_queue.{col}")
        else:
            print(f"Column agent_review_queue.{col} already exists, skipping")

    with open(OPS_SCHEMA_PATH) as f:
        conn.executescript(f.read())

    conn.commit()
    conn.close()
    print("AI Ops instrumentation ready.")


if __name__ == "__main__":
    main()
