from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Tuple

from agents.intent_registry import handlers_for, targets
from apis.api_client import banking_api_client
from config.settings import settings
from models.schemas import (
    AgentState,
    EntityValidationDetail,
    EntityValidationStatus,
    ValidationSummary,
)
from utils.pii_masker import mask_account_number, mask_card_number

V = EntityValidationStatus
MASKERS = {"account_number": mask_account_number, "credit_card_number": mask_card_number}


class ValidationAgent:

    def process(self, state: AgentState) -> AgentState:
        handlers = handlers_for(state)
        if not handlers:
            state.validation_summary = ValidationSummary(overall_valid=False, validations=[])
            return state

        needed = {opt for h in handlers for opt in h.entity_options}
        values = {
            "account_number": state.entities.account_numbers or ([state.entities.account_number] if state.entities.account_number else []),
            "credit_card_number": state.entities.card_numbers or ([state.entities.credit_card_number] if state.entities.credit_card_number else []),
        }

        self._verify_sender(state)
        sender_ok = bool(state.customer_profile)

        validations: List[EntityValidationDetail] = []
        if settings.REQUIRE_REGISTERED_SENDER and not sender_ok:
            for entity_type in ("account_number", "credit_card_number"):
                if entity_type in needed:
                    raw = values[entity_type][0] if values[entity_type] else None
                    validations.append(EntityValidationDetail(
                        entity_type=entity_type, raw_value=raw,
                        masked_value=MASKERS[entity_type](raw) if raw else None,
                        status=V.INVALID,
                        message="Sender is not a verified registered customer; account data withheld.",
                        additional_info={"reason": "UNREGISTERED_SENDER"},
                    ))
        else:
            validations += self._validate_entities(state, needed, values)
            if "registered_account" in needed and not values["account_number"] and state.customer_profile.get("primary_account"):
                primary = state.customer_profile["primary_account"]
                validations.append(EntityValidationDetail(
                    entity_type="registered_account",
                    raw_value=primary,
                    masked_value=mask_account_number(primary),
                    status=V.VALID,
                    message="Primary account resolved from the sender's registered email address.",
                    customer_name=state.customer_profile.get("customer_name"),
                    additional_info={"source": "registered_email"},
                ))

        outcomes = [v.status == V.VALID for h in handlers for v in targets(h, validations)] or [False]
        state.validation_summary = ValidationSummary(
            overall_valid=all(outcomes),
            has_partial_failure=any(outcomes) and not all(outcomes),
            validations=validations,
        )
        state.has_partial_failure = state.validation_summary.has_partial_failure
        state.execution_trace.append(
            "ValidationAgent: " + ", ".join(f"{v.entity_type}={v.status.value}" for v in validations)
            + f" | sender_registered={sender_ok}, sender_verified={state.email.sender_verified}"
        )
        return state

    def _verify_sender(self, state: AgentState) -> None:
        if state.email.sender_verified is False:
            state.execution_trace.append("ValidationAgent: sender failed SPF/DKIM verification")
            return
        data, log = banking_api_client.lookup_customer_by_email(state.email.sender)
        state.api_call_logs.append(log)
        state.api_plan.append({"stage": "1a. sender verification", "mode": "single", "apis": [log.api_name]})
        if data.get("status") == "FOUND":
            state.customer_profile = {k: data.get(k) for k in ("customer_id", "customer_name", "primary_account")}

    def _validate_entities(self, state: AgentState, needed, values) -> List[EntityValidationDetail]:
        jobs: List[Tuple[str, str, Callable[[], Tuple[Dict[str, Any], Any]]]] = []
        for value in values["account_number"] if "account_number" in needed else []:
            jobs.append(("account_number", value, lambda v=value: banking_api_client.validate_account(v)))
        for value in values["credit_card_number"] if "credit_card_number" in needed else []:
            jobs.append(("credit_card_number", value, lambda v=value: banking_api_client.validate_card(v)))

        results = []
        if jobs:
            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                futures = [(t, v, pool.submit(fn)) for t, v, fn in jobs]
                results = [(t, v, f.result()) for t, v, f in futures]
            for _, _, (_, log) in results:
                state.api_call_logs.append(log)
            state.api_plan.append({
                "stage": "1b. entity validation",
                "mode": "parallel" if len(jobs) > 1 else "single",
                "apis": [log.api_name for _, _, (_, log) in results],
            })

        details = [self._detail(t, v, res, state) for t, v, res in results]
        for entity_type in ("account_number", "credit_card_number"):
            if entity_type in needed and not values[entity_type]:
                details.append(EntityValidationDetail(
                    entity_type=entity_type, status=V.MISSING,
                    message=f"{entity_type.replace('_', ' ').capitalize()} was not provided in the request.",
                ))
        return details

    @staticmethod
    def _detail(entity_type: str, value: str, result, state: AgentState) -> EntityValidationDetail:
        data, _ = result
        base = dict(entity_type=entity_type, raw_value=value, masked_value=MASKERS[entity_type](value))
        if "error" in data:
            return EntityValidationDetail(
                **base, status=V.UNAVAILABLE, message=f"Validation service error ({data.get('error_type')}).",
                additional_info={"reason": data.get("error_type")},
            )
        if data.get("status") != "VALID":
            return EntityValidationDetail(
                **base, status=V.INVALID, message=data.get("message") or "Not found.",
                additional_info={"reason": "NOT_FOUND"},
            )
        owner, sender_id = data.get("customer_id"), state.customer_profile.get("customer_id")
        if settings.ENFORCE_SENDER_OWNERSHIP and sender_id and owner and owner != sender_id:
            return EntityValidationDetail(
                **base, status=V.INVALID,
                message="Exists, but is not linked to the sender's registered email address.",
                additional_info={"reason": "OWNERSHIP_MISMATCH"},
            )
        return EntityValidationDetail(
            **base, status=V.VALID, message=data.get("message") or "Verified.",
            customer_name=data.get("customer_name"),
            additional_info={k: data.get(k) for k in ("account_type", "card_type", "customer_id") if data.get(k)},
        )


validation_agent = ValidationAgent()
