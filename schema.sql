-- BureauFlow: clean model (star schema) for SQLite.
-- These tables are created empty now and populated by the ETL step (next).
-- Raw, messy data lives in the stg_* tables loaded by src/init_db.py.

PRAGMA foreign_keys = ON;

-- ---------- Dimensions ----------
CREATE TABLE dim_bureau (
    bureau_id   INTEGER PRIMARY KEY,
    bureau_name TEXT NOT NULL UNIQUE
);
INSERT INTO dim_bureau (bureau_name) VALUES ('Equifax'), ('Experian'), ('TransUnion');

CREATE TABLE dim_consumer (
    consumer_id TEXT PRIMARY KEY,
    state       TEXT,
    age_band    TEXT
);

CREATE TABLE dim_furnisher (
    furnisher_id   TEXT PRIMARY KEY,
    furnisher_name TEXT NOT NULL,
    furnisher_type TEXT NOT NULL
);

CREATE TABLE dim_reason (
    reason_code        TEXT PRIMARY KEY,
    reason_description TEXT NOT NULL
);

-- ---------- Fact ----------
CREATE TABLE fact_dispute (
    dispute_id      TEXT PRIMARY KEY,
    consumer_id     TEXT    NOT NULL REFERENCES dim_consumer(consumer_id),
    furnisher_id    TEXT    NOT NULL REFERENCES dim_furnisher(furnisher_id),
    bureau_id       INTEGER NOT NULL REFERENCES dim_bureau(bureau_id),
    reason_code     TEXT    NOT NULL REFERENCES dim_reason(reason_code),
    channel         TEXT    NOT NULL CHECK (channel IN ('online', 'mail', 'phone')),
    received_date   TEXT    NOT NULL,             -- ISO yyyy-mm-dd
    due_date        TEXT    NOT NULL,             -- received_date + 30 days
    response_date   TEXT,                         -- NULL while the case is open
    days_to_respond INTEGER,
    sla_breached    INTEGER CHECK (sla_breached IN (0, 1)),
    status          TEXT    NOT NULL CHECK (status IN ('Open', 'Closed')),
    outcome         TEXT    CHECK (outcome IN ('verified', 'updated', 'deleted')),
    CHECK (response_date IS NULL OR response_date >= received_date)
);

CREATE INDEX idx_fact_furnisher ON fact_dispute (furnisher_id);
CREATE INDEX idx_fact_reason    ON fact_dispute (reason_code);
CREATE INDEX idx_fact_received  ON fact_dispute (received_date);

-- ---------- Data quality: rows the ETL refuses to load ----------
CREATE TABLE etl_rejects (
    reject_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    dispute_id    TEXT,
    reject_reason TEXT NOT NULL,
    raw_payload   TEXT,
    rejected_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
