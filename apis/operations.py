import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from apis.api_client import banking_api_client
from apis.auth import require_admin
from config.settings import settings
from email_worker import email_worker
from models.llm_client import llm_client
from sample_data.sample_emails import SAMPLE_EMAILS, SCENARIO_TITLES, fresh_copy
from utils import review_queue, store
from utils.document_reader import OCR_AVAILABLE
from utils.pii_masker import mask_email
from utils.metrics import compute_metrics, find_record
from utils.policy_rag import policy_rag

router = APIRouter(prefix="/api/v1/ops", tags=["Operations & Control"])

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


@router.get("/metrics")
def metrics():
    m = compute_metrics()
    m["review_pending"] = len(review_queue.list_items(review_queue.PENDING))
    m["llm_stats"] = llm_client.stats
    return m


def _probe(fn) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = "OFFLINE", str(e)[:120]
    return {"status": status, "detail": detail, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def _probe_cbs():
    open_circuits = banking_api_client.breaker.states()
    if open_circuits:
        return "DEGRADED", "circuit open: " + ", ".join(f"{api} ({st})" for api, st in open_circuits.items())
    data, log = banking_api_client.invoke("ValidateAccountAPI", {"account_number": "1234567890"})
    if "error" in data:
        return "DEGRADED", data["error"]
    return "ONLINE", f"all circuits closed · via {settings.BANKING_API_TRANSPORT}"


def _probe_mcp():
    from apis.mcp_client import mcp_banking_client

    if mcp_banking_client._session is None and settings.BANKING_API_TRANSPORT != "mcp":
        return "STANDBY", "Starts when Core banking connection is set to MCP"
    data = mcp_banking_client.call_tool("validate_account", {"account_number": "1234567890"}, timeout=5)
    return ("ONLINE" if data.get("status") == "VALID" else "DEGRADED"), f"{len(mcp_banking_client.tools)} tools over stdio"


@router.get("/health")
def health():
    llm = llm_client.health()
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "components": {
            "Core Banking (CBS/CMS)": _probe(_probe_cbs),
            "MCP Banking Server": _probe(_probe_mcp),
            "LLaMA (Ollama)": {**llm, "ms": 0},
            "OCR (Tesseract)": {"status": "ONLINE" if OCR_AVAILABLE else "OFFLINE",
                                "detail": "image + scanned PDF attachments" if OCR_AVAILABLE else "tesseract not installed", "ms": 0},
            "Policy RAG (FAISS)": {"status": "ONLINE" if policy_rag.chunks else "OFFLINE",
                                   "detail": f"{len(policy_rag.chunks)} policy chunks indexed", "ms": 0},
            "Database": _probe(lambda: ("ONLINE", store.healthcheck())),
            "Email Worker (IMAP/SMTP)": {
                "status": "ONLINE" if email_worker.status["running"] else ("STOPPED" if email_worker.configured else "NOT CONFIGURED"),
                "detail": email_worker.user or "set EMAIL_USER / EMAIL_PASS", "ms": 0},
        },
    }


@router.get("/records/{email_id}")
def record(email_id: str):
    r = find_record(email_id)
    if not r:
        raise HTTPException(404, "Record not found")
    return r


@router.get("/export")
def export_audit():
    return StreamingResponse(store.iter_audit_jsonl(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=audit_trail.jsonl"})


class RuntimeConfig(BaseModel):
    LLM_PROVIDER: Optional[Literal["ollama", "mock"]] = None
    BANKING_API_TRANSPORT: Optional[Literal["inprocess", "http", "mcp"]] = None
    HITL_ENABLED: Optional[bool] = None
    ENFORCE_SENDER_OWNERSHIP: Optional[bool] = None
    REQUIRE_REGISTERED_SENDER: Optional[bool] = None
    MOCK_FAILURE_RATE: Optional[float] = Field(None, ge=0.0, le=1.0)
    API_TIMEOUT_SECONDS: Optional[float] = Field(None, gt=0.0, le=30.0)
    API_MAX_RETRIES: Optional[int] = Field(None, ge=0, le=5)


def _config() -> Dict[str, Any]:
    return {k: getattr(settings, k) for k in RuntimeConfig.model_fields} | {"OLLAMA_MODEL": settings.OLLAMA_MODEL}


@router.get("/config")
def get_config():
    return _config()


@router.post("/config")
def set_config(cfg: RuntimeConfig):
    changes = cfg.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(settings, key, value)
    store.save_config(changes)
    return _config()


def apply_saved_config() -> None:
    for key, value in store.load_config().items():
        if key in RuntimeConfig.model_fields:
            setattr(settings, key, value)


@router.get("/scenarios")
def scenarios():
    return [{"key": k, "title": SCENARIO_TITLES.get(k, k), "sender": e.sender, "subject": e.subject, "body": e.body,
             "attachments": [Path(p).name for p in e.attachment_paths]} for k, e in SAMPLE_EMAILS.items()]


def _summary(state) -> Dict[str, Any]:
    return {"email_id": state.email.email_id, "intents": [i.value for i in state.detected_intents],
            "sentiment": state.sentiment.value, "partial": state.has_partial_failure,
            "review": state.requires_human_review, "latency_ms": state.total_execution_ms,
            "apis": state.selected_apis, "response": state.masked_response}


@router.post("/scenarios/{key}/run")
def run_scenario(key: str):
    from workflows.orchestrator import orchestrator

    if key not in SAMPLE_EMAILS:
        raise HTTPException(404, "Unknown scenario")
    return _summary(orchestrator.process_email(fresh_copy(key)))


def _start_job(kind: str, keys, concurrency: int) -> Dict[str, Any]:
    from workflows.orchestrator import orchestrator

    job_id = uuid.uuid4().hex[:8]
    job = {"id": job_id, "kind": kind, "total": len(keys), "done": 0, "failed": 0, "status": "RUNNING",
           "started_at": time.time(), "elapsed_s": 0.0, "throughput_per_s": 0.0}
    with _jobs_lock:
        _jobs[job_id] = job

    def one(key):
        try:
            orchestrator.process_email(fresh_copy(key))
        except Exception:
            job["failed"] += 1
        finally:
            with _jobs_lock:
                job["done"] += 1
                job["elapsed_s"] = round(time.time() - job["started_at"], 2)
                job["throughput_per_s"] = round(job["done"] / max(job["elapsed_s"], 0.001), 2)

    def run():
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(one, keys))
        job["status"] = "COMPLETED"

    threading.Thread(target=run, daemon=True, name=f"job-{job_id}").start()
    return job


class LoadTest(BaseModel):
    count: int = Field(50, ge=1, le=1000)
    concurrency: int = Field(8, ge=1, le=32)
    include_faults: bool = False


@router.post("/run-all")
def run_all():
    return _start_job("run-all", list(SAMPLE_EMAILS), concurrency=1)


@router.post("/load-test")
def load_test(cfg: LoadTest):
    pool = [k for k in SAMPLE_EMAILS if cfg.include_faults or k not in ("scenario_10_api_timeout", "scenario_11_api_outage")]
    return _start_job("load-test", [random.choice(pool) for _ in range(cfg.count)], cfg.concurrency)


@router.get("/jobs")
def jobs():
    with _jobs_lock:
        return sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)[:10]


@router.post("/probe-mcp")
def probe_mcp():
    from apis.mcp_client import mcp_banking_client

    try:
        data = mcp_banking_client.call_tool("validate_account", {"account_number": "1234567890"}, timeout=10)
        return {"status": "ONLINE", "tools": mcp_banking_client.tools, "sample": data}
    except Exception as e:
        raise HTTPException(503, f"MCP probe failed: {e}")


@router.get("/worker")
def worker_status():
    return {**email_worker.status, "configured": email_worker.configured}


@router.post("/worker/start")
def worker_start():
    err = email_worker.start_background()
    if err:
        raise HTTPException(400, err)
    time.sleep(0.3)
    return worker_status()


@router.post("/worker/stop")
def worker_stop():
    email_worker.stop()
    return worker_status()


@router.get("/reviews")
def reviews(status: Optional[str] = None):
    items = review_queue.list_items(status)
    for i in items:
        i.pop("reply_to", None)
    return list(reversed(items))


class Decision(BaseModel):
    note: str = ""


def _decide(email_id: str, approve: bool, note: str, reviewer: str):
    item = review_queue.decide(email_id, approve=approve, reviewer=reviewer, note=note)
    if not item:
        raise HTTPException(409, "Item not found or already decided")
    delivery = "not sent (rejected)"
    if approve:
        if item.get("channel") == "email" and email_worker.configured:
            try:
                email_worker.send_reply(item["reply_to"], item["subject"], item["draft"])
                delivery = "sent via SMTP"
            except Exception as e:
                delivery = f"send failed: {e}"
        else:
            delivery = f"released ({item.get('channel')} channel, no SMTP delivery)"
    return {"email_id": email_id, "status": item["status"], "delivery": delivery, "decided_by": reviewer}


@router.post("/reviews/{email_id}/approve")
def approve(email_id: str, d: Decision = Decision(), user: str = Depends(require_admin)):
    return _decide(email_id, True, d.note, user)


@router.post("/reviews/{email_id}/reject")
def reject(email_id: str, d: Decision = Decision(), user: str = Depends(require_admin)):
    return _decide(email_id, False, d.note, user)


@router.get("/failed")
def failed_emails():
    items = store.list_failed()
    for i in items:
        i["sender"] = mask_email(i["payload"].get("sender"))
        i["subject"] = i["payload"].get("subject", "")
        i.pop("payload")
    return items


@router.post("/failed/{item_id}/retry")
def retry_failed(item_id: int):
    from models.schemas import EmailInput
    from workflows.orchestrator import orchestrator

    item = next((i for i in store.list_failed() if i["id"] == item_id), None)
    if not item:
        raise HTTPException(404, "Failed email not found or already retried")
    payload = {k: v for k, v in item["payload"].items() if k not in ("email_id", "received_at")}
    try:
        state = orchestrator.process_email(EmailInput(**payload))
    except Exception as e:
        store.set_failed_status(item_id, "FAILED", f"{type(e).__name__}: {e}")
        raise HTTPException(500, f"Retry failed again: {e}")
    delivery = "processed"
    if payload.get("channel") == "email" and email_worker.configured and not (settings.HITL_ENABLED and state.requires_human_review):
        email_worker.send_reply(payload["sender"], state.final_email_subject, state.masked_response)
        store.mark_processed(payload.get("message_id"), state.email.email_id)
        delivery = "reply sent via SMTP"
    store.set_failed_status(item_id, "RETRIED")
    return {"id": item_id, "email_id": state.email.email_id, "delivery": delivery}


@router.post("/reset")
def reset():
    store.clear_activity()
    with _jobs_lock:
        _jobs.clear()
    for k in llm_client.stats:
        llm_client.stats[k] = 0
    return {"status": "cleared"}
