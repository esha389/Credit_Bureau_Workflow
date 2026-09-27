"""
BureauFlow — Phase 3: run the agent over unprocessed incoming disputes.

For each new submission: classify -> retrieve guidance -> decide routing
-> write the proposal to agent_review_queue -> log every step. This is
"the agent proposes" half of the pipeline. Nothing here touches
fact_dispute — that only happens when a human approves in agent_console.py.

Run after generate_incoming_disputes.py.
"""

import json
import sqlite3

from agent_core import (
    DB_PATH,
    classify,
    decide_policy,
    get_connection,
    log_event,
    retrieve,
    simulate_cost,
    timed,
)


def main():
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    pending = conn.execute(
        "SELECT * FROM incoming_disputes WHERE processed = 0"
    ).fetchall()

    if not pending:
        print("No unprocessed incoming disputes. Run generate_incoming_disputes.py first.")
        return

    # furnisher quality_tier lookup, used by the policy engine
    tiers = dict(conn.execute("SELECT furnisher_id, quality_tier FROM dim_furnisher").fetchall())

    auto_count = 0
    escalate_count = 0

    for row in pending:
        incoming_id = row["incoming_id"]
        text = row["raw_text"]

        (suggested_code, confidence), classify_latency_ms = timed(classify, text)
        log_event(
            incoming_id, "classified",
            {"suggested_reason_code": suggested_code, "confidence": confidence, "latency_ms": classify_latency_ms},
            conn=conn,
        )

        guidance_hits, retrieve_latency_ms = timed(retrieve, text, top_k=2)
        log_event(incoming_id, "retrieved", {"guidance": guidance_hits, "latency_ms": retrieve_latency_ms}, conn=conn)

        guidance_text = " ".join(h["guidance"] for h in guidance_hits)
        cost = simulate_cost(text, guidance_text)

        tier = tiers.get(row["furnisher_id"])
        action, rationale = decide_policy(suggested_code, confidence, tier)
        log_event(incoming_id, "policy_decision", {"action": action, "rationale": rationale}, conn=conn)

        conn.execute(
            """
            INSERT INTO agent_review_queue
                (incoming_id, consumer_id, furnisher_id, bureau_name_raw, channel, raw_text,
                 suggested_reason_code, confidence, retrieved_guidance, policy_action, policy_rationale,
                 classify_latency_ms, retrieve_latency_ms, simulated_cost_usd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incoming_id, row["consumer_id"], row["furnisher_id"], row["bureau_name_raw"],
                row["channel"], text, suggested_code, confidence, json.dumps(guidance_hits),
                action, rationale, classify_latency_ms, retrieve_latency_ms, cost,
            ),
        )
        conn.execute(
            "UPDATE incoming_disputes SET processed = 1 WHERE incoming_id = ?", (incoming_id,)
        )

        if action == "auto_route":
            auto_count += 1
        else:
            escalate_count += 1

    conn.commit()
    conn.close()

    print(f"Triaged {len(pending)} incoming disputes.")
    print(f"  Ready for one-click approval (auto_route): {auto_count}")
    print(f"  Flagged for careful review (escalate_human): {escalate_count}")
    print("Open the review console: streamlit run src/agent_console.py")


if __name__ == "__main__":
    main()
