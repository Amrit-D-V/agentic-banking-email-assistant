import json
import logging
from datetime import datetime

from apis.api_client import banking_api_client
from config.settings import settings
from models.llm_client import llm_client
from models.schemas import AgentState, AuditRecord
from utils import review_queue, store
from utils.pii_masker import mask_account_number, mask_card_number, mask_email, mask_payload, mask_text_pii

log = logging.getLogger("AuditAgent")


class AuditLoggingAgent:

    def process(self, state: AgentState) -> AgentState:
        now = datetime.now()
        ms = round((now - state.start_time).total_seconds() * 1000, 2)
        state.total_execution_ms = ms
        state.execution_trace.append(f"AuditLoggingAgent: {ms}ms")

        if state.has_partial_failure:
            status_str = "PARTIAL"
        elif state.validation_summary.overall_valid:
            status_str = "VALID"
        elif not state.validation_summary.validations:
            status_str = "NOT_APPLICABLE"
        else:
            status_str = "INVALID"

        e = state.entities
        record = AuditRecord(
            timestamp=now.isoformat(),
            email_id=state.email.email_id,
            sender_masked=mask_email(state.email.sender),
            subject=mask_text_pii(state.email.subject),
            detected_intents=[i.value for i in state.detected_intents],
            intent_confidences=state.intent_confidences,
            sentiment=state.sentiment.value,
            sentiment_reason=state.sentiment_reason,
            urgency_flag=state.urgency_flag,
            entities_masked={
                "account_number": mask_account_number(e.account_number) if e.account_number else None,
                "credit_card_number": mask_card_number(e.credit_card_number) if e.credit_card_number else None,
                "account_numbers": [mask_account_number(a) for a in e.account_numbers],
                "card_numbers": [mask_card_number(c) for c in e.card_numbers],
                "statement_period": e.statement_period,
                "transaction_count": e.transaction_count,
                "sources": e.sources,
            },
            validations=[
                {"entity": v.entity_type, "value": v.masked_value, "status": v.status.value,
                 "reason": v.additional_info.get("reason")}
                for v in state.validation_summary.validations
            ],
            validation_status=status_str,
            api_plan=state.api_plan,
            apis_called=state.selected_apis,
            api_calls=[
                {"api": c.api_name, "status": c.status, "ms": c.execution_time_ms, "attempts": c.attempts,
                 "transport": c.transport, "request": mask_payload(c.request_payload),
                 "error": c.error_message}
                for c in state.api_call_logs
            ],
            has_partial_failure=state.has_partial_failure,
            requires_human_review=state.requires_human_review,
            review_reasons=state.review_reasons,
            response_subject=state.final_email_subject,
            response_masked=state.masked_response,
            response_preview=state.masked_response[:120],
            execution_trace=[mask_text_pii(t) for t in state.execution_trace],
            agent_timings=sorted(state.agent_timings, key=lambda t: t["start_ms"]),
            errors=[mask_text_pii(x) for x in state.errors],
            language=state.detected_language,
            translated=bool(state.translated_body),
            sender_verified=state.email.sender_verified,
            llm_provider=llm_client.provider,
            api_transport=banking_api_client.transport,
            total_execution_ms=ms,
            status="SUCCESS" if not state.errors else "COMPLETED_WITH_ERRORS",
        )

        try:
            store.add_audit(json.loads(record.model_dump_json()))
        except Exception as err:
            log.error("Audit write failed: %s", err)

        if state.requires_human_review:
            review_queue.add({
                "email_id": state.email.email_id,
                "queued_at": now.isoformat(),
                "status": review_queue.PENDING if settings.HITL_ENABLED else review_queue.AUTO_RELEASED,
                "channel": state.email.channel,
                "reply_to": state.email.sender,
                "sender_masked": mask_email(state.email.sender),
                "subject": state.final_email_subject,
                "reasons": state.review_reasons,
                "sentiment": state.sentiment.value,
                "intents": [i.value for i in state.detected_intents],
                "draft": state.masked_response,
            })
        return state


audit_logging_agent = AuditLoggingAgent()
