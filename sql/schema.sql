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
    furnisher_type TEXT NOT NULL,
    quality_tier   TEXT CHECK (quality_tier IN ('good', 'average', 'poor'))
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

-- ---------- Phase 3: agent layer (see sql/agent_schema.sql for details) ----------
CREATE TABLE incoming_disputes (
    incoming_id      TEXT PRIMARY KEY,
    consumer_id      TEXT,
    furnisher_id     TEXT,
    bureau_name_raw  TEXT,
    channel          TEXT,
    raw_text         TEXT NOT NULL,
    true_reason_code TEXT,
    submitted_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    processed        INTEGER DEFAULT 0 CHECK (processed IN (0, 1))
);

CREATE TABLE agent_review_queue (
    queue_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    incoming_id            TEXT NOT NULL UNIQUE REFERENCES incoming_disputes(incoming_id),
    consumer_id            TEXT,
    furnisher_id           TEXT,
    bureau_name_raw        TEXT,
    channel                TEXT,
    raw_text                TEXT NOT NULL,
    suggested_reason_code   TEXT,
    confidence              REAL,
    retrieved_guidance      TEXT,
    policy_action            TEXT CHECK (policy_action IN ('auto_route', 'escalate_human')),
    policy_rationale          TEXT,
    status                    TEXT NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending', 'approved', 'rejected')),
    final_reason_code         TEXT,
    decided_by                TEXT,
    decided_at                TEXT,
    created_at                TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_audit_log (
    log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    incoming_id  TEXT,
    event_type   TEXT NOT NULL,
    event_detail TEXT,
    logged_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ---------- Phase 4: AI Ops (see sql/ops_schema.sql for details) ----------
CREATE TABLE eval_runs (
    run_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at           TEXT DEFAULT CURRENT_TIMESTAMP,
    n_items          INTEGER,
    overall_accuracy REAL,
    per_reason_json  TEXT,
    confusion_json   TEXT
);
-- Note: a from-scratch build via init_db.py does NOT include the 3 extra
-- agent_review_queue columns (classify_latency_ms, retrieve_latency_ms,
-- simulated_cost_usd) — those are always added via src/init_ops_db.py.
