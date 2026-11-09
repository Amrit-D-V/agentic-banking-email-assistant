import pytest

from config.settings import settings


def pytest_addoption(parser):
    parser.addoption("--llm", action="store_true", help="also run tests against the live Ollama LLaMA model")


def pytest_configure(config):
    config.addinivalue_line("markers", "llm: needs a running Ollama with the configured LLaMA model")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--llm"):
        return
    skip = pytest.mark.skip(reason="live LLM test: run with --llm")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def test_settings(tmp_path, monkeypatch, request):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama" if "llm" in request.keywords else "mock")
    monkeypatch.setattr(settings, "BANKING_API_TRANSPORT", "inprocess")
    monkeypatch.setattr(settings, "API_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(settings, "API_MAX_RETRIES", 1)
    monkeypatch.setattr(settings, "API_RETRY_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(settings, "MOCK_SLOW_RESPONSE_SECONDS", 1.0)
    monkeypatch.setattr(settings, "MOCK_FAILURE_RATE", 0.0)
    monkeypatch.setattr(settings, "HITL_ENABLED", False)
    monkeypatch.setattr(settings, "ENFORCE_SENDER_OWNERSHIP", True)
    monkeypatch.setattr(settings, "DEMO_CUSTOMER_EMAIL", "john.doe@example.com")
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(settings, "REQUIRE_REGISTERED_SENDER", True)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "")
    from apis.api_client import banking_api_client

    banking_api_client.reset()
    yield
