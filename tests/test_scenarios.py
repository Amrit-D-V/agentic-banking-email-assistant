import pytest

from models.schemas import EmailInput, EntityValidationStatus, IntentType, SentimentType
from sample_data.sample_emails import fresh_copy
from workflows.orchestrator import orchestrator


def run(key):
    return orchestrator.process_email(fresh_copy(key))


def validation(state, entity):
    return next(v for v in state.validation_summary.validations if v.entity_type == entity)


def test_scenario_1_account_balance():
    state = run("scenario_1_balance")
    assert state.detected_intents == [IntentType.BALANCE_ENQUIRY]
    assert state.entities.account_number == "1234567890"
    assert state.validation_summary.overall_valid is True
    assert state.selected_apis == ["GetAccountBalanceAPI"]
    assert state.api_results["GetAccountBalanceAPI"]["available_balance"] == 125000.0
    assert "Account Number: XXXX7890" in state.masked_response
    assert "INR 1,25,000.00" in state.masked_response
    assert "1234567890" not in state.masked_response


def test_scenario_2_credit_card_usage():
    state = run("scenario_2_card_transactions")
    assert state.detected_intents == [IntentType.CARD_TRANSACTIONS]
    assert state.entities.credit_card_number == "4567XXXX8901"
    assert state.entities.account_number is None
    assert state.entities.transaction_count == 5
    assert len(state.api_results["GetCardTransactionsAPI"]["transactions"]) == 5
    assert "Amazon India" in state.masked_response


def test_scenario_3_statement_request_without_account_number():
    state = run("scenario_3_statement")
    assert state.email.body == "Kindly send my bank statement for April 2026."
    assert state.detected_intents == [IntentType.STATEMENT_REQUEST]
    assert state.entities.statement_period == "April 2026"
    assert (state.entities.date_from, state.entities.date_to) == ("2026-04-01", "2026-04-30")
    assert validation(state, "registered_account").status == EntityValidationStatus.VALID
    assert "GetStatementAPI" in state.selected_apis
    assert "Statement Period: April 2026" in state.masked_response
    assert "Secure Download Link" in state.masked_response


def test_scenario_4_multi_intent():
    state = run("scenario_4_multi_intent")
    assert set(state.detected_intents) == {IntentType.BALANCE_ENQUIRY, IntentType.CARD_TRANSACTIONS}
    assert state.entities.account_number == "1234567890"
    assert state.entities.credit_card_number == "987654321"
    assert state.entities.transaction_count == 3
    assert set(state.selected_apis) == {"GetAccountBalanceAPI", "GetCardTransactionsAPI"}
    fetch = next(s for s in state.api_plan if s["stage"].endswith("data fetch"))
    assert fetch["mode"] == "parallel"
    assert "Account Balance:" in state.masked_response and "Credit Card Request:" in state.masked_response
    assert state.masked_response.count("Dear ") == 1


def test_scenario_5_partial_validation_failure():
    state = run("scenario_5_partial_failure")
    assert validation(state, "account_number").status == EntityValidationStatus.VALID
    assert validation(state, "credit_card_number").status == EntityValidationStatus.INVALID
    assert state.has_partial_failure is True
    assert "GetAccountBalanceAPI" in state.selected_apis
    assert "GetCardTransactionsAPI" not in state.selected_apis
    resp = state.masked_response
    assert "partially processed" in resp
    assert "INR 1,25,000.00" in resp
    assert "could not be validated" in resp and "recheck the card details" in resp


def test_scenario_5_order_independent():
    state = orchestrator.process_email(EmailInput(
        sender="john.doe@example.com", subject="Request",
        body="Show the last 2 transactions for card 999999999 and the balance of account 1234567890. Call me on 9876501234."))
    assert state.entities.account_number == "1234567890"
    assert state.entities.credit_card_number == "999999999"
    assert state.entities.transaction_count == 2
    assert state.has_partial_failure is True


def test_urgent_sentiment_is_flagged_for_review():
    state = run("scenario_6_urgent_escalation")
    assert state.sentiment == SentimentType.NEGATIVE_URGENT
    assert state.urgency_flag is True
    assert state.requires_human_review is True
    assert "urgency" in state.masked_response.lower()


def test_missing_account_number_requests_clarification():
    state = run("scenario_7_missing_details")
    assert IntentType.BALANCE_ENQUIRY in state.detected_intents
    assert validation(state, "account_number").status == EntityValidationStatus.MISSING
    assert "GetAccountBalanceAPI" not in state.selected_apis
    assert "account number was not provided" in state.masked_response.lower()


def test_minimum_balance_question_is_policy_not_balance():
    state = run("scenario_8_policy_query")
    assert state.detected_intents == [IntentType.POLICY_INQUIRY]
    assert "PolicyRAGLookup" in state.selected_apis
    assert "10,000" in state.masked_response
    assert "unable to complete" not in state.masked_response


def test_unsupported_request_is_routed_to_officer():
    state = run("scenario_9_unsupported")
    assert state.detected_intents == [IntentType.GENERAL_INQUIRY]
    assert state.api_call_logs == []
    assert "forwarded to a customer service officer" in state.masked_response
    assert "unsupported request" in state.review_reasons
    assert state.masked_response.startswith("Dear Customer,")


def test_api_timeout_is_retried_and_reported():
    state = run("scenario_10_api_timeout")
    log = next(c for c in state.api_call_logs if c.api_name == "GetAccountBalanceAPI")
    assert log.status == "TIMEOUT"
    assert log.attempts == 2
    assert "temporary system issue" in state.masked_response
    assert "core banking API failure" in state.review_reasons


def test_api_outage_on_one_intent_is_a_partial_success():
    state = run("scenario_11_api_outage")
    assert state.api_results["GetAccountBalanceAPI"]["error_type"] == "UNAVAILABLE"
    assert "transactions" in state.api_results["GetCardTransactionsAPI"]
    assert state.has_partial_failure is True
    assert "temporary system issue" in state.masked_response
    assert "Amazon India" in state.masked_response


def test_account_of_another_customer_is_refused():
    state = run("scenario_12_ownership_mismatch")
    v = validation(state, "account_number")
    assert v.status == EntityValidationStatus.INVALID
    assert v.additional_info["reason"] == "OWNERSHIP_MISMATCH"
    assert "GetAccountBalanceAPI" not in state.selected_apis
    assert "125,000" not in state.masked_response and "1,25,000" not in state.masked_response


def test_unknown_sender_is_not_greeted_by_account_holder_name():
    state = orchestrator.process_email(EmailInput(
        sender="someone@else.com", subject="Balance", body="Balance for account 1234567890 please."))
    assert state.masked_response.startswith("Dear Customer,")
    assert "John Doe" not in state.masked_response


def test_statement_without_period_defaults_to_last_month():
    state = orchestrator.process_email(EmailInput(
        sender="john.doe@example.com", subject="Statement", body="Please email my account statement."))
    assert "GetStatementAPI" in state.selected_apis
    assert "As no period was mentioned" in state.masked_response


def test_text_attachment():
    state = orchestrator.process_email(EmailInput(
        sender="john.doe@example.com", subject="Inquiry with attached form",
        body="Please check my attached request form and provide my balance.",
        attachment_paths=["sample_data/attachment_sample.txt"]))
    assert state.entities.account_number == "1234567890"
    assert "GetAccountBalanceAPI" in state.selected_apis


@pytest.mark.parametrize("key", ["scenario_1_balance", "scenario_4_multi_intent", "scenario_5_partial_failure"])
def test_audit_record_written_and_masked(key):
    import json
    from utils import store

    state = run(key)
    rec = store.find_audit(state.email.email_id)
    assert rec["email_id"] == state.email.email_id
    assert rec["api_calls"] and all("1234567890" not in json.dumps(c) for c in rec["api_calls"])
    assert "1234567890" not in json.dumps(rec)


@pytest.mark.llm
@pytest.mark.parametrize("key", [
    "scenario_1_balance", "scenario_2_card_transactions", "scenario_3_statement",
    "scenario_4_multi_intent", "scenario_5_partial_failure", "scenario_8_policy_query", "scenario_9_unsupported",
])
def test_live_llm_scenarios_match_rule_engine(key):
    from config.settings import settings

    live = run(key)
    settings.LLM_PROVIDER = "mock"
    base = run(key)
    assert set(live.detected_intents) == set(base.detected_intents)
    assert live.selected_apis == base.selected_apis
    assert live.has_partial_failure == base.has_partial_failure
    assert live.masked_response.splitlines()[0] == base.masked_response.splitlines()[0]
