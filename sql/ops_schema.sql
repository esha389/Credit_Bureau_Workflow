-- BureauFlow — Phase 4: AI Ops layer.
-- agent_review_queue also gets 3 new columns (classify_latency_ms,
-- retrieve_latency_ms, simulated_cost_usd) — added by src/init_ops_db.py
-- in Python, since SQLite has no "ALTER TABLE ADD COLUMN IF NOT EXISTS".

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at           TEXT DEFAULT CURRENT_TIMESTAMP,
    n_items          INTEGER,
    overall_accuracy REAL,
    per_reason_json  TEXT,   -- JSON: {reason_code: {precision, recall, support}}
    confusion_json   TEXT    -- JSON: {true_code: {predicted_code: count}}
);
