"""
BureauFlow — Step 3: ETL.

Reads data/raw/disputes_raw.csv (messy), cleans and validates it, and loads
the result into the star schema created by init_db.py. Rows that fail
validation are written to etl_rejects instead of silently dropped or
silently "fixed" — that rejection trail is itself something to point to
in an interview as a data-quality control.

Run order: init_db.py -> generate_raw_data.py -> etl.py
"""

import csv
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"
RAW_DIR = ROOT / "data" / "raw"

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"]

BUREAU_MAP = {
    "equifax": "Equifax",
    "eqf": "Equifax",
    "experian": "Experian",
    "exp": "Experian",
    "transunion": "TransUnion",
    "tu": "TransUnion",
    "trans union": "TransUnion",
}

VALID_REASON_CODES = None  # populated from dim_reason after load
VALID_FURNISHER_IDS = None  # populated from dim_furnisher after load


def parse_date(raw: str):
    if not raw or not raw.strip():
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None  # unparseable


def load_reference_data(conn):
    """Load furnishers and reason codes from the raw ref CSVs into dims."""
    cur = conn.cursor()

    with open(RAW_DIR / "furnishers_ref.csv") as f:
        for row in csv.DictReader(f):
            cur.execute(
                "INSERT OR IGNORE INTO dim_furnisher (furnisher_id, furnisher_name, furnisher_type) "
                "VALUES (?, ?, ?)",
                (row["furnisher_id"], row["furnisher_name"], row["furnisher_type"]),
            )

    with open(RAW_DIR / "reason_codes_ref.csv") as f:
        for row in csv.DictReader(f):
            cur.execute(
                "INSERT OR IGNORE INTO dim_reason (reason_code, reason_description) VALUES (?, ?)",
                (row["reason_code"], row["reason_description"]),
            )

    conn.commit()


def bureau_id_lookup(conn):
    cur = conn.cursor()
    cur.execute("SELECT bureau_id, bureau_name FROM dim_bureau")
    return {name: bid for bid, name in cur.fetchall()}


def run_etl():
    conn = sqlite3.connect(DB_PATH)
    load_reference_data(conn)

    bureau_ids = bureau_id_lookup(conn)
    cur = conn.cursor()
    cur.execute("SELECT reason_code FROM dim_reason")
    valid_reasons = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT furnisher_id FROM dim_furnisher")
    valid_furnishers = {r[0] for r in cur.fetchall()}

    df = pd.read_csv(RAW_DIR / "disputes_raw.csv", dtype=str, keep_default_na=False)

    seen_dispute_ids = set()
    accepted = []
    rejected = []
    consumers_seen = {}  # consumer_id -> (state, age_band)

    for _, row in df.iterrows():
        errors = []
        dispute_id = row["dispute_id"].strip()

        if dispute_id in seen_dispute_ids:
            errors.append("duplicate dispute_id")
        else:
            seen_dispute_ids.add(dispute_id)

        consumer_id = row["consumer_id"].strip()
        if not consumer_id:
            errors.append("missing consumer_id")

        furnisher_id = row["furnisher_id"].strip()
        if not furnisher_id:
            errors.append("missing furnisher_id")
        elif furnisher_id not in valid_furnishers:
            errors.append(f"unknown furnisher_id: {furnisher_id}")

        bureau_raw = row["bureau_name_raw"].strip().lower()
        bureau_name = BUREAU_MAP.get(bureau_raw)
        if not bureau_name:
            errors.append(f"unmappable bureau: {row['bureau_name_raw']}")

        reason_code = row["reason_code_raw"].strip().upper()
        if reason_code not in valid_reasons:
            errors.append(f"invalid reason_code: {row['reason_code_raw']}")

        channel = row["channel_raw"].strip().lower()
        if channel == "web":
            channel = "online"
        elif channel == "call center":
            channel = "phone"
        if channel not in ("online", "mail", "phone"):
            errors.append(f"unrecognized channel: {row['channel_raw']}")

        received = parse_date(row["received_date_raw"])
        if received is None:
            errors.append("unparseable received_date")

        response = parse_date(row["response_date_raw"]) if row["response_date_raw"] else None
        if row["response_date_raw"] and response is None:
            errors.append("unparseable response_date")
        if received and response and response < received:
            errors.append("response_date before received_date")

        status = row["status_raw"].strip()
        if status not in ("Open", "Closed"):
            errors.append(f"invalid status: {status}")

        if errors:
            rejected.append(
                {
                    "dispute_id": dispute_id,
                    "reject_reason": "; ".join(errors),
                    "raw_payload": json.dumps(row.to_dict()),
                }
            )
            continue

        due_date = received + timedelta(days=30)
        days_to_respond = (response - received).days if response else None
        sla_breached = int(days_to_respond > 30) if days_to_respond is not None else None

        accepted.append(
            {
                "dispute_id": dispute_id,
                "consumer_id": consumer_id,
                "furnisher_id": furnisher_id,
                "bureau_id": bureau_ids[bureau_name],
                "reason_code": reason_code,
                "channel": channel,
                "received_date": received.isoformat(),
                "due_date": due_date.isoformat(),
                "response_date": response.isoformat() if response else None,
                "days_to_respond": days_to_respond,
                "sla_breached": sla_breached,
                "status": status,
                "outcome": None,  # not modeled in this phase; added with the agent layer
            }
        )
        consumers_seen[consumer_id] = (
            row["consumer_state_raw"].strip() or None,
            row["consumer_age_band_raw"].strip() or None,
        )

    # ---- load dim_consumer ----
    cur.executemany(
        "INSERT OR IGNORE INTO dim_consumer (consumer_id, state, age_band) VALUES (?, ?, ?)",
        [(cid, s, a) for cid, (s, a) in consumers_seen.items()],
    )

    # ---- load fact_dispute ----
    fact_cols = [
        "dispute_id", "consumer_id", "furnisher_id", "bureau_id", "reason_code",
        "channel", "received_date", "due_date", "response_date", "days_to_respond",
        "sla_breached", "status", "outcome",
    ]
    cur.executemany(
        f"INSERT INTO fact_dispute ({', '.join(fact_cols)}) VALUES ({', '.join(['?'] * len(fact_cols))})",
        [tuple(r[c] for c in fact_cols) for r in accepted],
    )

    # ---- load etl_rejects ----
    cur.executemany(
        "INSERT INTO etl_rejects (dispute_id, reject_reason, raw_payload) VALUES (?, ?, ?)",
        [(r["dispute_id"], r["reject_reason"], r["raw_payload"]) for r in rejected],
    )

    conn.commit()

    print(f"Raw rows read:        {len(df)}")
    print(f"Loaded to fact_dispute: {len(accepted)}")
    print(f"Rejected (see etl_rejects): {len(rejected)}")
    if rejected:
        reasons = {}
        for r in rejected:
            for reason in r["reject_reason"].split("; "):
                key = reason.split(":")[0]
                reasons[key] = reasons.get(key, 0) + 1
        print("Reject breakdown:")
        for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")

    conn.close()


if __name__ == "__main__":
    run_etl()
