import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

from config.settings import settings
from utils import store

OUTCOMES = ("RESOLVED", "PARTIAL", "NEEDS_INFO", "ROUTED", "FAILED")
_UNMASKED_NUMBER = re.compile(r"(?<![\dX])\d{9,19}(?!\d)")


def load_records() -> List[Dict[str, Any]]:
    return store.list_audit()


def _pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def outcome_of(r: Dict[str, Any]) -> str:
    if set(r.get("detected_intents", [])) == {"GENERAL_INQUIRY"}:
        return "ROUTED"
    if r.get("has_partial_failure"):
        return "PARTIAL"
    data_calls = [c for c in r.get("api_calls", []) if c["api"].startswith("Get")]
    if any(c["status"] != "SUCCESS" for c in data_calls):
        return "FAILED"
    if any(v.get("status") == "UNAVAILABLE" for v in r.get("validations", [])):
        return "FAILED"
    if r.get("validation_status") in ("VALID", "NOT_APPLICABLE"):
        return "RESOLVED"
    return "NEEDS_INFO"


def pii_scan(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    leaks = []
    for r in records:
        texts = [r.get("response_masked", ""), r.get("subject", ""), json.dumps(r.get("entities_masked", {}))]
        texts += [json.dumps(c.get("request", {})) for c in r.get("api_calls", [])]
        if any(_UNMASKED_NUMBER.search(t or "") for t in texts):
            leaks.append(r.get("email_id"))
    scanned = len(records)
    return {"records_scanned": scanned, "leaks": len(leaks), "leak_ids": leaks[:10],
            "compliance_pct": round(100.0 * (scanned - len(leaks)) / scanned, 2) if scanned else 100.0}


def compute_metrics(records: List[Dict[str, Any]] = None, bucket_minutes: int = 1, buckets: int = 30) -> Dict[str, Any]:
    records = load_records() if records is None else records
    now = datetime.now()
    total = len(records)
    latencies = [r.get("total_execution_ms", 0.0) for r in records]
    outcomes = Counter(outcome_of(r) for r in records)

    intents, sentiments, validation = Counter(), Counter(), Counter()
    for r in records:
        intents.update(r.get("detected_intents", []))
        sentiments[r.get("sentiment", "NEUTRAL")] += 1
        validation[r.get("validation_status", "UNKNOWN")] += 1

    api: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"calls": 0, "success": 0, "failed": 0, "timeout": 0,
                                                           "retries": 0, "ms": [], "transports": Counter()})
    for r in records:
        for c in r.get("api_calls", []):
            a = api[c["api"]]
            a["calls"] += 1
            a["success" if c["status"] == "SUCCESS" else "timeout" if c["status"] == "TIMEOUT" else "failed"] += 1
            a["retries"] += max(0, c.get("attempts", 1) - 1)
            a["ms"].append(c.get("ms", 0.0))
            a["transports"][c.get("transport", "inprocess")] += 1
    api_table = [
        {"api": name, "calls": a["calls"], "success": a["success"], "failed": a["failed"], "timeout": a["timeout"],
         "retries": a["retries"], "success_pct": round(100.0 * a["success"] / a["calls"], 1) if a["calls"] else 0.0,
         "avg_ms": round(sum(a["ms"]) / len(a["ms"]), 1) if a["ms"] else 0.0, "p95_ms": _pct(a["ms"], 0.95),
         "transports": dict(a["transports"])}
        for name, a in sorted(api.items())
    ]

    start = now - timedelta(minutes=bucket_minutes * buckets)
    timeline = [{"t": (start + timedelta(minutes=bucket_minutes * (i + 1))).strftime("%H:%M"),
                 **{o: 0 for o in OUTCOMES}, "lat": []} for i in range(buckets)]
    recent_5m = 0
    for r in records:
        try:
            ts = datetime.fromisoformat(r["timestamp"])
        except (KeyError, ValueError):
            continue
        if ts >= now - timedelta(minutes=5):
            recent_5m += 1
        if ts < start:
            continue
        idx = min(buckets - 1, int((ts - start).total_seconds() // (60 * bucket_minutes)))
        timeline[idx][outcome_of(r)] += 1
        timeline[idx]["lat"].append(r.get("total_execution_ms", 0.0))
    for b in timeline:
        b["p95_ms"] = _pct(b.pop("lat"), 0.95)

    sla_ok = sum(1 for v in latencies if v <= settings.RESPONSE_SLA_MS)
    automated = outcomes["RESOLVED"] + outcomes["PARTIAL"]
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "total_processed": total,
        "outcomes": {o: outcomes.get(o, 0) for o in OUTCOMES},
        "automation_rate_pct": round(100.0 * automated / total, 1) if total else 0.0,
        "avg_latency_ms": round(sum(latencies) / total, 1) if total else 0.0,
        "p50_latency_ms": _pct(latencies, 0.5),
        "p95_latency_ms": _pct(latencies, 0.95),
        "sla_ms": settings.RESPONSE_SLA_MS,
        "sla_compliance_pct": round(100.0 * sla_ok / total, 1) if total else 100.0,
        "throughput_per_min_5m": round(recent_5m / 5.0, 2),
        "urgent_count": sum(1 for r in records if r.get("urgency_flag")),
        "partial_failure_count": outcomes["PARTIAL"],
        "flagged_for_review": sum(1 for r in records if r.get("requires_human_review")),
        "intent_distribution": dict(intents.most_common()),
        "sentiment_distribution": dict(sentiments),
        "validation_distribution": dict(validation),
        "api_performance": api_table,
        "timeline": timeline,
        "pii": pii_scan(records),
        "recent": [summarize(r) for r in reversed(records[-50:])],
    }


def summarize(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": r.get("timestamp"),
        "email_id": r.get("email_id"),
        "sender_masked": r.get("sender_masked"),
        "subject": r.get("subject"),
        "intents": r.get("detected_intents", []),
        "sentiment": r.get("sentiment"),
        "outcome": outcome_of(r),
        "apis": r.get("apis_called", []),
        "latency_ms": r.get("total_execution_ms"),
        "review": r.get("requires_human_review", False),
        "transport": r.get("api_transport"),
        "llm": r.get("llm_provider"),
    }


def find_record(email_id: str) -> Dict[str, Any]:
    return store.find_audit(email_id)
