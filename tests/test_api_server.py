import pytest
from fastapi.testclient import TestClient

from apis.banking_api_server import app
from config.settings import settings

client = TestClient(app)


def test_pages_render():
    assert client.get("/dashboard").status_code == 200
    assert client.get("/ui").status_code == 404


def test_process_email_endpoint():
    res = client.post("/api/v1/process-email", json={
        "sender": "john.doe@example.com", "subject": "Balance Inquiry",
        "body": "Please provide my savings account balance for account number 1234567890."})
    assert res.status_code == 200
    data = res.json()
    assert "BALANCE_ENQUIRY" in data["detected_intents"]
    assert "INR 1,25,000.00" in data["masked_response"]


def test_attachment_paths_outside_allowed_dirs_are_rejected():
    res = client.post("/api/v1/process-email", json={
        "sender": "a@b.com", "subject": "x", "body": "balance", "attachment_paths": ["/etc/passwd"]})
    assert res.status_code == 400


def test_upload_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr("apis.banking_api_server.UPLOAD_DIR", tmp_path)
    with open("sample_data/attachment_sample.txt", "rb") as f:
        res = client.post("/api/v1/process-email-upload",
                          data={"sender": "john.doe@example.com", "subject": "Form", "body": "Please process attached"},
                          files=[("files", ("form.txt", f, "text/plain"))])
    assert res.status_code == 200
    assert "GetAccountBalanceAPI" in res.json()["selected_apis"]


def test_core_banking_errors_map_to_http_status():
    assert client.post("/api/v1/account-balance", json={"account_number": "0000000000"}).status_code == 404
    assert client.post("/api/v1/account-balance", json={"account_number": "2222222222"}).status_code == 503
    assert client.post("/api/v1/customer-lookup", json={"email": "john.doe@example.com"}).json()["primary_account"] == "1234567890"


def test_ops_config_switch_and_validation():
    res = client.post("/api/v1/ops/config", json={"HITL_ENABLED": True, "MOCK_FAILURE_RATE": 0.2})
    assert res.json()["HITL_ENABLED"] is True and res.json()["MOCK_FAILURE_RATE"] == 0.2
    assert client.post("/api/v1/ops/config", json={"BANKING_API_TRANSPORT": "carrier-pigeon"}).status_code == 422
    assert client.post("/api/v1/ops/config", json={"MOCK_FAILURE_RATE": 3}).status_code == 422


def test_run_scenario_metrics_and_drilldown():
    run = client.post("/api/v1/ops/scenarios/scenario_5_partial_failure/run").json()
    assert run["partial"] is True
    m = client.get("/api/v1/ops/metrics").json()
    assert m["total_processed"] == 1
    assert m["outcomes"]["PARTIAL"] == 1
    assert m["pii"]["leaks"] == 0
    assert any(a["api"] == "ValidateCardAPI" for a in m["api_performance"])
    rec = client.get(f"/api/v1/ops/records/{run['email_id']}").json()
    assert rec["validations"][1]["status"] == "INVALID"
    assert client.get("/api/v1/ops/records/nope").status_code == 404


def test_human_in_the_loop_approval_flow():
    client.post("/api/v1/ops/config", json={"HITL_ENABLED": True})
    run = client.post("/api/v1/ops/scenarios/scenario_6_urgent_escalation/run").json()
    pending = client.get("/api/v1/ops/reviews", params={"status": "PENDING_APPROVAL"}).json()
    assert [p["email_id"] for p in pending] == [run["email_id"]]
    assert "reply_to" not in pending[0]
    res = client.post(f"/api/v1/ops/reviews/{run['email_id']}/approve", json={}).json()
    assert res["status"] == "APPROVED"
    assert client.post(f"/api/v1/ops/reviews/{run['email_id']}/approve", json={}).status_code == 409


def test_health_reports_components():
    comps = client.get("/api/v1/ops/health").json()["components"]
    assert comps["Core Banking (CBS/CMS)"]["status"] == "ONLINE"
    assert "LLaMA (Ollama)" in comps and "OCR (Tesseract)" in comps


def test_worker_start_without_credentials(monkeypatch):
    from email_worker import email_worker

    monkeypatch.setattr(email_worker, "user", "")
    assert client.post("/api/v1/ops/worker/start").status_code == 400


def test_reset_clears_audit():
    client.post("/api/v1/ops/scenarios/scenario_1_balance/run")
    client.post("/api/v1/ops/reset")
    assert client.get("/api/v1/ops/metrics").json()["total_processed"] == 0
