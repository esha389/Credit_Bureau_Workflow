"""
BureauFlow — Phase 2: Streamlit dashboard.

Reads bureauflow.db (built in Phase 1) and presents the same questions as
sql/analytics_queries.sql, as an interactive dashboard.

Run with:
    streamlit run src/dashboard.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import sqlite3
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"

sns.set_style("whitegrid")
st.set_page_config(page_title="BureauFlow — Dispute Ops Dashboard", layout="wide")


@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


@st.cache_data
def load(query: str) -> pd.DataFrame:
    return pd.read_sql(query, get_connection())


def kpi_row():
    overall = load(
        """
        SELECT COUNT(*) AS closed_disputes,
               SUM(sla_breached) AS breached,
               ROUND(100.0 * SUM(sla_breached) / COUNT(*), 1) AS breach_pct,
               ROUND(AVG(days_to_respond), 1) AS avg_days
        FROM fact_dispute WHERE status = 'Closed'
        """
    ).iloc[0]
    open_count = load("SELECT COUNT(*) AS n FROM fact_dispute WHERE status = 'Open'").iloc[0]["n"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Closed disputes", f"{int(overall['closed_disputes']):,}")
    c2.metric("SLA breach rate", f"{overall['breach_pct']}%")
    c3.metric("Avg. days to respond", f"{overall['avg_days']}")
    c4.metric("Open backlog", f"{int(open_count):,}")


def sla_trend():
    df = load(
        """
        SELECT strftime('%Y-%m', received_date) AS month,
               COUNT(*) AS closed_disputes,
               ROUND(100.0 * SUM(sla_breached) / COUNT(*), 1) AS breach_pct
        FROM fact_dispute WHERE status = 'Closed'
        GROUP BY month ORDER BY month
        """
    )
    fig, ax = plt.subplots(figsize=(9, 3.2))
    sns.lineplot(data=df, x="month", y="breach_pct", marker="o", ax=ax, color="#C0392B")
    ax.set_ylabel("SLA breach %")
    ax.set_xlabel("")
    ax.set_title("SLA breach rate by month")
    ax.tick_params(axis="x", rotation=45)
    st.pyplot(fig)


def breach_by_reason():
    df = load(
        """
        SELECT r.reason_description, ROUND(100.0 * SUM(f.sla_breached) / COUNT(*), 1) AS breach_pct
        FROM fact_dispute f JOIN dim_reason r ON f.reason_code = r.reason_code
        WHERE f.status = 'Closed'
        GROUP BY r.reason_description ORDER BY breach_pct DESC
        """
    )
    fig, ax = plt.subplots(figsize=(6, 4))
    sns.barplot(data=df, y="reason_description", x="breach_pct", color="#2E86AB", ax=ax)
    ax.set_xlabel("SLA breach %")
    ax.set_ylabel("")
    ax.set_title("SLA breach rate by dispute reason")
    st.pyplot(fig)


def outcome_mix():
    df = load(
        """
        SELECT outcome, COUNT(*) AS disputes
        FROM fact_dispute WHERE status = 'Closed'
        GROUP BY outcome ORDER BY disputes DESC
        """
    )
    fig, ax = plt.subplots(figsize=(4, 4))
    colors = {"verified": "#2E86AB", "updated": "#F5B041", "deleted": "#C0392B"}
    ax.pie(
        df["disputes"],
        labels=df["outcome"],
        autopct="%1.0f%%",
        colors=[colors.get(o, "#999") for o in df["outcome"]],
        startangle=90,
    )
    ax.set_title("Reinvestigation outcome mix")
    st.pyplot(fig)


def furnisher_scorecard():
    df = load(
        """
        SELECT fn.furnisher_name, fn.quality_tier, COUNT(*) AS closed_disputes,
               ROUND(100.0 * SUM(CASE WHEN f.outcome IN ('updated','deleted') THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS error_rate_pct
        FROM fact_dispute f JOIN dim_furnisher fn ON f.furnisher_id = fn.furnisher_id
        WHERE f.status = 'Closed'
        GROUP BY fn.furnisher_id
        HAVING closed_disputes >= 10
        ORDER BY error_rate_pct DESC
        LIMIT 10
        """
    )
    fig, ax = plt.subplots(figsize=(7, 4))
    sns.barplot(data=df, y="furnisher_name", x="error_rate_pct", hue="quality_tier", dodge=False, ax=ax)
    ax.set_xlabel("Error rate % (updated + deleted outcomes)")
    ax.set_ylabel("")
    ax.set_title("Furnisher scorecard — 10 highest error rates")
    st.pyplot(fig)
    with st.expander("View underlying data"):
        st.dataframe(df, use_container_width=True)


def repeat_disputers():
    df = load(
        """
        SELECT c.consumer_id, c.state, COUNT(*) AS dispute_count,
               SUM(CASE WHEN f.outcome IN ('updated','deleted') THEN 1 ELSE 0 END) AS upheld_disputes
        FROM fact_dispute f JOIN dim_consumer c ON f.consumer_id = c.consumer_id
        GROUP BY c.consumer_id HAVING dispute_count > 1
        ORDER BY dispute_count DESC LIMIT 15
        """
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def channel_and_bureau():
    col1, col2 = st.columns(2)
    with col1:
        df = load(
            """
            SELECT channel, COUNT(*) AS disputes,
                   ROUND(100.0 * SUM(CASE WHEN status='Closed' AND sla_breached=1 THEN 1 ELSE 0 END)
                         / NULLIF(SUM(CASE WHEN status='Closed' THEN 1 ELSE 0 END), 0), 1) AS breach_pct
            FROM fact_dispute GROUP BY channel ORDER BY disputes DESC
            """
        )
        st.markdown("**By intake channel**")
        st.dataframe(df, use_container_width=True, hide_index=True)
    with col2:
        df = load(
            """
            SELECT b.bureau_name, COUNT(*) AS closed_disputes,
                   ROUND(100.0 * SUM(f.sla_breached) / COUNT(*), 1) AS breach_pct
            FROM fact_dispute f JOIN dim_bureau b ON f.bureau_id = b.bureau_id
            WHERE f.status = 'Closed' GROUP BY b.bureau_name ORDER BY breach_pct DESC
            """
        )
        st.markdown("**By bureau**")
        st.dataframe(df, use_container_width=True, hide_index=True)


def backlog_aging():
    df = load(
        """
        SELECT
            CASE
                WHEN julianday('now') - julianday(received_date) <= 15 THEN '0-15 days'
                WHEN julianday('now') - julianday(received_date) <= 30 THEN '16-30 days'
                ELSE '30+ days (overdue)'
            END AS age_bucket,
            COUNT(*) AS open_disputes
        FROM fact_dispute WHERE status = 'Open'
        GROUP BY age_bucket ORDER BY age_bucket
        """
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def data_quality():
    df = load(
        """
        SELECT reject_reason, COUNT(*) AS rejected_rows
        FROM etl_rejects GROUP BY reject_reason ORDER BY rejected_rows DESC LIMIT 10
        """
    )
    total_rejected = load("SELECT COUNT(*) AS n FROM etl_rejects").iloc[0]["n"]
    total_loaded = load("SELECT COUNT(*) AS n FROM fact_dispute").iloc[0]["n"]
    st.caption(
        f"ETL loaded {total_loaded:,} clean records and rejected {total_rejected:,} "
        f"(with reasons logged, not silently dropped)."
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------- Layout ----------------

st.title("BureauFlow — Dispute Operations Dashboard")
st.caption(
    "Synthetic data. Built on Metro 2 / FCRA-style dispute concepts for portfolio purposes only."
)

if not DB_PATH.exists():
    st.error(
        f"Couldn't find {DB_PATH.name}. Run `python src/init_db.py`, then "
        "`python src/generate_raw_data.py`, then `python src/etl.py` first."
    )
    st.stop()

kpi_row()
st.divider()

col1, col2 = st.columns([2, 1])
with col1:
    sla_trend()
with col2:
    outcome_mix()

col3, col4 = st.columns(2)
with col3:
    breach_by_reason()
with col4:
    furnisher_scorecard()

st.divider()
st.subheader("Repeat disputers")
repeat_disputers()

st.divider()
st.subheader("Channel & bureau comparison")
channel_and_bureau()

st.divider()
st.subheader("Open case backlog, aged")
backlog_aging()

st.divider()
st.subheader("Data quality — ETL reject summary")
data_quality()
