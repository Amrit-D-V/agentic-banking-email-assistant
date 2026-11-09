from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from apis.api_client import banking_api_client
from email_worker import email_worker
from models.llm_client import llm_client
from utils import review_queue, store
from utils.metrics import compute_metrics

router = APIRouter()


def _line(name: str, value, labels: dict | None = None) -> str:
    label_text = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
    return f"{name}{label_text} {value}"


@router.get("/metrics", response_class=PlainTextResponse, tags=["System"], summary="Prometheus metrics")
def prometheus_metrics():
    m = compute_metrics()
    out = [
        "# HELP email_processed_total Emails processed, by outcome.",
        "# TYPE email_processed_total counter",
        *[_line("email_processed_total", n, {"outcome": o.lower()}) for o, n in m["outcomes"].items()],
        "# HELP email_latency_ms End-to-end processing latency.",
        "# TYPE email_latency_ms gauge",
        _line("email_latency_ms", m["avg_latency_ms"], {"stat": "avg"}),
        _line("email_latency_ms", m["p50_latency_ms"], {"stat": "p50"}),
        _line("email_latency_ms", m["p95_latency_ms"], {"stat": "p95"}),
        "# HELP email_sla_compliance_ratio Share of emails answered within the SLA.",
        "# TYPE email_sla_compliance_ratio gauge",
        _line("email_sla_compliance_ratio", round(m["sla_compliance_pct"] / 100, 4)),
        "# HELP core_banking_calls_total Core banking API calls, by API and status.",
        "# TYPE core_banking_calls_total counter",
    ]
    for a in m["api_performance"]:
        for status in ("success", "failed", "timeout"):
            out.append(_line("core_banking_calls_total", a[status], {"api": a["api"], "status": status}))
    out += [
        "# HELP core_banking_circuit_open Circuit breaker open (1) per API.",
        "# TYPE core_banking_circuit_open gauge",
        *[_line("core_banking_circuit_open", 1, {"api": api}) for api in banking_api_client.breaker.states()],
        "# HELP llm_calls_total LLM calls and fallbacks since start.",
        "# TYPE llm_calls_total counter",
        _line("llm_calls_total", llm_client.stats["llm_calls"], {"result": "attempted"}),
        _line("llm_calls_total", llm_client.stats["llm_failures"], {"result": "failed"}),
        _line("llm_calls_total", llm_client.stats["fallbacks"], {"result": "rules_fallback"}),
        "# HELP review_queue_pending Replies waiting for human approval.",
        "# TYPE review_queue_pending gauge",
        _line("review_queue_pending", len(review_queue.list_items(review_queue.PENDING))),
        "# HELP failed_emails_pending Emails in the failed (dead-letter) list.",
        "# TYPE failed_emails_pending gauge",
        _line("failed_emails_pending", len(store.list_failed())),
        "# HELP email_worker_queue_depth Emails waiting in the worker queue.",
        "# TYPE email_worker_queue_depth gauge",
        _line("email_worker_queue_depth", email_worker.status["queue_depth"]),
    ]
    return "\n".join(out) + "\n"
