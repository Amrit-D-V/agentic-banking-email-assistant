import re
from typing import List, Tuple

from agents.intent_registry import IntentHandler, handlers_for, targets
from config.settings import settings
from models.llm_client import llm_client
from models.schemas import (
    AgentState,
    EntityValidationDetail,
    EntityValidationStatus,
    IntentType,
    SentimentType,
)
from prompts.templates import OPENING_SYSTEM_PROMPT, OPENING_USER_PROMPT
from utils.pii_masker import mask_text_pii

V = EntityValidationStatus
ENTITY_LABELS = {"account_number": "account number", "credit_card_number": "credit card number"}
LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "gu": "Gujarati",
                  "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi"}
INTENT_PHRASES = {
    IntentType.BALANCE_ENQUIRY: "account balance", IntentType.CARD_TRANSACTIONS: "credit card transactions",
    IntentType.STATEMENT_REQUEST: "account statement", IntentType.POLICY_INQUIRY: "banking policy question",
    IntentType.GENERAL_INQUIRY: "general request",
}
UNREGISTERED_MESSAGE = ("For your security, we can only share account and card details with customers writing from "
                        "the email address registered with the bank. Please write to us from your registered email "
                        "address, or contact us through net banking or your branch.")
_UNSAFE_OPENING = re.compile(
    r"\d|inr|rs\.?\s|₹|%|http|www\.|balance (is|of)|@"
    r"|\b(will|shall|available|processing|processed|updated|aware|investigat\w*|resolv\w*|commit\w*|ensure|guarantee\w*|soon|shortly)\b",
    re.I)


class ResponseGenerationAgent:

    def process(self, state: AgentState) -> AgentState:
        handlers = handlers_for(state)
        all_targets = [(h, t) for h in handlers for t in targets(h, state.validation_summary.validations)]
        unregistered = bool(all_targets) and all(t.additional_info.get("reason") == "UNREGISTERED_SENDER" for _, t in all_targets)

        sections: List[str] = []
        outcomes: List[bool] = []
        if unregistered:
            outcomes = [False]
            sections += [UNREGISTERED_MESSAGE, ""]
        else:
            for h in handlers:
                section_outcomes, body = self._section(h, state)
                outcomes += section_outcomes
                sections += [f"{h.title}:", *body, ""]

        if state.retrieved_policies:
            sections.append("Policy Information:")
            for text in state.retrieved_policies:
                head, _, body = text.partition("\n")
                sections.append(head.split("| Topic:")[-1].strip())
                sections += [f"• {line.strip().lstrip('-• ').strip()}" for line in body.split("\n") if line.strip()]
            sections.append("")
        elif IntentType.POLICY_INQUIRY in state.detected_intents:
            sections += ["Policy Information:", "• A customer service officer will answer your policy question "
                         "within one business day.", ""]

        unsupported = not handlers and not state.retrieved_policies
        if unsupported:
            sections += [
                "This mailbox handles account balance enquiries, credit card transaction enquiries, account "
                "statements and banking policy questions. Your request has been forwarded to a customer service "
                "officer, who will respond within one business day.", ""]

        self._flag_for_review(state, unsupported)

        if not outcomes:
            opening = "Thank you for writing to us."
        elif all(outcomes):
            opening = "We have processed your request successfully."
        elif any(outcomes):
            opening = "We have partially processed your request. Please find the details below:"
        else:
            opening = "We were unable to complete your request for the reasons below:"
        state.has_partial_failure = any(outcomes) and not all(outcomes)

        lines = [f"Dear {self._greeting_name(state)},", ""]
        personal = self._personalised_opening(state)
        if personal:
            lines += [personal, ""]
        if state.sentiment == SentimentType.NEGATIVE_URGENT:
            lines += ["We understand the urgency of your request and sincerely apologise for any inconvenience. "
                      "Your email has been prioritised"
                      + (" and escalated to a senior customer service officer." if state.requires_human_review else "."), ""]
        if state.detected_language in LANGUAGE_NAMES:
            lines += [f"We received your email in {LANGUAGE_NAMES[state.detected_language]} and have replied in English.", ""]
        lines += [opening, "", *sections, "Thank you,", "Customer Support Team", "HDFC Bank"]

        draft = "\n".join(lines)
        state.generated_response = draft
        state.masked_response = mask_text_pii(draft) if settings.MASK_PII_IN_RESPONSES else draft
        state.final_email_subject = f"Re: {state.email.subject} [Ref: {state.email.email_id}]"
        state.execution_trace.append(
            f"ResponseGenerationAgent: items={len(outcomes)}, ok={sum(outcomes)}, llm_opening={bool(personal)}, "
            f"review={state.requires_human_review}"
        )
        return state

    def _section(self, h: IntentHandler, state: AgentState) -> Tuple[List[bool], List[str]]:
        chosen = targets(h, state.validation_summary.validations)
        if not chosen:
            return [False], [h.missing_message]
        outcomes, body = [], []
        for t in chosen:
            ok, lines = self._target(h, t, state)
            outcomes.append(ok)
            if body:
                body.append("")
            body += lines
        return outcomes, body

    def _target(self, h: IntentHandler, t: EntityValidationDetail, state: AgentState) -> Tuple[bool, List[str]]:
        label = ENTITY_LABELS.get(t.entity_type, "account")
        if t.status == V.VALID:
            f = next((f for f in state.fulfilments if f["api"] == h.api_name and f["value"] == t.raw_value), None)
            if f and "error" not in f["data"]:
                return True, h.render(f["data"], state)
            return False, [f"We are unable to retrieve your {h.noun} at the moment due to a temporary system issue. "
                           "Our team has been notified and will send you the details shortly; no action is needed from you."]
        if t.status == V.MISSING:
            return False, [h.missing_message]
        if t.status == V.UNAVAILABLE:
            return False, [f"We could not verify the {label} {t.masked_value} due to a temporary system issue. "
                           "Our team will follow up with you shortly."]
        reason = t.additional_info.get("reason")
        if reason == "UNREGISTERED_SENDER":
            return False, [UNREGISTERED_MESSAGE]
        if reason == "OWNERSHIP_MISMATCH":
            return False, [f"The {label} {t.masked_value} is not linked to the email address you wrote from. "
                           "For your security, please write to us from your registered email address."]
        noun = "card" if t.entity_type == "credit_card_number" else "account"
        return False, [f"The {label} provided ({t.masked_value}) could not be validated. "
                       f"Kindly recheck the {noun} details and resend your request."]

    @staticmethod
    def _personalised_opening(state: AgentState) -> str:
        if not settings.LLM_PERSONALISED_OPENING:
            return ""
        topics = ", ".join(INTENT_PHRASES[i] for i in state.detected_intents if i in INTENT_PHRASES)
        prompt = OPENING_USER_PROMPT.format(topics=topics, sentiment=state.sentiment.value,
                                            email=(state.translated_body or state.cleaned_body)[:600])
        text = " ".join(llm_client.generate(prompt, OPENING_SYSTEM_PROMPT).split()).strip().strip('"')
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
        if not text or len(text) > 240 or len(sentences) > 2 or _UNSAFE_OPENING.search(text) \
                or text.lower().startswith(("dear", "hi", "hello", "subject")):
            if text:
                state.execution_trace.append("ResponseGenerationAgent: LLM opening rejected by guardrail")
            return ""
        return text

    @staticmethod
    def _greeting_name(state: AgentState) -> str:
        return state.customer_profile.get("customer_name") or state.entities.customer_name or "Customer"

    @staticmethod
    def _flag_for_review(state: AgentState, unsupported: bool) -> None:
        reasons = []
        if state.sentiment == SentimentType.NEGATIVE_URGENT:
            reasons.append("negative/urgent sentiment")
        low = [i for i, c in state.intent_confidences.items() if c < settings.HITL_CONFIDENCE_THRESHOLD]
        if low:
            reasons.append(f"low intent confidence: {', '.join(low)}")
        if any(log.status in ("FAILED", "TIMEOUT") for log in state.api_call_logs):
            reasons.append("core banking API failure")
        if unsupported:
            reasons.append("unsupported request")
        if state.detected_language != "en" and not state.translated_body:
            reasons.append("non-English email could not be translated")
        state.review_reasons = reasons
        state.requires_human_review = bool(reasons)


response_generation_agent = ResponseGenerationAgent()
