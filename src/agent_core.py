"""
BureauFlow — Phase 3: agent core.

Design choice, disclosed up front rather than glossed over: reason-code
classification and guidance retrieval both run on TF-IDF + cosine
similarity (scikit-learn), not a hosted LLM. That's deliberate here: it's
free, fully reproducible, runs in milliseconds, and every score is
explainable ("this matched because of these words") rather than a black
box. It's a legitimate lightweight retrieval approach, not a placeholder
for a "real" implementation — swapping in an embedding model or an LLM
call later is a drop-in change to classify()/retrieve(), not a rewrite.

Pipeline: classify() -> retrieve() -> decide_policy() -> log_event()
Nothing here writes to fact_dispute. That happens only when a human
approves an item in agent_console.py.
"""

import json
import sqlite3
import time
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "bureauflow.db"
GUIDANCE_PATH = ROOT / "data" / "reference" / "fcra_guidance.csv"
AUDIT_JSONL_PATH = ROOT / "data" / "agent_audit_log.jsonl"

# Codes that always get a human's eyes on them, regardless of classifier confidence.
HIGH_RISK_CODES = {"R08"}  # suspected identity theft / fraud

# Below this cosine-similarity score, the agent isn't confident enough to
# recommend auto-routing.
CONFIDENCE_THRESHOLD = 0.30

BUREAU_MAP = {
    "equifax": "Equifax", "eqf": "Equifax",
    "experian": "Experian", "exp": "Experian",
    "transunion": "TransUnion", "tu": "TransUnion", "trans union": "TransUnion",
}


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def load_guidance() -> pd.DataFrame:
    return pd.read_csv(GUIDANCE_PATH)


class GuidanceIndex:
    """TF-IDF index over the reference guidance, shared by classify() and retrieve()."""

    def __init__(self):
        self.guidance = load_guidance()
        # keywords (typical consumer phrasing) boost matching signal for
        # classification but are never shown to the reviewer as "guidance"
        corpus = (
            self.guidance["title"] + ". " + self.guidance["guidance"] + " "
            + self.guidance["keywords"] + " " + self.guidance["keywords"]
        ).tolist()
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.doc_matrix = self.vectorizer.fit_transform(corpus)

    def scores_for(self, text: str):
        """Cosine similarity of `text` against every guidance doc, as a Series indexed by reason_code."""
        query_vec = self.vectorizer.transform([text])
        sims = cosine_similarity(query_vec, self.doc_matrix)[0]
        return pd.Series(sims, index=self.guidance["reason_code"])


_index = None


def get_index() -> GuidanceIndex:
    global _index
    if _index is None:
        _index = GuidanceIndex()
    return _index


def classify(raw_text: str):
    """Returns (suggested_reason_code, confidence) for a piece of free text."""
    scores = get_index().scores_for(raw_text)
    top_code = scores.idxmax()
    confidence = round(float(scores.max()), 4)
    return top_code, confidence


def retrieve(raw_text: str, top_k: int = 2):
    """Returns the top_k most relevant guidance snippets as a list of dicts."""
    scores = get_index().scores_for(raw_text)
    top = scores.sort_values(ascending=False).head(top_k)
    guidance = get_index().guidance.set_index("reason_code")
    return [
        {
            "reason_code": code,
            "title": guidance.loc[code, "title"],
            "guidance": guidance.loc[code, "guidance"],
            "score": round(float(score), 4),
        }
        for code, score in top.items()
    ]


def decide_policy(reason_code: str, confidence: float, furnisher_quality_tier: str | None):
    """
    Returns (action, rationale). action is 'auto_route' or 'escalate_human'.
    'auto_route' only means the agent PRE-FILLS the approval as a one-click
    accept in the console — a human still has to click it. Nothing reaches
    fact_dispute without that click, for either action.
    """
    if reason_code in HIGH_RISK_CODES:
        return "escalate_human", "High-risk reason code (fraud/identity theft) — always reviewed."
    if confidence < CONFIDENCE_THRESHOLD:
        return "escalate_human", f"Classifier confidence {confidence} below threshold {CONFIDENCE_THRESHOLD}."
    if furnisher_quality_tier == "poor":
        return "escalate_human", "Furnisher has a history of high error rates — extra scrutiny."
    return "auto_route", "Confident classification, low-risk reason code, furnisher in good standing."


# ---------------- Phase 4: AI Ops instrumentation ----------------
#
# classify()/retrieve() run local TF-IDF, so their real latency is near-zero
# and there's no actual API bill. The cost figure below is a deliberate
# SIMULATION of what this step would cost if it were routed through a
# hosted LLM instead — useful for practicing cost-monitoring instrumentation,
# not a claim about any vendor's real, current pricing.
SIMULATED_RATE_PER_1K_INPUT_TOKENS = 0.003
SIMULATED_RATE_PER_1K_OUTPUT_TOKENS = 0.015


def estimate_tokens(text: str) -> int:
    """Rough ~1.3-tokens-per-word estimate, for cost simulation only."""
    return max(1, round(len((text or "").split()) * 1.3))


def simulate_cost(input_text: str, output_text: str) -> float:
    in_tok = estimate_tokens(input_text)
    out_tok = estimate_tokens(output_text)
    cost = (
        (in_tok / 1000) * SIMULATED_RATE_PER_1K_INPUT_TOKENS
        + (out_tok / 1000) * SIMULATED_RATE_PER_1K_OUTPUT_TOKENS
    )
    return round(cost, 6)


def timed(fn, *args, **kwargs):
    """Runs fn(*args, **kwargs), returns (result, elapsed_ms)."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return result, round(elapsed_ms, 3)


def log_event(incoming_id: str, event_type: str, detail: dict, conn=None):
    """
    Dual-storage audit log: SQLite (queryable) + JSONL (append-only, portable).
    Pass an existing `conn` when calling this repeatedly inside a loop that
    already holds a connection open — SQLite's file-level locking means two
    separate open connections writing around the same time will deadlock
    each other with "database is locked".
    """
    owns_conn = conn is None
    if owns_conn:
        conn = get_connection()

    conn.execute(
        "INSERT INTO agent_audit_log (incoming_id, event_type, event_detail) VALUES (?, ?, ?)",
        (incoming_id, event_type, json.dumps(detail)),
    )
    if owns_conn:
        conn.commit()
        conn.close()

    AUDIT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_JSONL_PATH, "a") as f:
        record = {"incoming_id": incoming_id, "event_type": event_type, **detail}
        f.write(json.dumps(record) + "\n")
