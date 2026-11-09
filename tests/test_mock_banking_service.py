import pytest
from apis.mock_banking_service import mock_banking_service


def test_validate_account_valid():
    res = mock_banking_service.validate_account("1234567890")
    assert res.status == "VALID"
    assert res.customer_name == "John Doe"
    assert res.account_type == "Savings"


def test_validate_account_invalid():
    res = mock_banking_service.validate_account("0000000000")
    assert res.status == "INVALID"
    assert res.customer_name is None


def test_validate_card_valid():
    res = mock_banking_service.validate_card("4567XXXX8901")
    assert res.status == "VALID"
    assert res.customer_name == "John Doe"


def test_validate_card_invalid():
    res = mock_banking_service.validate_card("999999999")
    assert res.status == "INVALID"


def test_get_account_balance():
    res = mock_banking_service.get_account_balance("1234567890")
    assert res.account_number == "1234567890"
    assert res.available_balance == 125000.0
    assert res.currency == "INR"


def test_get_card_transactions():
    res = mock_banking_service.get_card_transactions("4567XXXX8901", limit=5)
    assert res.card_number == "4567XXXX8901"
    assert len(res.transactions) == 5
    assert res.transactions[0].merchant == "Amazon India"


def test_get_statement():
    res = mock_banking_service.get_statement("1234567890", "April 2026")
    assert res.account_number == "1234567890"
    assert res.period == "April 2026"
    assert "STMT" in res.statement_id
    assert res.download_url.endswith(".pdf")


def test_card_matching_is_strict():
    assert mock_banking_service.validate_card("4567123456788901").status == "VALID"
    assert mock_banking_service.validate_card("1111222233338901").status == "INVALID"
    assert mock_banking_service.validate_card("8901").status == "INVALID"


def test_lookup_customer_by_email():
    found = mock_banking_service.lookup_customer_by_email("John.Doe@example.com")
    assert found.status == "FOUND" and found.primary_account == "1234567890"
    assert mock_banking_service.lookup_customer_by_email("stranger@example.com").status == "NOT_FOUND"
