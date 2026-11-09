import json
from apis.mcp_banking_server import (
    validate_account,
    validate_card,
    get_account_balance,
    get_card_transactions,
    get_account_statement,
)


def test_mcp_validate_account_tool():
    res_str = validate_account("1234567890")
    data = json.loads(res_str)
    assert data["status"] == "VALID"
    assert data["customer_name"] == "John Doe"


def test_mcp_validate_card_tool():
    res_str = validate_card("4567XXXX8901")
    data = json.loads(res_str)
    assert data["status"] == "VALID"

    res_invalid = validate_card("999999999")
    data_invalid = json.loads(res_invalid)
    assert data_invalid["status"] == "INVALID"


def test_mcp_get_account_balance_tool():
    res_str = get_account_balance("1234567890")
    data = json.loads(res_str)
    assert data["available_balance"] == 125000.0


def test_mcp_get_card_transactions_tool():
    res_str = get_card_transactions("4567XXXX8901", limit=3)
    data = json.loads(res_str)
    assert len(data["transactions"]) == 3


def test_mcp_get_account_statement_tool():
    res_str = get_account_statement("1234567890", "April 2026")
    data = json.loads(res_str)
    assert data["period"] == "April 2026"
    assert "download_url" in data
