"""
BureauFlow — Phase 4: evaluate the classifier against ground truth.

incoming_disputes.true_reason_code is only known because this is synthetic
data — in production you wouldn't have it. Here it plays the role of a
held-out labeled evaluation set: run this any time (e.g. after generating
more incoming disputes) to get a fresh accuracy data point in eval_runs,
the way a scheduled AI Ops job would monitor a model for drift.

Run any time after generate_incoming_disputes.py:
    python src/eval_classifier.py
"""

import json
from collections import defaultdict

from agent_core import classify, get_connection


def main():
    conn = get_connection()
    rows = conn.execute(
        "SELECT incoming_id, raw_text, true_reason_code FROM incoming_disputes"
    ).fetchall()

    if not rows:
        print("No incoming_disputes to evaluate. Run generate_incoming_disputes.py first.")
        return

    per_reason = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "support": 0})
    confusion = defaultdict(lambda: defaultdict(int))
    correct = 0

    for incoming_id, text, true_code in rows:
        pred_code, _ = classify(text)
        confusion[true_code][pred_code] += 1
        per_reason[true_code]["support"] += 1
        if pred_code == true_code:
            correct += 1
            per_reason[true_code]["tp"] += 1
        else:
            per_reason[true_code]["fn"] += 1
            per_reason[pred_code]["fp"] += 1

    n = len(rows)
    accuracy = round(correct / n, 4)

    per_reason_summary = {}
    for code, c in per_reason.items():
        precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else None
        recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else None
        per_reason_summary[code] = {
            "precision": round(precision, 3) if precision is not None else None,
            "recall": round(recall, 3) if recall is not None else None,
            "support": c["support"],
        }

    conn.execute(
        "INSERT INTO eval_runs (n_items, overall_accuracy, per_reason_json, confusion_json) VALUES (?, ?, ?, ?)",
        (
            n, accuracy, json.dumps(per_reason_summary),
            json.dumps({k: dict(v) for k, v in confusion.items()}),
        ),
    )
    conn.commit()
    conn.close()

    print(f"Evaluated {n} labeled items. Overall accuracy: {accuracy * 100:.1f}%")
    print("Per-reason precision / recall / support:")
    for code, m in sorted(per_reason_summary.items()):
        print(f"  {code}: precision={m['precision']}  recall={m['recall']}  support={m['support']}")


if __name__ == "__main__":
    main()
