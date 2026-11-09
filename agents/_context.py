from typing import Any, Callable, Dict

from config.settings import settings
from models.llm_client import llm_client
from models.schemas import AgentState


def attachment_context(state: AgentState) -> str:
    return f"Attachment text:\n{state.attachment_extracted_text}" if state.attachment_extracted_text else ""


def nlu_body(state: AgentState) -> str:
    return state.translated_body or state.cleaned_body


def source_text(state: AgentState) -> str:
    return f"{state.email.subject}\n{state.cleaned_body}\n{state.translated_body}\n{state.attachment_extracted_text}"


def llm_json(state: AgentState, prompt: str, system_prompt: str, fallback: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    if not settings.NLU_SINGLE_CALL:
        return llm_client.generate_json(prompt, system_prompt, fallback=fallback)
    if state.llm_analysis.get("_source") == "llm":
        return state.llm_analysis
    return {**fallback(), "_source": "rules"}
