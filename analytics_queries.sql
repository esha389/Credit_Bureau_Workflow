-- BureauFlow — Phase 2: Analytics queries
-- Run these in DBeaver against bureauflow.db, or via src/dashboard.py.
-- Each query answers a specific operations question a dispute-resolution
-- team would actually ask.

-- ============================================================
-- 1. Overall SLA performance
-- ============================================================
SELECT
    COUNT(*)                                                     AS closed_disputes,
    SUM(sla_breached)                                            AS breached,
    ROUND(100.0 * SUM(sla_breached) / COUNT(*), 1)               AS breach_pct,
    ROUND(AVG(days_to_respond), 1)                               AS avg_days_to_respond
FROM fact_dispute
WHERE status = 'Closed';

-- ============================================================
-- 2. SLA breach rate by month (trend)
-- ============================================================
SELECT
    strftime('%Y-%m', received_date)                             AS month,
    COUNT(*)                                                      AS closed_disputes,
    ROUND(100.0 * SUM(sla_breached) / COUNT(*), 1)                AS breach_pct
FROM fact_dispute
WHERE status = 'Closed'
GROUP BY month
ORDER BY month;

-- ============================================================
-- 3. SLA breach rate by dispute reason
-- ============================================================
SELECT
    r.reason_description,
    COUNT(*)                                                      AS closed_disputes,
    ROUND(100.0 * SUM(f.sla_breached) / COUNT(*), 1)              AS breach_pct
FROM fact_dispute f
JOIN dim_reason r ON f.reason_code = r.reason_code
WHERE f.status = 'Closed'
GROUP BY r.reason_description
ORDER BY breach_pct DESC;

-- ============================================================
-- 4. Reinvestigation outcome mix (verified / updated / deleted)
-- ============================================================
SELECT
    outcome,
    COUNT(*)                                                      AS disputes,
    ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM fact_dispute WHERE status='Closed'), 1) AS pct_of_closed
FROM fact_dispute
WHERE status = 'Closed'
GROUP BY outcome
ORDER BY disputes DESC;

-- ============================================================
-- 5. Furnisher scorecard — error rate (updated + deleted) per furnisher
--    "Error" here means the furnisher's original report didn't hold up.
-- ============================================================
SELECT
    fn.furnisher_name,
    fn.furnisher_type,
    fn.quality_tier,
    COUNT(*)                                                      AS closed_disputes,
    ROUND(100.0 * SUM(CASE WHEN f.outcome IN ('updated','deleted') THEN 1 ELSE 0 END)
          / COUNT(*), 1)                                          AS error_rate_pct
FROM fact_dispute f
JOIN dim_furnisher fn ON f.furnisher_id = fn.furnisher_id
WHERE f.status = 'Closed'
GROUP BY fn.furnisher_id
HAVING closed_disputes >= 10
ORDER BY error_rate_pct DESC
LIMIT 15;

-- ============================================================
-- 6. Repeat disputers — consumers who filed more than one dispute
-- ============================================================
SELECT
    c.consumer_id,
    c.state,
    COUNT(*)                                                      AS dispute_count,
    SUM(CASE WHEN f.outcome IN ('updated','deleted') THEN 1 ELSE 0 END) AS upheld_disputes
FROM fact_dispute f
JOIN dim_consumer c ON f.consumer_id = c.consumer_id
GROUP BY c.consumer_id
HAVING dispute_count > 1
ORDER BY dispute_count DESC
LIMIT 20;

-- ============================================================
-- 7. Volume and breach rate by intake channel
-- ============================================================
SELECT
    channel,
    COUNT(*)                                                      AS disputes,
    ROUND(100.0 * SUM(CASE WHEN status='Closed' AND sla_breached=1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN status='Closed' THEN 1 ELSE 0 END), 0), 1) AS breach_pct
FROM fact_dispute
GROUP BY channel
ORDER BY disputes DESC;

-- ============================================================
-- 8. Bureau-level comparison
-- ============================================================
SELECT
    b.bureau_name,
    COUNT(*)                                                      AS closed_disputes,
    ROUND(100.0 * SUM(f.sla_breached) / COUNT(*), 1)              AS breach_pct,
    ROUND(AVG(f.days_to_respond), 1)                              AS avg_days_to_respond
FROM fact_dispute f
JOIN dim_bureau b ON f.bureau_id = b.bureau_id
WHERE f.status = 'Closed'
GROUP BY b.bureau_name
ORDER BY breach_pct DESC;

-- ============================================================
-- 9. Current open-case backlog, aged
-- ============================================================
SELECT
    CASE
        WHEN julianday('now') - julianday(received_date) <= 15 THEN '0-15 days'
        WHEN julianday('now') - julianday(received_date) <= 30 THEN '16-30 days'
        ELSE '30+ days (overdue)'
    END                                                            AS age_bucket,
    COUNT(*)                                                       AS open_disputes
FROM fact_dispute
WHERE status = 'Open'
GROUP BY age_bucket
ORDER BY age_bucket;

-- ============================================================
-- 10. Data quality summary — what the ETL rejected, and why
-- ============================================================
SELECT
    reject_reason,
    COUNT(*) AS rejected_rows
FROM etl_rejects
GROUP BY reject_reason
ORDER BY rejected_rows DESC
LIMIT 10;
