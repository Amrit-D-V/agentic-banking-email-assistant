from agents._context import attachment_context, llm_json, nlu_body, source_text
from models.schemas import AgentState, SentimentType
from prompts.templates import SENTIMENT_SYSTEM_PROMPT, SENTIMENT_USER_PROMPT
from utils.nlu_rules import rule_sentiment


class SentimentAnalysisAgent:

    def process(self, state: AgentState) -> AgentState:
        text = f"{state.email.subject}\n{nlu_body(state)}"
        rule_label, cues = rule_sentiment(text)
        prompt = SENTIMENT_USER_PROMPT.format(
            subject=state.email.subject, body=nlu_body(state), attachment_context=attachment_context(state)
        )
        res = llm_json(state, prompt, SENTIMENT_SYSTEM_PROMPT, fallback=lambda: {"sentiment": rule_label})
        llm_label = str(res.get("sentiment", "NEUTRAL")).upper()
        llm_ran = res.get("_source") == "llm"

        if rule_label == "NEGATIVE_URGENT":
            sentiment = SentimentType.NEGATIVE_URGENT
            reason = f"Urgency/negative cues detected: {', '.join(repr(c) for c in cues[:4])}."
        elif llm_ran and ("NEGATIVE" in llm_label or "URGENT" in llm_label):
            sentiment = SentimentType.NEGATIVE_URGENT
            reason = res.get("sentiment_reason") or "LLM detected a negative or urgent tone."
        elif rule_label == "POSITIVE":
            sentiment = SentimentType.POSITIVE
            reason = "Customer expressed appreciation."
        else:
            sentiment = SentimentType.NEUTRAL
            reason = "Routine banking request with no emotional charge."

        state.sentiment = sentiment
        state.urgency_flag = sentiment == SentimentType.NEGATIVE_URGENT
        state.sentiment_reason = reason
        state.execution_trace.append(
            f"SentimentAnalysisAgent: {sentiment.value} (rules={rule_label}, llm={llm_label if llm_ran else 'n/a'})"
        )
        return state


sentiment_analysis_agent = SentimentAnalysisAgent()
