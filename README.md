# BureauFlow

**An end-to-end synthetic credit-dispute platform: data engineering, SQL analytics, an agentic triage layer, and AI Ops monitoring, all built on one shared database.**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-star%20schema-003B57?logo=sqlite&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-dashboards-FF4B4B?logo=streamlit&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-TF--IDF-F7931E?logo=scikitlearn&logoColor=white)

![BureauFlow architecture](docs/architecture.svg)

## Live demo

| What | Link |
|---|---|
| Analytics dashboard (Phase 2) | [creditbureauworkflow-bureauflow-analytics.streamlit.app](https://creditbureauworkflow-bureauflow-analytics.streamlit.app/) |
| AI Ops monitoring dashboard (Phase 4) | [bureauflow-ops-dashboard.streamlit.app](https://bureauflow-ops-dashboard.streamlit.app/) |
| Agent review console (Phase 3) | Demo clip below (runs locally) |

**Agent console demo:**

https://github.com/user-attachments/assets/7ff7d788-771e-4492-bbea-05519839ece4

> Free-tier Streamlit apps sleep when idle. If a page shows a "wake up" button, click it and give it a few seconds.

## Results

- **5,296** clean records loaded from **6,124** raw rows. The rest were rejected with a logged reason for each, so nothing is silently dropped.
- **93.3%** dispute-classification accuracy on the agent's evaluation set: **96.5%** on items it auto-routed vs. **83.3%** on items it escalated to a human. That is the split a well-calibrated policy engine should produce.
- **4 phases, one database**: ETL → SQL/dashboard analytics → human-in-the-loop agent → AI Ops monitoring.

**Built with:** Python · pandas · SQLite · Streamlit · scikit-learn · seaborn/matplotlib

Built on public FCRA/credit-reporting domain concepts. **All data is synthetic. No real consumer or employer data is used anywhere in this repo.**

## Why this project

Disputes go through intake → investigation → response, against a 30-day regulatory clock. This project models that lifecycle end to end: generate realistic messy data, clean and validate it, and land it in a schema built for analytics (Phase 2) and an agent layer (Phase 3), then monitor the agent in production-style conditions (Phase 4).

## Project structure

```
bureauflow/
├── sql/
│   ├── schema.sql              # star schema: dims + fact_dispute + etl_rejects
│   └── analytics_queries.sql   # 10 ops-analytics queries
├── src/
│   ├── generate_raw_data.py        # creates messy synthetic raw CSV
│   ├── init_db.py                  # builds bureauflow.db from schema.sql
│   ├── etl.py                      # cleans raw data, loads star schema, logs rejects
│   ├── dashboard.py                # Phase 2 analytics dashboard
│   ├── init_agent_db.py            # Phase 3 tables
│   ├── generate_incoming_disputes.py
│   ├── run_intake.py               # classify + retrieve + policy routing
│   ├── agent_core.py               # TF-IDF classifier, retrieval, policy engine
│   ├── agent_console.py            # human review console
│   ├── init_ops_db.py              # Phase 4 latency/cost columns + eval_runs
│   ├── eval_classifier.py          # evaluation harness
│   └── ops_dashboard.py            # AI Ops monitoring dashboard
├── data/raw/                   # generated CSVs (raw + reference lists)
├── docs/architecture.svg
├── bureauflow.db               # SQLite database (generated)
└── requirements.txt
```

## Quick start

```bash
pip install -r requirements.txt
python src/init_db.py            # (re)builds an empty bureauflow.db
python src/generate_raw_data.py  # writes data/raw/disputes_raw.csv
python src/etl.py                # cleans + loads into bureauflow.db
```

Each run of `etl.py` prints a load summary, e.g.:

```
Raw rows read:        6124
Loaded to fact_dispute: 5296
Rejected (see etl_rejects): 828
Reject breakdown:
  invalid reason_code: 257
  unparseable received_date: 171
  duplicate dispute_id: 124
  ...
```

Then continue with the Phase 2, 3 and 4 commands below.

## Phase 1: Data engineering

**Star schema**, SQLite:
- `fact_dispute`: one row per dispute (dates, channel, SLA breach flag, status)
- `dim_consumer`, `dim_furnisher`, `dim_bureau`, `dim_reason`: lookups
- `etl_rejects`: every row the ETL refused to load, with a reason and the original raw payload (JSON) for debugging

**Data quality rules enforced by the ETL** (see `src/etl.py`):
- No duplicate `dispute_id`
- `consumer_id` and `furnisher_id` required and must resolve to a known dimension row
- `bureau_name` normalized from raw variants (`"EQF"`, `"equifax"`, `"Trans Union"`, …) to a canonical bureau
- `reason_code` must exist in `dim_reason`
- Dates parsed across three raw formats; unparseable dates rejected
- `response_date` may not precede `received_date`
- SLA breach computed as `days_to_respond > 30`

### Explore in DBeaver

1. **Database → New Database Connection → SQLite**
2. Point the path at `bureauflow.db` in this folder
3. If DBeaver prompts to download the SQLite JDBC driver, allow it
4. Browse the tables or run SQL, e.g.:

```sql
SELECT status, COUNT(*) FROM fact_dispute GROUP BY status;

SELECT r.reason_description,
       ROUND(100.0 * SUM(f.sla_breached) / COUNT(*), 1) AS breach_pct
FROM fact_dispute f
JOIN dim_reason r ON f.reason_code = r.reason_code
WHERE f.status = 'Closed'
GROUP BY r.reason_description
ORDER BY breach_pct DESC;
```

## Phase 2: Analytics + dashboard

`dim_furnisher` carries a `quality_tier` (`good` / `average` / `poor`), and closed disputes get a reinvestigation `outcome` (`verified` / `updated` / `deleted`) weighted by that tier. A furnisher's accuracy history drives its disputes' outcomes, which is what makes furnisher error-rate analysis meaningful.

**If you ran Phase 1 before this was added**, re-run the pipeline so your database picks up the new column and outcome data:

```bash
python src/init_db.py
python src/generate_raw_data.py
python src/etl.py
```

**SQL:** `sql/analytics_queries.sql` has 10 queries answering real ops questions: SLA trend, breach rate by reason, furnisher scorecard, repeat disputers, channel/bureau comparison, backlog aging, and ETL reject summary.

**Dashboard** ([live](https://creditbureauworkflow-bureauflow-analytics.streamlit.app/)):

```bash
streamlit run src/dashboard.py   # http://localhost:8501
```

KPI cards up top, then seaborn/matplotlib charts and pandas tables for each question above.

## Phase 3: Agentic triage layer

New disputes go through an agent before they become a case. This phase is purely additive and does not touch Phase 1/2 data.

**One-time setup** (safe to run on an existing database):

```bash
python src/init_agent_db.py
```

**Run the pipeline:**

```bash
python src/generate_incoming_disputes.py   # 150 new synthetic submissions
python src/run_intake.py                   # classify + retrieve + propose routing
streamlit run src/agent_console.py         # human reviews and approves/rejects
```

**How it works:**
1. `incoming_disputes`: new free-text consumer submissions, unprocessed.
2. **Classify** (`src/agent_core.py`): TF-IDF cosine similarity against reference guidance suggests a reason code and a confidence score. This is not a hosted LLM. It is a deliberate, disclosed design choice: free, deterministic, fully explainable, and swappable for an embedding model or LLM call later without changing the pipeline shape.
3. **Retrieve**: the same TF-IDF index returns the most relevant guidance snippets (real nearest-neighbor retrieval, not a lookup table).
4. **Policy engine** (`decide_policy` in `agent_core.py`): routes to `auto_route` (pre-filled, one-click approval) or `escalate_human` (flagged for careful review). High-risk reason codes (fraud/identity theft) always escalate, low classifier confidence escalates, and furnishers with a poor track record get extra scrutiny.
5. **`agent_review_queue`**: the agent's proposal, awaiting a human.
6. **Human review console** (`agent_console.py`): the reviewer sees the text, suggestion, confidence, retrieved guidance and policy flag, can override the reason code, and clicks Approve or Reject. **Nothing reaches `fact_dispute` without this click, including `auto_route` items.** The agent proposes; a human approves anything that touches the system of record.
7. On approval, a new `Open` case is written to `fact_dispute` (`dispute_id` prefixed `AG`) and everything is logged.
8. **Dual-storage audit log**: every step (classified / retrieved / policy_decision / human_decision / committed) is written to both `agent_audit_log` (SQLite, queryable) and `data/agent_audit_log.jsonl` (append-only).

On the 150-item synthetic batch used to build this, the classifier matched the true reason code **93.3%** of the time overall: **96.5%** on auto-routed items vs. **83.3%** on escalated ones. The policy engine is correctly sending its least-confident calls to a human.

## Phase 4: AI Ops layer

Not just "does the agent work" but "how do you know it's still working, and what does it cost."

**One-time setup:**

```bash
python src/init_ops_db.py   # adds latency/cost columns + eval_runs table
```

Run this **before** your next `generate_incoming_disputes.py` + `run_intake.py` batch. Those scripts record latency and a simulated cost per item and need the new columns to exist first.

**What's instrumented:**
- **Latency**: real wall-clock time for the classify and retrieve steps, in milliseconds. These are local TF-IDF operations, so this is genuine latency, not simulated.
- **Simulated cost**: `src/agent_core.py` estimates what a step would cost if routed through a hosted LLM (rough token count × an illustrative rate). This is clearly a simulation, not a real bill. The point is the monitoring instrumentation, which has the same shape whether the underlying call is free or metered.
- **Evaluation harness** (`src/eval_classifier.py`): scores the classifier against `incoming_disputes.true_reason_code` (known only because the data is synthetic) and logs accuracy plus per-reason precision/recall to `eval_runs`.

```bash
python src/eval_classifier.py
```

**Monitoring dashboard** ([live](https://bureauflow-ops-dashboard.streamlit.app/)):

```bash
streamlit run src/ops_dashboard.py
```

Shows latest accuracy, escalation rate, average latency and cumulative simulated cost as KPIs; an accuracy-over-time trend with an alert threshold; confidence-score distribution; escalation rate by day; a latency box plot (p50/p95); a cumulative cost curve; and per-reason precision/recall from the latest eval run. An alert banner fires if accuracy drops below 85% or escalation rate climbs above 45%.

## Limitations

- All data is synthetic, and the free-text disputes are generated, so the 93.3% accuracy is a pipeline-validation number, not a claim about real-world performance.
- The classifier is TF-IDF, chosen for transparency and zero cost. A production system would likely benchmark it against embeddings or an LLM using the same evaluation harness.
- Cost figures are simulated.

## The complete picture

1. **Data engineering**: messy synthetic data → validated star schema, with a logged reject trail
2. **Data analysis**: SQL plus a Streamlit ops dashboard answering real questions (SLA breaches, furnisher scorecards, repeat disputers)
3. **Agentic AI**: classify → retrieve → policy-route → human approval → dual-storage audit log
4. **AI Ops**: latency, simulated cost, and a running evaluation set with accuracy monitoring and alerts
