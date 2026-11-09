import re
from pathlib import Path

from config.settings import settings
from models.llm_client import llm_client
from models.schemas import AgentState
from prompts.templates import (
    COMBINED_NLU_SYSTEM_PROMPT,
    COMBINED_NLU_USER_PROMPT,
    TRANSLATE_SYSTEM_PROMPT,
    TRANSLATE_USER_PROMPT,
)
from utils.document_reader import extract_text_from_attachment
from utils.text_cleaner import clean_email_text, detect_language


REFUSAL = re.compile(r"\b(i can'?t|i cannot|i'm sorry|i am sorry|as an ai|unable to translate)\b", re.I)


class EmailUnderstandingAgent:
    def process(self, state: AgentState) -> AgentState:
        body = clean_email_text(state.email.body)
        state.cleaned_body = body

        lang, conf = detect_language(f"{state.email.subject}\n{body}")
        state.detected_language = lang
        state.execution_trace.append(f"EmailUnderstandingAgent: lang={lang} ({conf:.2f})")
        if lang != "en" and settings.TRANSLATE_NON_ENGLISH:
            translated = llm_client.generate(
                TRANSLATE_USER_PROMPT.format(language=lang, body=body[:3000]), TRANSLATE_SYSTEM_PROMPT).strip()
            if self._translation_ok(body, translated):
                state.translated_body = translated
                state.execution_trace.append("EmailUnderstandingAgent: translated to English for analysis")
            else:
                state.execution_trace.append("EmailUnderstandingAgent: translation rejected, analysing original text")

        attachments = [
            f"--- Attachment ({Path(p).name}) ---\n{extract_text_from_attachment(p)}"
            for p in state.email.attachment_paths
        ]
        state.attachment_extracted_text = "\n\n".join(attachments)

        ctx = f"Subject: {state.email.subject}\n\nBody:\n{body}"
        if state.attachment_extracted_text:
            ctx += f"\n\nAttachments:\n{state.attachment_extracted_text}"
        state.full_context = ctx

        if settings.NLU_SINGLE_CALL:
            attachment_ctx = f"Attachment text:\n{state.attachment_extracted_text}" if state.attachment_extracted_text else ""
            state.llm_analysis = llm_client.generate_json(
                COMBINED_NLU_USER_PROMPT.format(subject=state.email.subject, body=state.translated_body or body,
                                                attachment_context=attachment_ctx),
                COMBINED_NLU_SYSTEM_PROMPT, fallback=dict)
            state.execution_trace.append(f"EmailUnderstandingAgent: combined NLU call ({state.llm_analysis.get('_source')})")
        return state

    @staticmethod
    def _translation_ok(original: str, translated: str) -> bool:
        if not translated or translated == original or REFUSAL.search(translated):
            return False
        return all(n in translated for n in re.findall(r"\d{4,}", original))


email_understanding_agent = EmailUnderstandingAgent()
