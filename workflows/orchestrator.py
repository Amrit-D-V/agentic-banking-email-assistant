import time
from datetime import datetime
from typing import Annotated, Any, Dict, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.api_selection_agent import api_selection_agent
from agents.audit_agent import audit_logging_agent
from agents.email_agent import email_understanding_agent
from agents.entity_agent import entity_extraction_agent
from agents.intent_agent import intent_classification_agent
from agents.intent_registry import handlers_for
from agents.response_agent import response_generation_agent
from agents.sentiment_agent import sentiment_analysis_agent
from agents.validation_agent import validation_agent
from models.schemas import AgentState, EmailInput, EntityValidationStatus, IntentType


def _same_state(left: AgentState, right: AgentState) -> AgentState:
    return right


class GraphState(TypedDict):
    state: Annotated[AgentState, _same_state]


def step(agent):
    name = type(agent).__name__

    def run(d):
        state: AgentState = d["state"]
        start_ms = (datetime.now() - state.start_time).total_seconds() * 1000
        t0 = time.perf_counter()
        state = agent.process(state)
        state.agent_timings.append({"agent": name, "start_ms": round(start_ms, 1),
                                    "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return {"state": state}

    return run


def route_post_validation(d: Dict[str, Any]) -> str:
    state: AgentState = d["state"]
    has_valid = any(v.status == EntityValidationStatus.VALID for v in state.validation_summary.validations)
    needs_fetch = bool(handlers_for(state)) and has_valid
    return "api_selection" if needs_fetch or IntentType.POLICY_INQUIRY in state.detected_intents else "response_generation"


def build_graph():
    builder = StateGraph(GraphState)

    builder.add_node("email_understanding", step(email_understanding_agent))
    builder.add_node("intent_classification", step(intent_classification_agent))
    builder.add_node("sentiment_analysis", step(sentiment_analysis_agent))
    builder.add_node("entity_extraction", step(entity_extraction_agent))
    builder.add_node("validation", step(validation_agent))
    builder.add_node("api_selection", step(api_selection_agent))
    builder.add_node("response_generation", step(response_generation_agent))
    builder.add_node("audit_logging", step(audit_logging_agent))

    builder.add_edge(START, "email_understanding")
    for branch in ("intent_classification", "sentiment_analysis", "entity_extraction"):
        builder.add_edge("email_understanding", branch)
    builder.add_edge(["intent_classification", "sentiment_analysis", "entity_extraction"], "validation")

    builder.add_conditional_edges(
        "validation",
        route_post_validation,
        {"api_selection": "api_selection", "response_generation": "response_generation"},
    )
    builder.add_edge("api_selection", "response_generation")
    builder.add_edge("response_generation", "audit_logging")
    builder.add_edge("audit_logging", END)

    return builder.compile()


class BankingEmailOrchestrator:
    def __init__(self):
        self.workflow = build_graph()

    def process_email(self, mail: EmailInput) -> AgentState:
        res = self.workflow.invoke({"state": AgentState(email=mail)})
        return res["state"]


orchestrator = BankingEmailOrchestrator()
