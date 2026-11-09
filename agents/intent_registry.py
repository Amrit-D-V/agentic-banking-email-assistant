import calendar
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Dict, List, Tuple

from apis.api_client import banking_api_client
from models.schemas import AgentState, EntityValidationDetail, EntityValidationStatus, IntentType
from utils.pii_masker import mask_account_number, mask_card_number


@dataclass(frozen=True)
class IntentHandler:
    intent: IntentType
    title: str
    api_name: str
    entity_options: Tuple[str, ...]
    call: Callable[[str, AgentState], Tuple[Dict[str, Any], Any]]
    render: Callable[[Dict[str, Any], AgentState], List[str]]
    noun: str
    missing_message: str


def default_statement_period(state: AgentState) -> Dict[str, str]:
    last = state.email.received_at.date().replace(day=1) - timedelta(days=1)
    return {
        "label": f"{calendar.month_name[last.month]} {last.year}",
        "date_from": last.replace(day=1).isoformat(),
        "date_to": last.isoformat(),
    }


def _call_statement(acct: str, state: AgentState):
    e = state.entities
    if e.statement_period:
        return banking_api_client.get_statement(acct, e.statement_period, e.date_from, e.date_to)
    p = default_statement_period(state)
    return banking_api_client.get_statement(acct, p["label"], p["date_from"], p["date_to"])


def _render_balance(d: Dict[str, Any], state: AgentState) -> List[str]:
    return [
        f"• Account Number: {mask_account_number(d.get('account_number'))}",
        f"• Account Type: {d.get('account_type', 'Savings')}",
        f"• Available Balance: {d.get('currency', 'INR')} {format_inr(d.get('available_balance', 0.0))}",
    ]


def _render_card(d: Dict[str, Any], state: AgentState) -> List[str]:
    txns = d.get("transactions", [])
    requested = state.entities.transaction_count or len(txns)
    lines = [
        f"• Card: {mask_card_number(d.get('card_number'))} ({d.get('card_type', 'Credit Card')})",
        f"• Last {len(txns)} transaction(s):",
    ]
    for tx in txns:
        lines.append(f"    - {tx['date']} | {tx['merchant']} | {tx['currency']} {format_inr(tx['amount'])} ({tx['type']})")
    if len(txns) < requested:
        lines.append(f"• Note: only {len(txns)} transaction(s) are available on this card for the recent period.")
    return lines


def _render_statement(d: Dict[str, Any], state: AgentState) -> List[str]:
    lines = [
        f"• Statement Period: {d.get('period')}",
        f"• Account: {mask_account_number(d.get('account_number'))}",
        f"• Statement Reference: {d.get('statement_id')}",
        f"• Secure Download Link: {d.get('download_url')}",
        "• The statement PDF is password protected (first 4 letters of your name + date of birth, DDMM).",
    ]
    if not state.entities.statement_period:
        lines.append("• As no period was mentioned, we have shared the statement for the last full month. "
                     "Reply with the month you need if this is not the one you wanted.")
    return lines


def format_inr(amount: float) -> str:
    whole, frac = f"{float(amount):.2f}".split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}{whole}.{frac}"


HANDLERS: Dict[IntentType, IntentHandler] = {
    h.intent: h
    for h in [
        IntentHandler(
            intent=IntentType.BALANCE_ENQUIRY,
            title="Account Balance",
            api_name="GetAccountBalanceAPI",
            entity_options=("account_number",),
            call=lambda acct, state: banking_api_client.get_account_balance(acct),
            render=_render_balance,
            noun="account balance",
            missing_message="Your account number was not provided. For your security, please reply with your "
                            "account number so that we can share the balance.",
        ),
        IntentHandler(
            intent=IntentType.CARD_TRANSACTIONS,
            title="Credit Card Request",
            api_name="GetCardTransactionsAPI",
            entity_options=("credit_card_number",),
            call=lambda card, state: banking_api_client.get_card_transactions(
                card, limit=state.entities.transaction_count or 5),
            render=_render_card,
            noun="credit card transactions",
            missing_message="Your credit card number was not provided. Please reply with the card number "
                            "(masked, e.g. XXXX-XXXX-XXXX-1234, is fine) to view your recent transactions.",
        ),
        IntentHandler(
            intent=IntentType.STATEMENT_REQUEST,
            title="Account Statement",
            api_name="GetStatementAPI",
            entity_options=("account_number", "registered_account"),
            call=_call_statement,
            render=_render_statement,
            noun="account statement",
            missing_message="We could not identify your account. Please reply with your account number, or "
                            "write to us from your registered email address.",
        ),
    ]
}


def handlers_for(state: AgentState) -> List[IntentHandler]:
    return [HANDLERS[i] for i in state.detected_intents if i in HANDLERS]


def targets(h: IntentHandler, validations: List[EntityValidationDetail]) -> List[EntityValidationDetail]:
    primary = [v for v in validations if v.entity_type == h.entity_options[0]]
    if any(v.raw_value for v in primary):
        return primary
    for option in h.entity_options[1:]:
        alt = [v for v in validations if v.entity_type == option and v.status == EntityValidationStatus.VALID]
        if alt:
            return alt
    return primary
