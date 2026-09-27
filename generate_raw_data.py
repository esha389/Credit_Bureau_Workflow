"""
BureauFlow — Step 1: generate synthetic RAW dispute data.

This simulates a messy export you might pull from a case management system:
inconsistent date formats, typo'd/blank fields, duplicate rows, and a few
records where the response predates the request. The ETL step (etl.py)
is what cleans this into the star schema.

All data is fully synthetic. No real consumer, furnisher, or employer data.
"""

import csv
import random
from datetime import datetime, timedelta

from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

N_CONSUMERS = 800
N_FURNISHERS = 30
N_DISPUTES = 6000

STATES = ["CA", "TX", "NY", "FL", "IL", "OH", "PA", "GA", "NC", "MI", "AZ", "WA"]
AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]

FURNISHER_TYPES = ["Bank", "Credit Union", "Retail Card", "Auto Lender", "Collections Agency"]

# Fixed reference lists — kept consistent across the raw export so the ETL
# has something real to validate against.
BUREAUS = ["Equifax", "Experian", "TransUnion"]
BUREAU_RAW_VARIANTS = {
    "Equifax": ["Equifax", "equifax", "EQF", "EQUIFAX"],
    "Experian": ["Experian", "experian", "EXP"],
    "TransUnion": ["TransUnion", "transunion", "TU", "Trans Union"],
}

REASON_CODES = {
    "R01": "Not my account",
    "R02": "Incorrect balance",
    "R03": "Incorrect payment history",
    "R04": "Account status incorrect (open/closed)",
    "R05": "Duplicate account reported",
    "R06": "Incorrect date opened",
    "R07": "Paid in full but showing balance due",
    "R08": "Suspected identity theft / fraud",
    "R09": "Incorrect credit limit / high balance",
    "R10": "Account should be removed after bankruptcy discharge",
}

CHANNEL_VARIANTS = {
    "online": ["online", "Online", "ONLINE", "web"],
    "mail": ["mail", "Mail", "MAIL"],
    "phone": ["phone", "Phone", "PHONE", "call center"],
}

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"]


def make_consumers(n):
    consumers = []
    for i in range(1, n + 1):
        consumers.append(
            {
                "consumer_id": f"C{i:06d}",
                "state": random.choice(STATES),
                "age_band": random.choice(AGE_BANDS),
            }
        )
    return consumers


def make_furnishers(n):
    furnishers = []
    for i in range(1, n + 1):
        ftype = random.choice(FURNISHER_TYPES)
        furnishers.append(
            {
                "furnisher_id": f"F{i:03d}",
                "furnisher_name": f"{fake.company()} {ftype.split()[0]}",
                "furnisher_type": ftype,
            }
        )
    return furnishers


def messy_date(d: datetime) -> str:
    """Format a date in one of several inconsistent styles, or blank it out."""
    if random.random() < 0.03:
        return ""
    fmt = random.choice(DATE_FORMATS)
    return d.strftime(fmt)


def random_channel_raw():
    key = random.choice(list(CHANNEL_VARIANTS.keys()))
    return random.choice(CHANNEL_VARIANTS[key])


def random_bureau_raw():
    key = random.choice(BUREAUS)
    if random.random() < 0.01:
        return "UNK"  # unmappable, should be rejected
    return random.choice(BUREAU_RAW_VARIANTS[key])


def random_reason_raw():
    if random.random() < 0.04:
        # invalid / free-text reason that won't match dim_reason
        return random.choice(["", "other", "XX99", "see notes"])
    code = random.choice(list(REASON_CODES.keys()))
    if random.random() < 0.1:
        return code.lower()  # case inconsistency, still recoverable
    return code


def generate():
    consumers = make_consumers(N_CONSUMERS)
    furnishers = make_furnishers(N_FURNISHERS)

    rows = []
    start_window = datetime(2025, 1, 1)
    end_window = datetime(2026, 9, 1)

    for i in range(1, N_DISPUTES + 1):
        dispute_id = f"D{i:07d}"
        consumer = random.choice(consumers)
        furnisher = random.choice(furnishers)

        received = start_window + timedelta(
            days=random.randint(0, (end_window - start_window).days)
        )

        is_open = random.random() < 0.12
        response = None
        if not is_open:
            # most responses land within 30 days; a tail runs late (SLA breach)
            if random.random() < 0.8:
                delay = random.randint(3, 30)
            else:
                delay = random.randint(31, 55)
            response = received + timedelta(days=delay)
            # a small slice of bad data: response logged before request
            if random.random() < 0.01:
                response = received - timedelta(days=random.randint(1, 5))

        row = {
            "dispute_id": dispute_id,
            "consumer_id": consumer["consumer_id"] if random.random() > 0.015 else "",
            "consumer_state_raw": consumer["state"],
            "consumer_age_band_raw": consumer["age_band"],
            "furnisher_id": furnisher["furnisher_id"] if random.random() > 0.015 else "",
            "furnisher_name_raw": furnisher["furnisher_name"],
            "bureau_name_raw": random_bureau_raw(),
            "reason_code_raw": random_reason_raw(),
            "channel_raw": random_channel_raw(),
            "received_date_raw": messy_date(received),
            "response_date_raw": messy_date(response) if response else "",
            "status_raw": "Open" if is_open else "Closed",
        }
        rows.append(row)

        # sprinkle in exact-duplicate rows, as a real export sometimes has
        if random.random() < 0.02:
            rows.append(dict(row))

    random.shuffle(rows)

    fieldnames = list(rows[0].keys())
    out_path = "/mnt/user-data/outputs/bureauflow/data/raw/disputes_raw.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # also drop the reference lists — ETL and dashboard both use these
    with open(
        "/mnt/user-data/outputs/bureauflow/data/raw/furnishers_ref.csv", "w", newline=""
    ) as f:
        w = csv.DictWriter(f, fieldnames=["furnisher_id", "furnisher_name", "furnisher_type"])
        w.writeheader()
        w.writerows(furnishers)

    with open(
        "/mnt/user-data/outputs/bureauflow/data/raw/reason_codes_ref.csv", "w", newline=""
    ) as f:
        w = csv.writer(f)
        w.writerow(["reason_code", "reason_description"])
        for code, desc in REASON_CODES.items():
            w.writerow([code, desc])

    print(f"Wrote {len(rows)} raw dispute rows to {out_path}")
    print(f"  consumers: {len(consumers)} | furnishers: {len(furnishers)}")


if __name__ == "__main__":
    generate()
