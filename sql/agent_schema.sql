-- BureauFlow — Phase 3: agent layer tables.
-- These are additive (CREATE TABLE IF NOT EXISTS) so running this against
-- your existing bureauflow.db does NOT touch fact_dispute or anything
-- from Phase 1/2. Run via: python src/init_agent_db.py

-- New dispute submissions the agent hasn't triaged yet. This simulates
-- what would land in an intake system before anyone looks at it.
CREATE TABLE IF NOT EXISTS incoming_disputes (
    incoming_id      TEXT PRIMARY KEY,
    consumer_id      TEXT,
    furnisher_id     TEXT,
    bureau_name_raw  TEXT,
    channel          TEXT,
    raw_text         TEXT NOT NULL,
    true_reason_code TEXT,   -- known only because this is synthetic data; used for Phase 4 evaluation
    submitted_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    processed        INTEGER DEFAULT 0 CHECK (processed IN (0, 1))
);

-- The agent's proposal for each incoming dispute, awaiting human review.
-- Nothing here has touched fact_dispute yet.
CREATE TABLE IF NOT EXISTS agent_review_queue (
    queue_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    incoming_id            TEXT NOT NULL UNIQUE REFERENCES incoming_disputes(incoming_id),
    consumer_id            TEXT,
    furnisher_id           TEXT,
    bureau_name_raw        TEXT,
    channel                TEXT,
    raw_text                TEXT NOT NULL,
    suggested_reason_code   TEXT,
    confidence              REAL,
    retrieved_guidance      TEXT,   -- JSON: list of {reason_code, title, score}
    policy_action            TEXT CHECK (policy_action IN ('auto_route', 'escalate_human')),
    policy_rationale          TEXT,
    status                    TEXT NOT NULL DEFAULT 'pending'
                                   CHECK (status IN ('pending', 'approved', 'rejected')),
    final_reason_code         TEXT,   -- set on approval; human may override the suggestion
    decided_by                TEXT,
    decided_at                TEXT,
    created_at                TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Every step the agent (or a human) takes, for the audit trail.
-- Also mirrored to data/agent_audit_log.jsonl (dual-storage pattern).
CREATE TABLE IF NOT EXISTS agent_audit_log (
    log_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    incoming_id  TEXT,
    event_type   TEXT NOT NULL,   -- classified | retrieved | policy_decision | human_decision | committed
    event_detail TEXT,            -- JSON
    logged_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
