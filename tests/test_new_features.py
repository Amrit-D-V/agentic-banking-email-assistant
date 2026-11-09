import email as email_lib
from email.mime.text import MIMEText

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from email_worker import EmailWorker, sender_verdict
from models.llm_client import llm_client
from models.schemas import EmailInput, EntityValidationStatus, IntentType
from sample_data.sample_emails import fresh_copy
from utils import store
from workflows.orchestrator import orchestrator


def run(key):
    return orchestrator.process_email(fresh_copy(key))


def test_several_accounts_and_cards_in_one_email():
    state = run("scenario_15_multiple_accounts")
    assert state.entities.account_numbers == ["1234567890", "1234509876"]
    assert state.entities.card_numbers == ["4567XXXX8901", "999999999"]
    balances = [f for f in state.fulfilments if f["api"] == "GetAccountBalanceAPI"]
    assert {f["value"] for f in balances} == {"1234567890", "1234509876"}
    assert state.has_partial_failure is True
    resp = state.masked_response
    assert "XXXX7890" in resp and "XXXX9876" in resp
    assert "INR 1,25,000.00" in resp and "INR 48,250.75" in resp
    assert "Amazon India" in resp
    assert "XXXX-XXXX-XXXX-9999" in resp and "could not be validated" in resp


def test_unregistered_sender_gets_no_account_data():
    state = run("scenario_17_unregistered_sender")
    assert all(v.additional_info.get("reason") == "UNREGISTERED_SENDER" for v in state.validation_summary.validations)
    assert not any(c.api_name.startswith("Validate") or c.api_name.startswith("Get") for c in state.api_call_logs)
    assert "registered with the bank" in state.masked_response
    assert "1,25,000" not in state.masked_response


def test_unregistered_sender_still_gets_policy_answers():
    state = orchestrator.process_email(EmailInput(
        sender="stranger@example.com", subject="Charges",
        body="What is the minimum balance and the penalty charges for a savings account in metro branches?"))
    assert state.detected_intents == [IntentType.POLICY_INQUIRY]
    assert "10,000" in state.masked_response


def test_registered_sender_failing_dkim_is_treated_as_unregistered():
    mail = fresh_copy("scenario_1_balance")
    mail.sender_verified = False
    state = orchestrator.process_email(mail)
    assert state.customer_profile == {}
    assert "1,25,000" not in state.masked_response
    assert "registered with the bank" in state.masked_response


def test_open_mode_allows_unknown_senders(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_REGISTERED_SENDER", False)
    state = run("scenario_17_unregistered_sender")
    assert state.validation_summary.validations[0].status == EntityValidationStatus.VALID
    assert state.masked_response.startswith("Dear Customer,")
    assert "John Doe" not in state.masked_response


@pytest.mark.parametrize("header,expected", [
    ("mx.google.com; dkim=pass header.i=@example.com; spf=pass", True),
    ("mx.google.com; spf=softfail; dkim=none", False),
    ("mx.google.com; dkim=pass; dmarc=fail", False),
    (None, None),
])
def test_sender_verdict_from_authentication_results(header, expected):
    msg = MIMEText("hi")
    if header:
        msg["Authentication-Results"] = header
    assert sender_verdict(email_lib.message_from_bytes(msg.as_bytes())) is expected


def test_hindi_email_is_translated_then_understood(monkeypatch):
    monkeypatch.setattr(llm_client, "generate", lambda prompt, system_prompt="", fallback="":
                        "Please tell me the balance of my account number 1234567890.")
    state = run("scenario_16_hindi")
    assert state.detected_language == "hi"
    assert state.translated_body.startswith("Please tell me the balance")
    assert state.detected_intents == [IntentType.BALANCE_ENQUIRY]
    assert "received your email in Hindi" in state.masked_response
    assert "INR 1,25,000.00" in state.masked_response


@pytest.mark.parametrize("bad", ["I can't do that. Is there anything else I can help you with?",
                                 "Please tell me my balance."])
def test_bad_translation_is_rejected(monkeypatch, bad):
    monkeypatch.setattr(llm_client, "generate", lambda prompt, system_prompt="", fallback="": bad)
    state = run("scenario_16_hindi")
    assert state.translated_body == ""
    assert "non-English email could not be translated" in state.review_reasons


def test_llm_opening_guardrail(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PERSONALISED_OPENING", True)
    monkeypatch.setattr(llm_client, "generate", lambda prompt, system_prompt="", fallback="":
                        "Your account balance will be updated shortly.")
    state = run("scenario_1_balance")
    assert "updated shortly" not in state.masked_response
    monkeypatch.setattr(llm_client, "generate", lambda prompt, system_prompt="", fallback="":
                        "Thank you for contacting us about your account balance.")
    state = run("scenario_1_balance")
    assert "Thank you for contacting us about your account balance." in state.masked_response


def test_email_ids_are_unique():
    ids = {EmailInput(sender="a@b.com", subject="s", body="b").email_id for _ in range(500)}
    assert len(ids) == 500


def test_settings_persist_across_restart():
    from apis.operations import apply_saved_config

    client = TestClient(__import__("apis.banking_api_server", fromlist=["app"]).app)
    client.post("/api/v1/ops/config", json={"HITL_ENABLED": True, "BANKING_API_TRANSPORT": "http"})
    settings.HITL_ENABLED, settings.BANKING_API_TRANSPORT = False, "inprocess"
    apply_saved_config()
    assert settings.HITL_ENABLED is True and settings.BANKING_API_TRANSPORT == "http"


def test_audit_export_streams_jsonl():
    from apis.banking_api_server import app

    run("scenario_1_balance")
    res = TestClient(app).get("/api/v1/ops/export")
    assert res.status_code == 200
    assert '"email_id": "EML-' in res.text or '"email_id":"EML-' in res.text


def test_dashboard_login(monkeypatch):
    from apis.banking_api_server import app

    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "s3cret")
    client = TestClient(app)
    assert client.get("/dashboard").status_code == 401
    assert client.get("/api/v1/ops/metrics").status_code == 401
    assert client.get("/dashboard", auth=("admin", "wrong")).status_code == 401
    assert client.get("/dashboard", auth=("admin", "s3cret")).status_code == 200
    assert client.post("/api/v1/validate-account", json={"account_number": "1234567890"}).status_code == 200

    monkeypatch.setattr(settings, "HITL_ENABLED", True)
    run_res = client.post("/api/v1/ops/scenarios/scenario_6_urgent_escalation/run", auth=("admin", "s3cret")).json()
    res = client.post(f"/api/v1/ops/reviews/{run_res['email_id']}/approve", json={}, auth=("admin", "s3cret")).json()
    assert res["decided_by"] == "admin"


def test_worker_processes_batch_concurrently(monkeypatch):
    worker = EmailWorker(user="bank@example.com", pwd="x")
    batch = [(str(i), fresh_copy("scenario_1_balance")) for i in range(6)]
    sent = []
    monkeypatch.setattr(worker, "fetch_unseen", lambda batch_size=None: batch)
    monkeypatch.setattr(worker, "send_reply", lambda to, subj, body: sent.append(to))
    monkeypatch.setattr(worker, "mark_seen", lambda mid: None)
    assert worker.process_pending() == 6
    assert len(sent) == 6 and worker.status["replied"] == 6
    assert len(store.list_audit()) == 6
