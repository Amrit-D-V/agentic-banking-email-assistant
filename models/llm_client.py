import json
import logging
import time
from typing import Any, Callable, Dict, Optional

import ollama

from config.settings import settings

logger = logging.getLogger(__name__)


def clean_json_output(raw_output: str) -> str:
    cleaned = raw_output.strip()
    if "```" in cleaned:
        cleaned = cleaned.split("```json", 1)[-1] if "```json" in cleaned else cleaned.split("```", 1)[1]
        cleaned = cleaned.split("```", 1)[0]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start : end + 1].strip()
    return cleaned.strip()


class LLMClient:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self._provider = provider
        self._model = model
        self.stats = {"llm_calls": 0, "llm_failures": 0, "fallbacks": 0, "total_llm_ms": 0.0}

    @property
    def provider(self) -> str:
        return self._provider or settings.LLM_PROVIDER

    @property
    def model(self) -> str:
        return self._model or settings.OLLAMA_MODEL

    def _chat(self, prompt: str, system_prompt: str, json_mode: bool) -> str:
        client = ollama.Client(host=settings.OLLAMA_BASE_URL, timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS)
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [
            {"role": "user", "content": prompt}
        ]
        res = client.chat(
            model=self.model,
            messages=messages,
            format="json" if json_mode else "",
            options={"temperature": 0.0 if json_mode else settings.LLM_TEMPERATURE, "num_predict": 256},
        )
        return res["message"]["content"]

    def generate(self, prompt: str, system_prompt: str = "", fallback: str = "") -> str:
        if self.provider == "ollama":
            try:
                return self._chat(prompt, system_prompt, json_mode=False)
            except Exception as e:
                logger.warning("Ollama generation failed (%s); using fallback text.", e)
        return fallback

    def generate_json(
        self, prompt: str, system_prompt: str = "", fallback: Optional[Callable[[], Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        if self.provider == "ollama":
            t0 = time.perf_counter()
            self.stats["llm_calls"] += 1
            try:
                data = json.loads(clean_json_output(self._chat(prompt, system_prompt, json_mode=True)))
                if not isinstance(data, dict):
                    raise ValueError("LLM returned non-object JSON")
                data["_source"] = "llm"
                return data
            except Exception as e:
                self.stats["llm_failures"] += 1
                logger.warning("LLM JSON call failed (%s); using rule-based fallback.", e)
            finally:
                self.stats["total_llm_ms"] += (time.perf_counter() - t0) * 1000

        self.stats["fallbacks"] += 1
        data = dict(fallback() if fallback else {})
        data["_source"] = "rules"
        return data

    def health(self) -> Dict[str, Any]:
        if self.provider != "ollama":
            return {"status": "DISABLED", "detail": f"provider={self.provider} (rule engine only)"}
        try:
            t0 = time.perf_counter()
            models = ollama.Client(host=settings.OLLAMA_BASE_URL, timeout=2.0).list()
            names = [m.model for m in models.models]
            ms = round((time.perf_counter() - t0) * 1000, 1)
            if self.model in names:
                return {"status": "ONLINE", "detail": f"{self.model} ({ms} ms)"}
            return {"status": "DEGRADED", "detail": f"model {self.model} not pulled"}
        except Exception as e:
            return {"status": "OFFLINE", "detail": str(e)[:120]}


llm_client = LLMClient()
