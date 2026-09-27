"""
BureauFlow — Phase 3: human review console.

This is the ONLY place a triaged dispute becomes a real case in
fact_dispute. run_intake.py only ever proposes; nothing is committed to
the system of record without a reviewer clicking Approve here — including
items the policy engine marked 'auto_route'. Auto-route just means the
suggestion is pre-filled for a one-click accept; it does not skip the
human.

Run with:
    streamlit run src/agent_console.py
"""

import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from agent_core import BUREAU_MAP, get_connection, load_guidance, log_event

st.set_page_config(page_title="BureauFlow — Agent Review Console", layout="wide")

REVIEWER_NAME = "Esha (reviewer)"  # stand-in for a logged-in user in this portfolio build


@st.cache_data(ttl=5)
def load_pending():
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT q.*, f.furnisher_name, f.quality_tier
        FROM agent_review_queue q
        LEFT JOIN dim_furnisher f ON q.furnisher_id = f.furnisher_id
        WHERE q.status = 'pending'
        ORDER BY CASE q.policy_action WHEN 'escalate_human' THEN 0 ELSE 1 END, q.created_at
        """,
        conn,
    )
    conn.close()
    return df


@st.cache_data(ttl=5)
def load_stats():
    conn = get_connection()
    df = pd.read_sql("SELECT status, COUNT(*) AS n FROM agent_review_queue GROUP BY status", conn)
    conn.close()
    return {row["status"]: row["n"] for _, row in df.iterrows()}


def commit_case(row, final_reason_code: str):
    """Approve path: writes a new Open case into fact_dispute."""
    conn = get_connection()
    bureau_name = BUREAU_MAP.get(row["bureau_name_raw"].strip().lower(), "Equifax")
    bureau_id = conn.execute(
        "SELECT bureau_id FROM dim_bureau WHERE bureau_name = ?", (bureau_name,)
    ).fetchone()[0]

    received = date.today()
    due = received + timedelta(days=30)

    conn.execute(
        """
        INSERT INTO fact_dispute
            (dispute_id, consumer_id, furnisher_id, bureau_id, reason_code, channel,
             received_date, due_date, response_date, days_to_respond, sla_breached, status, outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 'Open', NULL)
        """,
        (
            f"AG{row['incoming_id']}", row["consumer_id"], row["furnisher_id"], bureau_id,
            final_reason_code, row["channel"], received.isoformat(), due.isoformat(),
        ),
    )
    conn.execute(
        "UPDATE agent_review_queue SET status='approved', final_reason_code=?, decided_by=?, "
        "decided_at=datetime('now') WHERE queue_id=?",
        (final_reason_code, REVIEWER_NAME, row["queue_id"]),
    )
    log_event(
        row["incoming_id"], "human_decision",
        {"decision": "approved", "final_reason_code": final_reason_code, "decided_by": REVIEWER_NAME},
        conn=conn,
    )
    log_event(
        row["incoming_id"], "committed",
        {"dispute_id": f"AG{row['incoming_id']}", "received_date": received.isoformat()},
        conn=conn,
    )
    conn.commit()
    conn.close()


def reject_case(row):
    conn = get_connection()
    conn.execute(
        "UPDATE agent_review_queue SET status='rejected', decided_by=?, decided_at=datetime('now') "
        "WHERE queue_id=?",
        (REVIEWER_NAME, row["queue_id"]),
    )
    log_event(row["incoming_id"], "human_decision", {"decision": "rejected", "decided_by": REVIEWER_NAME}, conn=conn)
    conn.commit()
    conn.close()


def render_item(row, guidance_lookup):
    suggested = row["suggested_reason_code"]
    badge = "🔴 Escalated" if row["policy_action"] == "escalate_human" else "🟢 Auto-route eligible"

    with st.container(border=True):
        top = st.columns([3, 1])
        with top[0]:
            st.markdown(f"**{row['incoming_id']}** — {badge}")
            st.write(f"> {row['raw_text']}")
        with top[1]:
            st.metric("Confidence", f"{row['confidence']:.2f}")

        st.caption(
            f"Consumer {row['consumer_id']} · Furnisher {row['furnisher_name']} "
            f"({row['quality_tier']} tier) · {row['channel']} · {row['bureau_name_raw']}"
        )
        st.caption(f"Policy rationale: {row['policy_rationale']}")

        with st.expander("Retrieved guidance (what the agent based this on)"):
            for hit in json.loads(row["retrieved_guidance"]):
                st.markdown(f"**{hit['reason_code']} — {hit['title']}** (similarity {hit['score']:.2f})")
                st.caption(guidance_lookup.get(hit["reason_code"], ""))

        code_options = list(guidance_lookup.keys())
        default_idx = code_options.index(suggested) if suggested in code_options else 0
        chosen = st.selectbox(
            "Final reason code (change if the agent got it wrong)",
            options=code_options,
            index=default_idx,
            format_func=lambda c: f"{c} — {guidance_lookup[c]}",
            key=f"select_{row['queue_id']}",
        )

        btn_cols = st.columns([1, 1, 4])
        if btn_cols[0].button("✅ Approve", key=f"approve_{row['queue_id']}"):
            commit_case(row, chosen)
            st.cache_data.clear()
            st.rerun()
        if btn_cols[1].button("❌ Reject", key=f"reject_{row['queue_id']}"):
            reject_case(row)
            st.cache_data.clear()
            st.rerun()


# ---------------- Layout ----------------

st.title("BureauFlow — Agent Review Console")
st.caption(
    "The agent proposes a reason code and a routing recommendation for each new dispute. "
    "Nothing reaches the case database until you approve it here — including 'auto-route eligible' items."
)

guidance_df = load_guidance().set_index("reason_code")
guidance_lookup = {code: row["title"] for code, row in guidance_df.iterrows()}

stats = load_stats()
c1, c2, c3 = st.columns(3)
c1.metric("Pending review", stats.get("pending", 0))
c2.metric("Approved", stats.get("approved", 0))
c3.metric("Rejected", stats.get("rejected", 0))

st.divider()

pending = load_pending()
if pending.empty:
    st.success("No items waiting for review. Run `python src/run_intake.py` to triage new submissions.")
else:
    for _, row in pending.iterrows():
        render_item(row, guidance_lookup)
