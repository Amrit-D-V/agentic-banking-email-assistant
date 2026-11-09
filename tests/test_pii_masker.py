from utils.pii_masker import (
    mask_account_number,
    mask_card_number,
    mask_email,
    mask_text_pii,
)


def test_mask_account_number():
    assert mask_account_number("1234567890") == "XXXX7890"
    assert mask_account_number("9876543210") == "XXXX3210"
    assert mask_account_number("123") == "XXXX123"
    assert mask_account_number(None) == "N/A"


def test_mask_card_number():
    assert mask_card_number("4567123456788901") == "4567-XXXX-XXXX-8901"
    assert mask_card_number("4567XXXX8901") == "XXXX-XXXX-XXXX-8901"
    assert mask_card_number("987654321") == "XXXX-XXXX-XXXX-4321"
    assert mask_card_number(None) == "N/A"


def test_mask_email():
    assert mask_email("john.doe@example.com") == "j***e@example.com"
    assert mask_email("amrit@bank.com") == "a***t@bank.com"


def test_mask_text_pii():
    text = "User account 1234567890 with card 4567123456788901 requested balance."
    masked = mask_text_pii(text)
    assert "1234567890" not in masked
    assert "XXXX7890" in masked
    assert "4567123456788901" not in masked


def test_mask_payload():
    from utils.pii_masker import mask_payload

    masked = mask_payload({"account_number": "1234567890", "card_number": "4567123456788901", "limit": 5})
    assert masked == {"account_number": "XXXX7890", "card_number": "4567-XXXX-XXXX-8901", "limit": 5}
