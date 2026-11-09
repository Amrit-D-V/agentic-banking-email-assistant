from concurrent.futures import ThreadPoolExecutor

from agents.intent_registry import handlers_for, targets
from models.schemas import AgentState, EntityValidationStatus, IntentType
from utils.policy_rag import policy_rag


class APISelectionAgent:

    def process(self, state: AgentState) -> AgentState:
        tasks, skipped = [], []
        for h in handlers_for(state):
            chosen = targets(h, state.validation_summary.validations)
            for v in chosen:
                if v.status == EntityValidationStatus.VALID:
                    tasks.append((h, v))
                else:
                    skipped.append({"intent": h.intent.value, "api": h.api_name, "value": v.masked_value,
                                    "reason": v.additional_info.get("reason") or v.status.value})
            if not chosen:
                skipped.append({"intent": h.intent.value, "api": h.api_name, "reason": "no " + h.entity_options[0]})

        selected = list(dict.fromkeys(h.api_name for h, _ in tasks))

        if IntentType.POLICY_INQUIRY in state.detected_intents:
            matches = policy_rag.search(f"{state.email.subject}\n{state.translated_body or state.cleaned_body}", top_k=2)
            if matches:
                selected.append("PolicyRAGLookup")
                state.retrieved_policies = [m["text"] for m in matches]
                state.api_results["PolicyRAGLookup"] = {"matches": matches}

        state.selected_apis = selected
        if tasks or skipped:
            state.api_plan.append({
                "stage": "2. data fetch",
                "mode": "parallel" if len(tasks) > 1 else "single",
                "depends_on": "1. validation",
                "apis": [h.api_name for h, _ in tasks],
                "skipped": skipped,
            })

        if tasks:
            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = [(h, v, pool.submit(h.call, v.raw_value, state)) for h, v in tasks]
                for h, v, fut in futures:
                    payload, log = fut.result()
                    state.api_call_logs.append(log)
                    state.fulfilments.append({"intent": h.intent.value, "api": h.api_name, "entity_type": v.entity_type,
                                              "value": v.raw_value, "masked": v.masked_value, "data": payload})
                    state.api_results.setdefault(h.api_name, payload)
                    if "error" in payload:
                        state.errors.append(f"{h.api_name} ({v.masked_value}): {payload.get('error_type')} - {payload.get('error')}")

        state.execution_trace.append(f"APISelectionAgent: dispatched={[h.api_name for h, _ in tasks]}, skipped={[s['intent'] for s in skipped]}")
        return state


api_selection_agent = APISelectionAgent()
