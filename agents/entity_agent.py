import re

from agents._context import attachment_context, llm_json, nlu_body, source_text
from config.settings import settings
from models.schemas import AgentState, ExtractedEntities
from prompts.templates import ENTITY_EXTRACTION_SYSTEM_PROMPT, ENTITY_EXTRACTION_USER_PROMPT
from utils.nlu_rules import (
    extract_customer_name,
    extract_statement_period,
    extract_transaction_count,
    find_identifiers,
    is_plausible_name,
)

DEFAULT_TRANSACTION_COUNT = 5


def _compact(value) -> str:
    return re.sub(r"[ -]", "", str(value or "")).strip()


class EntityExtractionAgent:

    def process(self, state: AgentState) -> AgentState:
        text = source_text(state)
        compact_text = _compact(text)
        ids = find_identifiers(text)
        period = extract_statement_period(text, today=state.email.received_at.date())
        count = extract_transaction_count(text)
        name = extract_customer_name(state.cleaned_body)
        name = name if is_plausible_name(name) else None

        prompt = ENTITY_EXTRACTION_USER_PROMPT.format(
            subject=state.email.subject, body=nlu_body(state), attachment_context=attachment_context(state)
        )
        res = llm_json(state, prompt, ENTITY_EXTRACTION_SYSTEM_PROMPT, fallback=dict)
        llm_ran = res.get("_source") == "llm"

        def grounded(value) -> bool:
            v = _compact(value)
            return bool(v) and v.lower() in compact_text.lower()

        sources, conf = {}, {}

        acct = ids["account"][0] if ids["account"] else None
        card = ids["card"][0] if ids["card"] else None
        llm_acct, llm_card = _compact(res.get("account_number")), _compact(res.get("credit_card_number"))
        for key, value, llm_value in (("account_number", acct, llm_acct), ("credit_card_number", card, llm_card)):
            if value:
                sources[key] = "rules+llm" if llm_ran and llm_value == value else "rules"
                conf[key] = 0.98 if sources[key] == "rules+llm" else 0.92
        if not acct and llm_ran and grounded(llm_acct) and llm_acct.isdigit() and llm_acct != card:
            acct, sources["account_number"], conf["account_number"] = llm_acct, "llm", 0.7
        if not card and llm_ran and grounded(llm_card) and llm_card != acct:
            card, sources["credit_card_number"], conf["credit_card_number"] = llm_card, "llm", 0.7

        llm_count = res.get("transaction_count")
        if count is None and llm_ran and isinstance(llm_count, int) and 1 <= llm_count <= 50 \
                and re.search(rf"\b{llm_count}\b", text):
            count, sources["transaction_count"] = llm_count, "llm"
        elif count is not None:
            sources["transaction_count"] = "rules"

        llm_period = res.get("statement_period")
        if not period and llm_ran and llm_period and str(llm_period).lower() in text.lower():
            period = extract_statement_period(str(llm_period), today=state.email.received_at.date())
            if period:
                sources["statement_period"] = "llm"
        elif period:
            sources["statement_period"] = "rules"

        llm_name = res.get("customer_name")
        if not name and llm_ran and is_plausible_name(llm_name) and str(llm_name).lower() in state.cleaned_body.lower():
            name, sources["customer_name"] = str(llm_name).strip(), "llm"
        elif name:
            sources["customer_name"] = "rules"

        limit = settings.MAX_ENTITIES_PER_EMAIL
        accounts = (ids["account"] or ([acct] if acct else []))[:limit]
        cards = (ids["card"] or ([card] if card else []))[:limit]

        state.entities = ExtractedEntities(
            account_number=acct,
            credit_card_number=card,
            account_numbers=accounts,
            card_numbers=cards,
            statement_period=period["label"] if period else None,
            date_from=period["date_from"] if period else None,
            date_to=period["date_to"] if period else None,
            transaction_count=count or DEFAULT_TRANSACTION_COUNT,
            customer_name=name,
            confidence_scores=conf,
            sources=sources,
        )
        state.execution_trace.append(
            f"EntityExtractionAgent: accounts={len(accounts)}, cards={len(cards)}, period={state.entities.statement_period}, "
            f"count={state.entities.transaction_count}, sources={sources}"
        )
        return state


entity_extraction_agent = EntityExtractionAgent()
