import threading
import time

from fastapi.testclient import TestClient

from apis.api_client import BankingApiClient, banking_api_client
from apis.mock_banking_service import SIMULATED_OUTAGE_ACCOUNT
from config.settings import settings
from email_worker import EmailWorker
from models.schemas import EmailInput
from sample_data.sample_emails import fresh_copy
from utils import store
from workflows.orchestrator import orchestrator


def client():
    from apis.banking_api_server import app

    return TestClient(app)


def test_circuit_opens_after_repeated_failures_and_fails_fast(monkeypatch):
    monkeypatch.setattr(settings, "CIRCUIT_FAILURE_THRESHOLD", 2)
    monkeypatch.setattr(settings, "API_MAX_RETRIES", 0)
    api = BankingApiClient(transport="inprocess")
    for _ in range(2):
        assert api.get_account_balance(SIMULATED_OUTAGE_ACCOUNT)[0]["error_type"] == "UNAVAILABLE"
    data, log = api.get_account_balance("1234567890")
    assert data["error_type"] == "CIRCUIT_OPEN" and log.attempts == 0
    assert api.breaker.states() == {"GetAccountBalanceAPI": "OPEN"}


def test_circuit_recovers_after_reset_window(monkeypatch):
    monkeypatch.setattr(settings, "CIRCUIT_FAILURE_THRESHOLD", 1)
    monkeypatch.setattr(settings, "CIRCUIT_RESET_SECONDS", 0.05)
    monkeypatch.setattr(settings, "API_MAX_RETRIES", 0)
    api = BankingApiClient(transport="inprocess")
    api.get_account_balance(SIMULATED_OUTAGE_ACCOUNT)
    time.sleep(0.06)
    data, _ = api.get_account_balance("1234567890")
    assert data["available_balance"] == 125000.0
    assert api.breaker.states() == {}


def test_not_found_does_not_open_circuit(monkeypatch):
    monkeypatch.setattr(settings, "CIRCUIT_FAILURE_THRESHOLD", 1)
    api = BankingApiClient(transport="inprocess")
    api.get_account_balance("0000000000")
    assert api.breaker.states() == {}


def test_validation_lookups_are_cached():
    api = BankingApiClient(transport="inprocess")
    _, first = api.validate_account("1234567890")
    _, second = api.validate_account("1234567890")
    assert first.transport == "inprocess" and second.transport == "cache"
    _, balance1 = api.get_account_balance("1234567890")
    _, balance2 = api.get_account_balance("1234567890")
    assert balance2.transport == "inprocess"


def test_agent_timings_cover_every_agent():
    state = orchestrator.process_email(fresh_copy("scenario_4_multi_intent"))
    agents = {t["agent"] for t in state.agent_timings}
    assert {"EmailUnderstandingAgent", "IntentClassificationAgent", "SentimentAnalysisAgent", "EntityExtractionAgent",
            "ValidationAgent", "APISelectionAgent", "ResponseGenerationAgent", "AuditLoggingAgent"} <= agents
    rec = store.find_audit(state.email.email_id)
    assert len(rec["agent_timings"]) >= 7


def _worker(monkeypatch, batch):
    worker = EmailWorker(user="bank@example.com", pwd="x")
    sent = []
    monkeypatch.setattr(worker, "fetch_unseen", lambda batch_size=None: list(batch))
    monkeypatch.setattr(worker, "send_reply", lambda to, subj, body: sent.append(subj))
    monkeypatch.setattr(worker, "mark_seen", lambda mid: None)
    return worker, sent


def test_same_message_is_never_answered_twice(monkeypatch):
    mail = fresh_copy("scenario_1_balance")
    mail.message_id = "<abc123@mail.example.com>"
    worker, sent = _worker(monkeypatch, [("1", mail)])
    worker.process_pending()
    worker.process_pending()
    assert len(sent) == 1
    assert worker.status["skipped_duplicates"] == 1


def test_crashing_email_goes_to_failed_list_and_can_be_retried(monkeypatch):
    mail = fresh_copy("scenario_1_balance")
    worker, sent = _worker(monkeypatch, [("1", mail)])
    original = orchestrator.process_email
    monkeypatch.setattr(orchestrator, "process_email", lambda m: (_ for _ in ()).throw(RuntimeError("boom")))
    worker.process_pending()
    assert sent == [] and worker.status["failed"] == 1
    failed = client().get("/api/v1/ops/failed").json()
    assert len(failed) == 1 and "boom" in failed[0]["error"]

    monkeypatch.setattr(orchestrator, "process_email", original)
    res = client().post(f"/api/v1/ops/failed/{failed[0]['id']}/retry").json()
    assert res["delivery"] == "processed"
    assert client().get("/api/v1/ops/failed").json() == []


def test_queue_mode_processes_with_worker_pool(monkeypatch):
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 3)
    batch = [(str(i), fresh_copy("scenario_1_balance")) for i in range(5)]
    worker, sent = _worker(monkeypatch, batch)
    consumers = [threading.Thread(target=worker._consume, daemon=True) for _ in range(3)]
    for t in consumers:
        t.start()
    assert worker.poll_once() == 5
    worker.inbox_queue.join()
    worker.stop_event.set()
    assert len(sent) == 5 and worker.status["queue_depth"] == 0


def test_prometheus_metrics_endpoint():
    orchestrator.process_email(fresh_copy("scenario_5_partial_failure"))
    text = client().get("/metrics").text
    assert 'email_processed_total{outcome="partial"} 1' in text
    assert 'core_banking_calls_total{api="ValidateCardAPI",status="success"}' in text
    assert "review_queue_pending" in text


def test_database_is_created_by_migrations():
    from sqlalchemy import inspect

    tables = set(inspect(store.engine()).get_table_names())
    assert {"alembic_version", "audit_records", "review_items", "processed_messages", "failed_emails"} <= tables


def test_rule_engine_accuracy_does_not_regress():
    from utils.evaluation import evaluate

    report = evaluate()
    assert report["accuracy"]["intents"]["pct"] >= 85.0
    for field in ("accounts", "cards", "count", "period"):
        assert report["accuracy"][field]["pct"] == 100.0
