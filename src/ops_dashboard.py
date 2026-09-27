"""
BureauFlow — Phase 4: AI Ops monitoring dashboard.

Answers the question an AI Ops role actually cares about: not just "does
the agent work", but "how do you know it's still working, and what does
it cost to run". Reads the same bureauflow.db as everything else.

Run with:
    streamlit run src/ops_dashboard.py
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st

from agent_core import get_connection

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"

sns.set_style("whitegrid")
st.set_page_config(page_title="BureauFlow — AI Ops Dashboard", layout="wide")

ACCURACY_ALERT_THRESHOLD = 0.85
ESCALATION_RATE_ALERT = 0.45  # if more than this share of items get escalated, flag it


@st.cache_data(ttl=5)
def load(query: str) -> pd.DataFrame:
    return pd.read_sql(query, get_connection())


def latest_eval():
    df = load("SELECT * FROM eval_runs ORDER BY run_id DESC LIMIT 1")
    return None if df.empty else df.iloc[0]


def kpi_row():
    latest = latest_eval()
    escalation = load(
        "SELECT AVG(CASE WHEN policy_action='escalate_human' THEN 1.0 ELSE 0 END) AS rate FROM agent_review_queue"
    ).iloc[0]["rate"]
    latency = load(
        "SELECT AVG(classify_latency_ms + retrieve_latency_ms) AS avg_ms FROM agent_review_queue "
        "WHERE classify_latency_ms IS NOT NULL"
    ).iloc[0]["avg_ms"]
    total_cost = load(
        "SELECT SUM(simulated_cost_usd) AS total FROM agent_review_queue"
    ).iloc[0]["total"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest eval accuracy", f"{latest['overall_accuracy']*100:.1f}%" if latest is not None else "—")
    c2.metric("Escalation rate", f"{escalation*100:.1f}%" if escalation is not None else "—")
    c3.metric("Avg. agent latency", f"{latency:.2f} ms" if latency is not None else "—")
    c4.metric("Simulated cost so far", f"${total_cost:.4f}" if total_cost is not None else "—")


def alerts():
    latest = latest_eval()
    escalation = load(
        "SELECT AVG(CASE WHEN policy_action='escalate_human' THEN 1.0 ELSE 0 END) AS rate FROM agent_review_queue"
    ).iloc[0]["rate"]

    msgs = []
    if latest is not None and latest["overall_accuracy"] < ACCURACY_ALERT_THRESHOLD:
        msgs.append(
            f"⚠️ Latest eval accuracy ({latest['overall_accuracy']*100:.1f}%) is below the "
            f"{ACCURACY_ALERT_THRESHOLD*100:.0f}% threshold — worth checking for a shift in incoming dispute patterns."
        )
    if escalation is not None and escalation > ESCALATION_RATE_ALERT:
        msgs.append(
            f"⚠️ Escalation rate ({escalation*100:.1f}%) is unusually high — more cases than usual are "
            "needing human review, which may mean confidence is dropping or fraud-pattern volume has shifted."
        )
    if msgs:
        for m in msgs:
            st.warning(m)
    else:
        st.success("No alerts — accuracy and escalation rate are within expected ranges.")


def accuracy_trend():
    df = load("SELECT run_id, run_at, overall_accuracy, n_items FROM eval_runs ORDER BY run_id")
    if len(df) < 2:
        st.info(
            "Only one eval run so far — run `python src/eval_classifier.py` again after a new "
            "batch of incoming disputes to start building a trend line."
        )
        st.dataframe(df, width='stretch', hide_index=True)
        return
    fig, ax = plt.subplots(figsize=(8, 3))
    sns.lineplot(data=df, x="run_id", y="overall_accuracy", marker="o", ax=ax, color="#2E86AB")
    ax.axhline(ACCURACY_ALERT_THRESHOLD, color="#C0392B", linestyle="--", linewidth=1, label="alert threshold")
    ax.set_ylim(0, 1)
    ax.set_xlabel("Eval run #")
    ax.set_ylabel("Accuracy")
    ax.set_title("Classifier accuracy over evaluation runs")
    ax.legend()
    st.pyplot(fig)


def confidence_distribution():
    df = load("SELECT confidence, policy_action FROM agent_review_queue")
    fig, ax = plt.subplots(figsize=(6, 3.5))
    sns.histplot(data=df, x="confidence", hue="policy_action", bins=20, ax=ax, multiple="stack")
    ax.set_title("Classifier confidence distribution")
    st.pyplot(fig)


def escalation_over_time():
    df = load(
        """
        SELECT date(created_at) AS day,
               AVG(CASE WHEN policy_action='escalate_human' THEN 1.0 ELSE 0 END) AS escalation_rate,
               COUNT(*) AS n
        FROM agent_review_queue GROUP BY day ORDER BY day
        """
    )
    if len(df) < 2:
        st.caption("Escalation rate by day (needs more than one day of intake batches to show a trend):")
        st.dataframe(df, width='stretch', hide_index=True)
        return
    fig, ax = plt.subplots(figsize=(8, 3))
    sns.barplot(data=df, x="day", y="escalation_rate", color="#F5B041", ax=ax)
    ax.set_ylabel("Escalation rate")
    ax.set_title("Escalation rate by day")
    st.pyplot(fig)


def latency_and_cost():
    df = load(
        "SELECT classify_latency_ms, retrieve_latency_ms, simulated_cost_usd, created_at "
        "FROM agent_review_queue WHERE classify_latency_ms IS NOT NULL ORDER BY queue_id"
    )
    if df.empty:
        st.info(
            "No latency/cost data yet — run `python src/init_ops_db.py` then a fresh "
            "`generate_incoming_disputes.py` + `run_intake.py` batch."
        )
        return

    col1, col2 = st.columns(2)
    with col1:
        fig, ax = plt.subplots(figsize=(6, 3.5))
        melted = df.melt(
            value_vars=["classify_latency_ms", "retrieve_latency_ms"],
            var_name="step", value_name="latency_ms",
        )
        sns.boxplot(data=melted, x="step", y="latency_ms", ax=ax)
        ax.set_title("Latency by pipeline step (ms)")
        ax.set_xlabel("")
        st.pyplot(fig)
        p50 = df["classify_latency_ms"].add(df["retrieve_latency_ms"]).quantile(0.5)
        p95 = df["classify_latency_ms"].add(df["retrieve_latency_ms"]).quantile(0.95)
        st.caption(f"Combined latency — p50: {p50:.2f} ms · p95: {p95:.2f} ms")

    with col2:
        df["cumulative_cost"] = df["simulated_cost_usd"].cumsum()
        fig, ax = plt.subplots(figsize=(6, 3.5))
        sns.lineplot(data=df.reset_index(), x="index", y="cumulative_cost", ax=ax, color="#2E86AB")
        ax.set_xlabel("Items processed")
        ax.set_ylabel("Cumulative simulated cost ($)")
        ax.set_title("Simulated cumulative cost")
        st.pyplot(fig)
        st.caption(
            f"Total so far: ${df['simulated_cost_usd'].sum():.4f} · "
            f"illustrative rate, not tied to a specific vendor's current pricing"
        )


def per_reason_table():
    latest = latest_eval()
    if latest is None:
        return
    per_reason = json.loads(latest["per_reason_json"])
    rows = [{"reason_code": k, **v} for k, v in sorted(per_reason.items())]
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    st.caption(f"From eval run #{int(latest['run_id'])} at {latest['run_at']} ({int(latest['n_items'])} labeled items)")


# ---------------- Layout ----------------

st.title("BureauFlow — AI Ops Dashboard")
st.caption("Monitoring the agent layer: is it still accurate, how much is it escalating, how fast, and what it costs.")

if not DB_PATH.exists():
    st.error(f"Couldn't find {DB_PATH.name}. Run Phase 1 first.")
    st.stop()

kpi_row()
st.divider()
alerts()
st.divider()

st.subheader("Accuracy over time")
accuracy_trend()

col1, col2 = st.columns(2)
with col1:
    st.subheader("Confidence distribution")
    confidence_distribution()
with col2:
    st.subheader("Escalation rate")
    escalation_over_time()

st.divider()
st.subheader("Latency & simulated cost")
latency_and_cost()

st.divider()
st.subheader("Per-reason-code precision / recall (latest eval)")
per_reason_table()
