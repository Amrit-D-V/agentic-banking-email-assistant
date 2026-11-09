import pytest
from models.schemas import EmailInput, IntentType
from utils.policy_rag import policy_rag
from workflows.orchestrator import orchestrator


def test_policy_rag_ingestion():
    count = policy_rag.ingest()
    assert count >= 4
    assert policy_rag.index is not None


def test_policy_rag_query():
    matches = policy_rag.search("What is the minimum balance required in metro branches?", top_k=1)
    assert len(matches) > 0
    assert "Minimum Average Balance" in matches[0]["topic"]
    assert "10,000" in matches[0]["text"]


def test_end_to_end_policy_inquiry_email():
    email = EmailInput(
        sender="customer.policy@example.com",
        subject="Query regarding minimum balance charges",
        body="What are the minimum balance requirements and penalty charges for savings accounts in metro branches?",
    )
    state = orchestrator.process_email(email)

    assert IntentType.POLICY_INQUIRY in state.detected_intents or "PolicyRAGLookup" in state.selected_apis
    assert len(state.retrieved_policies) > 0
    assert "10,000" in state.masked_response
    assert "Policy Information" in state.masked_response
