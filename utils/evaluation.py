import json
import re
import statistics
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from config.settings import settings
from models.schemas import EmailInput

DATASET = settings.BASE_DIR / "sample_data" / "eval_emails.json"
EVAL_SENDER = "john.doe@example.com"


def _norm(values) -> set:
    return {re.sub(r"[ -]", "", str(v)).upper() for v in values or []}


def evaluate(dataset: Path = DATASET) -> Dict[str, Any]:
    from workflows.orchestrator import orchestrator

    cases = json.loads(Path(dataset).read_text(encoding="utf-8"))
    saved = settings.DATABASE_URL, settings.DEMO_CUSTOMER_EMAIL
    with tempfile.TemporaryDirectory() as tmp:
        settings.DATABASE_URL = f"sqlite:///{Path(tmp) / 'eval.db'}"
        settings.DEMO_CUSTOMER_EMAIL = EVAL_SENDER
        try:
            results = [_run_case(orchestrator, c) for c in cases]
        finally:
            settings.DATABASE_URL, settings.DEMO_CUSTOMER_EMAIL = saved
    return _report(results)


def _run_case(orchestrator, case: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    state = orchestrator.process_email(EmailInput(sender=EVAL_SENDER, subject="Customer request", body=case["body"], channel="eval"))
    got_intents = {i.value for i in state.detected_intents}
    checks = {
        "intents": got_intents == set(case["intents"]),
        "accounts": _norm(state.entities.account_numbers) == _norm(case["accounts"]),
        "cards": _norm(state.entities.card_numbers) == _norm(case["cards"]),
        "sentiment": state.sentiment.value == case["sentiment"],
    }
    if "count" in case:
        checks["count"] = state.entities.transaction_count == case["count"]
    if "period" in case:
        checks["period"] = state.entities.statement_period == case["period"]
    return {
        "id": case["id"], "body": case["body"], "expected": set(case["intents"]), "got": got_intents,
        "checks": checks, "ms": (time.perf_counter() - t0) * 1000,
        "got_detail": {"accounts": state.entities.account_numbers, "cards": state.entities.card_numbers,
                       "count": state.entities.transaction_count, "period": state.entities.statement_period,
                       "sentiment": state.sentiment.value},
    }


def _report(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    fields = ["intents", "accounts", "cards", "count", "period", "sentiment"]
    accuracy = {}
    for f in fields:
        scored = [r["checks"][f] for r in results if f in r["checks"]]
        accuracy[f] = {"correct": sum(scored), "total": len(scored), "pct": round(100 * sum(scored) / len(scored), 1) if scored else None}

    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in results:
        for i in r["got"] & r["expected"]:
            tp[i] += 1
        for i in r["got"] - r["expected"]:
            fp[i] += 1
        for i in r["expected"] - r["got"]:
            fn[i] += 1
    per_intent = {}
    for i in sorted(set(tp) | set(fp) | set(fn)):
        p = tp[i] / (tp[i] + fp[i]) if tp[i] + fp[i] else 0.0
        rc = tp[i] / (tp[i] + fn[i]) if tp[i] + fn[i] else 0.0
        per_intent[i] = {"precision": round(p, 3), "recall": round(rc, 3), "f1": round(2 * p * rc / (p + rc), 3) if p + rc else 0.0,
                         "support": tp[i] + fn[i]}

    latencies = [r["ms"] for r in results]
    return {
        "cases": len(results),
        "fully_correct": sum(all(r["checks"].values()) for r in results),
        "accuracy": accuracy,
        "per_intent": per_intent,
        "latency_ms": {"median": round(statistics.median(latencies), 1), "max": round(max(latencies), 1)},
        "llm_provider": settings.LLM_PROVIDER,
        "model": settings.OLLAMA_MODEL,
        "failures": [
            {"id": r["id"], "body": r["body"][:90], "failed": [k for k, ok in r["checks"].items() if not ok],
             "expected_intents": sorted(r["expected"]), "got_intents": sorted(r["got"]), "got": r["got_detail"]}
            for r in results if not all(r["checks"].values())
        ],
    }
