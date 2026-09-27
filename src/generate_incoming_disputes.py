"""
BureauFlow — Phase 3: generate synthetic incoming dispute submissions.

Reads existing consumers/furnishers straight from bureauflow.db (built in
Phase 1) so nothing earlier needs to be regenerated. Writes new rows into
the incoming_disputes table for the agent to triage.

Run order: init_agent_db.py -> generate_incoming_disputes.py -> run_intake.py
"""

import random
import sqlite3
from pathlib import Path

import pandas as pd

from agent_core import get_connection

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"

random.seed(11)

N_INCOMING = 150

# A few varied phrasings per reason code, so the same true label doesn't
# always produce identical text (keeps the classifier's job non-trivial).
TEMPLATES = {
    "R01": [
        "I never opened this account, it's not mine.",
        "This account does not belong to me — I don't recognize it at all.",
        "Someone else's account is showing up on my report, I never applied for this.",
    ],
    "R02": [
        "The balance amount shown is way too high, that's not what I owe.",
        "My reported balance is wrong, it should be much lower than this.",
        "The balance on this account is incorrect compared to my own records.",
    ],
    "R03": [
        "This account shows late payments but I always paid on time every month.",
        "My payment history is wrong — I never missed a single payment.",
        "There are late marks on this account that shouldn't be there, I paid on schedule.",
    ],
    "R04": [
        "This account shows as open but I closed it a long time ago.",
        "The account status is wrong, it's marked closed but I'm still using it.",
        "My account status is incorrect on this report.",
    ],
    "R05": [
        "This same account is appearing twice on my credit report, it's a duplicate.",
        "I see this exact account listed two separate times.",
        "There's a duplicate entry for this account on my report.",
    ],
    "R06": [
        "The date this account was opened is wrong on my report.",
        "My account's opening date is incorrect, it's showing the wrong year.",
        "The reported open date for this account doesn't match when I actually opened it.",
    ],
    "R07": [
        "I already paid this account off in full months ago but it still shows a balance due.",
        "This was paid off completely, why does it still say I owe money?",
        "The payoff on this account was never reflected, it still shows a balance.",
    ],
    "R08": [
        "Someone stole my identity and opened this account fraudulently without my knowledge.",
        "This is a fraudulent account, I never authorized it — I think I'm a victim of identity theft.",
        "I did not open this account, this looks like fraud on my identity.",
    ],
    "R09": [
        "The credit limit shown for this account is wrong.",
        "My reported credit limit doesn't match the actual limit on my card.",
        "This account's high balance figure is incorrect.",
    ],
    "R10": [
        "This account was discharged in my bankruptcy but it still shows I owe money.",
        "After my bankruptcy discharge, this account should not still be reporting a balance.",
        "This debt was included in my bankruptcy and should no longer show as owed.",
    ],
}

CHANNELS = ["online", "mail", "phone"]
BUREAUS_RAW = ["Equifax", "Experian", "TransUnion", "EQF", "TU", "experian"]


def main():
    conn = get_connection()

    if not conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='incoming_disputes'"
    ).fetchone():
        raise SystemExit("incoming_disputes table not found — run src/init_agent_db.py first.")

    consumers = [r[0] for r in conn.execute("SELECT consumer_id FROM dim_consumer").fetchall()]
    furnishers = [r[0] for r in conn.execute("SELECT furnisher_id FROM dim_furnisher").fetchall()]

    if not consumers or not furnishers:
        raise SystemExit("dim_consumer/dim_furnisher are empty — run Phase 1 (etl.py) first.")

    existing = conn.execute("SELECT COUNT(*) FROM incoming_disputes").fetchone()[0]
    start_i = existing + 1

    rows = []
    for i in range(start_i, start_i + N_INCOMING):
        true_code = random.choice(list(TEMPLATES.keys()))
        text = random.choice(TEMPLATES[true_code])
        rows.append(
            (
                f"IN{i:06d}",
                random.choice(consumers),
                random.choice(furnishers),
                random.choice(BUREAUS_RAW),
                random.choice(CHANNELS),
                text,
                true_code,
            )
        )

    conn.executemany(
        "INSERT INTO incoming_disputes "
        "(incoming_id, consumer_id, furnisher_id, bureau_name_raw, channel, raw_text, true_reason_code) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    print(f"Added {len(rows)} new incoming disputes (unprocessed).")
    conn.close()


if __name__ == "__main__":
    main()
