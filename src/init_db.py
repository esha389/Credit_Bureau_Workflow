"""
BureauFlow — Step 2: create bureauflow.db from sql/schema.sql.
Run this once (or after deleting bureauflow.db to start fresh).
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"
SCHEMA_PATH = ROOT / "sql" / "schema.sql"


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed existing {DB_PATH.name}")

    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"Created {DB_PATH} from {SCHEMA_PATH.name}")


if __name__ == "__main__":
    main()
