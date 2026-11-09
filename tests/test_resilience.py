import pytest
from fastapi.testclient import TestClient

from apis import api_client as api_client_module
from apis.api_client import BankingApiClient
from apis.mock_banking_service import SIMULATED_OUTAGE_ACCOUNT, SIMULATED_TIMEOUT_ACCOUNT
from config.settings import settings
from sample_data.sample_emails import fresh_copy
from workflows.orchestrator import orchestrator


def test_timeout_is_retried_then_reported():
    data, log = BankingApiClient(transport="inprocess").get_account_balance(SIMULATED_TIMEOUT_ACCOUNT)
    assert data["error_type"] == "TIMEOUT"
    assert log.status == "TIMEOUT" and log.attempts == 1 + settings.API_MAX_RETRIES


def test_outage_is_transient_and_retried():
    data, log = BankingApiClient(transport="inprocess").get_account_balance(SIMULATED_OUTAGE_ACCOUNT)
    assert data["error_type"] == "UNAVAILABLE"
    assert log.status == "FAILED" and log.attempts == 2


def test_not_found_is_not_retried():
    data, log = BankingApiClient(transport="inprocess").get_account_balance("0000000000")
    assert data["error_type"] == "NOT_FOUND"
    assert log.attempts == 1


def test_chaos_failure_rate(monkeypatch):
    monkeypatch.setattr(settings, "MOCK_FAILURE_RATE", 1.0)
    monkeypatch.setattr(settings, "API_MAX_RETRIES", 0)
    data, _ = BankingApiClient(transport="inprocess").get_card_transactions("4567XXXX8901")
    assert data["error_type"] == "UNAVAILABLE"


@pytest.fixture
def http_transport(monkeypatch):
    from apis.banking_api_server import app

    client = TestClient(app)

    def fake_post(url, json=None, timeout=None):
        return client.post(url.replace(f"http://{settings.BANKING_API_HOST}:{settings.BANKING_API_PORT}", ""), json=json)

    monkeypatch.setattr(api_client_module.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "BANKING_API_TRANSPORT", "http")


def test_rest_transport_end_to_end(http_transport):
    state = orchestrator.process_email(fresh_copy("scenario_5_partial_failure"))
    assert {log.transport for log in state.api_call_logs} == {"http"}
    assert state.has_partial_failure and "1,25,000" in state.masked_response


def test_rest_transport_maps_503_to_retryable_failure(http_transport):
    data, log = BankingApiClient().get_account_balance(SIMULATED_OUTAGE_ACCOUNT)
    assert data["error_type"] == "UNAVAILABLE" and log.attempts == 2


def test_mcp_transport_end_to_end(monkeypatch):
    from apis.mcp_client import MCPBankingClient

    client = MCPBankingClient()
    monkeypatch.setattr("apis.mcp_client.mcp_banking_client", client)
    monkeypatch.setattr(settings, "BANKING_API_TRANSPORT", "mcp")
    monkeypatch.setattr(settings, "API_TIMEOUT_SECONDS", 10)
    try:
        state = orchestrator.process_email(fresh_copy("scenario_4_multi_intent"))
        assert {log.transport for log in state.api_call_logs} == {"mcp"}
        assert set(state.selected_apis) == {"GetAccountBalanceAPI", "GetCardTransactionsAPI"}
        assert "get_account_statement" in client.tools
        data, _ = BankingApiClient().get_account_balance(SIMULATED_OUTAGE_ACCOUNT)
        assert data["error_type"] == "UNAVAILABLE"
    finally:
        client.close()
