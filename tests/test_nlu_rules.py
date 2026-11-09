from datetime import date

import pytest

from utils.nlu_rules import (
    extract_customer_name,
    extract_statement_period,
    extract_transaction_count,
    find_identifiers,
    is_plausible_name,
    rule_analysis,
    rule_sentiment,
)


@pytest.mark.parametrize("text,account,card", [
    ("balance for account number 1234567890", "1234567890", None),
    ("last 5 transactions for card 4567XXXX8901", None, "4567XXXX8901"),
    ("card 999999999 and account 1234567890", "1234567890", "999999999"),
    ("my credit card 4567 1234 5678 8901", None, "4567123456788901"),
    ("a/c no. 5555666677", "5555666677", None),
    ("please call me on mobile 9876501234", None, None),
])
def test_find_identifiers_uses_context(text, account, card):
    ids = find_identifiers(text)
    assert (ids["account"][0] if ids["account"] else None) == account
    assert (ids["card"][0] if ids["card"] else None) == card


@pytest.mark.parametrize("text,n", [
    ("last 3 transactions", 3), ("latest five transactions on my card", 5),
    ("previous 10 card transactions", 10), ("show my transactions", None),
])
def test_transaction_count(text, n):
    assert extract_transaction_count(text) == n


@pytest.mark.parametrize("text,label,start,end", [
    ("statement for April 2026", "April 2026", "2026-04-01", "2026-04-30"),
    ("statement for 02/2024", "February 2024", "2024-02-01", "2024-02-29"),
    ("from 01/03/2026 to 15/03/2026", "01 Mar 2026 to 15 Mar 2026", "2026-03-01", "2026-03-15"),
    ("January to March 2026", "January to March 2026", "2026-01-01", "2026-03-31"),
    ("Q2 2026", "Q2 2026", "2026-04-01", "2026-06-30"),
    ("FY 2025-26", "FY 2025-26", "2025-04-01", "2026-03-31"),
    ("last month", "October 2026", "2026-10-01", "2026-10-31"),
])
def test_statement_period(text, label, start, end):
    p = extract_statement_period(text, today=date(2026, 11, 8))
    assert (p["label"], p["date_from"], p["date_to"]) == (label, start, end)


def test_statement_period_absent():
    assert extract_statement_period("please send my statement") is None


@pytest.mark.parametrize("text,intents", [
    ("Please provide my savings account balance for account number 1234567890.", ["BALANCE_ENQUIRY"]),
    ("Please share my last 5 credit card transactions for card 4567XXXX8901.", ["CARD_TRANSACTIONS"]),
    ("Kindly send my bank statement for April 2026.", ["STATEMENT_REQUEST"]),
    ("What is the minimum balance required and what are the penalty charges?", ["POLICY_INQUIRY"]),
    ("Reason: Balance check", ["BALANCE_ENQUIRY"]),
    ("I want to apply for a home loan", []),
])
def test_rule_intents(text, intents):
    assert rule_analysis(text)[0] == intents


def test_minimum_balance_vetoes_balance_intent():
    _, vetoed = rule_analysis("What is the minimum balance for savings accounts and the charges if balance falls below it?")
    assert "BALANCE_ENQUIRY" in vetoed


def test_sentiment_lexicon():
    assert rule_sentiment("This is unacceptable, fix it immediately!")[0] == "NEGATIVE_URGENT"
    assert rule_sentiment("Thank you for the great service")[0] == "POSITIVE"
    assert rule_sentiment("Please share my balance")[0] == "NEUTRAL"


def test_customer_name_and_plausibility():
    assert extract_customer_name("Please help.\n\nRegards,\nAnita Rao") == "Anita Rao"
    assert is_plausible_name("Anita Rao")
    assert not is_plausible_name("I would like to apply for a home loan.")
    assert not is_plausible_name("Hi")
