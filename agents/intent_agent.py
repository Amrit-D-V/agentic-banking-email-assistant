from agents._context import attachment_context, llm_json, nlu_body, source_text
from models.schemas import AgentState, IntentType
from prompts.templates import INTENT_SYSTEM_PROMPT, INTENT_USER_PROMPT
from utils.nlu_rules import intent_is_grounded, rule_analysis


class IntentClassificationAgent:

    def process(self, state: AgentState) -> AgentState:
        text = source_text(state)
        rules, vetoed = rule_analysis(text)
        prompt = INTENT_USER_PROMPT.format(
            subject=state.email.subject, body=nlu_body(state), attachment_context=attachment_context(state)
        )
        res = llm_json(state, prompt, INTENT_SYSTEM_PROMPT, fallback=lambda: {"intents": rules})
        llm_ran = res.get("_source") == "llm"

        raw = res.get("intents") or []
        llm_intents = []
        for item in [raw] if isinstance(raw, str) else raw:
            try:
                intent = IntentType(str(item).strip().upper())
            except ValueError:
                continue
            if intent not in (IntentType.GENERAL_INQUIRY, IntentType.UNKNOWN):
                llm_intents.append(intent.value)
        llm_conf = res.get("intent_confidences") if isinstance(res.get("intent_confidences"), dict) else {}

        intents, confidences = [], {}
        for intent in dict.fromkeys(rules + llm_intents):
            in_rules, in_llm = intent in rules, llm_ran and intent in llm_intents
            if in_rules and in_llm:
                conf = 0.97
            elif in_rules:
                conf = 0.80 if llm_ran else 0.85
            elif intent in vetoed:
                state.execution_trace.append(f"IntentClassificationAgent: rule veto on LLM intent {intent}")
                continue
            elif intent_is_grounded(intent, text):
                conf = min(float(llm_conf.get(intent, 0.7) or 0.7), 0.7)
            else:
                state.execution_trace.append(f"IntentClassificationAgent: rejected ungrounded LLM intent {intent}")
                continue
            intents.append(IntentType(intent))
            confidences[intent] = round(conf, 2)

        if not intents:
            intents = [IntentType.GENERAL_INQUIRY]
            confidences = {IntentType.GENERAL_INQUIRY.value: 0.9 if llm_ran else 0.75}

        state.detected_intents = intents
        state.intent_confidences = confidences
        state.execution_trace.append(
            f"IntentClassificationAgent: {[i.value for i in intents]} (rules={rules}, llm={llm_intents if llm_ran else 'n/a'})"
        )
        return state


intent_classification_agent = IntentClassificationAgent()
