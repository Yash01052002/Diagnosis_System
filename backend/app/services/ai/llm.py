"""LLM providers for diagnosis generation.

An ``LLMProvider`` takes a system + user prompt and returns a structured
diagnosis. The default ``template`` provider is deterministic and offline: it
composes an answer strictly from the retrieved context it is given, and refuses
to invent one when that context is empty. ``openai`` and ``ollama`` call a real
model over HTTP through the same interface — which is what makes swapping in a
local model a configuration change, not a code change.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.exceptions import AppError


class LLMError(AppError):
    error_code = "llm_error"
    message = "The language model provider failed."


@dataclass(slots=True)
class LLMResult:
    """A structured diagnosis returned by a provider."""

    root_cause: str
    recommended_fix: str | None = None
    summary: str | None = None
    #: The model's own confidence claim (0-1). Advisory only — the pipeline
    #: grounds the final score in retrieval quality, never trusting this alone.
    model_confidence: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LLMRequest:
    """A prompt plus the context the answer must be grounded in."""

    system_prompt: str
    user_prompt: str
    #: The retrieved context passages. An empty list means "nothing to ground
    #: an answer" — providers must not fabricate one.
    context_passages: list[str] = field(default_factory=list)
    max_tokens: int = 800


class LLMProvider(ABC):
    provider: str
    model: str

    @abstractmethod
    async def diagnose(self, request: LLMRequest) -> LLMResult:
        """Produce a structured diagnosis for ``request``."""


#: The instruction shared by every real provider. It is the heart of the
#: anti-hallucination design: answer only from context, and say so when the
#: context does not support an answer.
SYSTEM_PROMPT = """You are an expert embedded-firmware crash analyst for \
STM32 + FreeRTOS systems. You diagnose crashes using ONLY the reference \
material provided in the context.

Rules you must follow:
- Base your diagnosis strictly on the provided context and the crash data.
- If the context does not contain enough information to determine the cause, \
say so explicitly and set confidence low. Do NOT invent register meanings, \
peripheral behaviour, or fixes that are not supported by the context.
- Prefer citing the specific fault type, fault registers and the symbolized \
function where the crash occurred.
- Be concise and concrete.

Respond with a single JSON object and nothing else:
{
  "root_cause": "<what went wrong and why>",
  "recommended_fix": "<concrete steps, or null if unknown>",
  "summary": "<one sentence>",
  "confidence": <number between 0 and 1>
}"""


class TemplateLLMProvider(LLMProvider):
    """Deterministic, offline provider.

    It does not reason — it *reports*: it extracts the crash facts from the
    prompt and grounds them in the retrieved passages, and when there are no
    passages it returns an explicitly uncertain answer. That behaviour is
    exactly what the anti-hallucination tests assert, and it makes the platform
    demonstrable without any external model.
    """

    provider = "template"
    model = "template-v1"

    async def diagnose(self, request: LLMRequest) -> LLMResult:
        facts = _extract_crash_facts(request.user_prompt)
        fault = facts.get("fault_type", "fault")
        function = facts.get("top_function")
        task = facts.get("task")

        if not request.context_passages:
            where = f" in {function}" if function else ""
            return LLMResult(
                root_cause=(
                    f"A {fault}{where} was reported, but no relevant reference "
                    "material was found in the knowledge base to explain it. "
                    "The cause cannot be determined with confidence from the "
                    "available information."
                ),
                recommended_fix=(
                    "Upload the relevant STM32/FreeRTOS documentation or "
                    "engineering notes and re-run the diagnosis; in the "
                    "meantime, inspect the fault registers and the code around "
                    f"{function or 'the faulting address'} manually."
                ),
                summary=f"Uncertain: {fault} with no supporting references.",
                model_confidence=0.1,
                warnings=["no context supplied to the language model"],
            )

        # Ground the answer in the top passage.
        lead = request.context_passages[0].strip().split("\n")
        grounding = " ".join(line.strip() for line in lead if line.strip())[:400]
        where = f" in `{function}`" if function else ""
        for_task = f" (task `{task}`)" if task else ""

        return LLMResult(
            root_cause=(
                f"The {fault}{where}{for_task} is consistent with the "
                f"referenced material: {grounding}"
            ),
            recommended_fix=(
                "Follow the remediation described in the cited reference and "
                f"review the implementation of {function or 'the faulting code'}"
                " against it."
            ),
            summary=f"{fault}{where} — see cited reference.",
            model_confidence=0.7,
            raw=None,
        )


class _HTTPLLMProvider(LLMProvider):
    """Shared prompt assembly for HTTP chat backends."""

    @staticmethod
    def _compose_messages(request: LLMRequest) -> list[dict[str, str]]:
        context_block = (
            "\n\n---\n\n".join(
                f"[Source {i + 1}]\n{passage}"
                for i, passage in enumerate(request.context_passages)
            )
            or "(no reference material was retrieved)"
        )
        user = (
            f"{request.user_prompt}\n\n"
            f"=== REFERENCE CONTEXT ===\n{context_block}\n\n"
            "Diagnose the crash using only the context above."
        )
        return [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _parse(content: str) -> LLMResult:
        """Parse the model's JSON, degrading to prose if it did not comply."""
        payload = _extract_json(content)
        if payload is None:
            return LLMResult(
                root_cause=content.strip()[:4000] or "The model returned no usable output.",
                summary=None,
                model_confidence=None,
                raw=content,
                warnings=["model did not return valid JSON; stored raw text"],
            )
        confidence = payload.get("confidence")
        return LLMResult(
            root_cause=str(payload.get("root_cause", "")).strip()
            or "The model did not identify a root cause.",
            recommended_fix=_opt_str(payload.get("recommended_fix")),
            summary=_opt_str(payload.get("summary")),
            model_confidence=float(confidence) if isinstance(confidence, int | float) else None,
            raw=content,
        )


class OpenAILLMProvider(_HTTPLLMProvider):
    """OpenAI chat completions over REST (no SDK dependency)."""

    provider = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.OPENAI_API_KEY:
            raise LLMError("OPENAI_API_KEY is not set.")
        self.model = settings.OPENAI_CHAT_MODEL
        self._api_key = settings.OPENAI_API_KEY
        self._base_url = settings.OPENAI_BASE_URL.rstrip("/")
        self._timeout = settings.LLM_TIMEOUT_SECONDS

    async def diagnose(self, request: LLMRequest) -> LLMResult:
        import httpx

        body = {
            "model": self.model,
            "messages": self._compose_messages(request),
            "temperature": 0.1,
            "max_tokens": request.max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI chat request failed: {exc}") from exc

        content = data["choices"][0]["message"]["content"]
        result = self._parse(content)
        usage = data.get("usage", {})
        result.prompt_tokens = usage.get("prompt_tokens")
        result.completion_tokens = usage.get("completion_tokens")
        return result


class OllamaLLMProvider(_HTTPLLMProvider):
    """Local chat via an Ollama server."""

    provider = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.OLLAMA_CHAT_MODEL
        self._base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self._timeout = settings.LLM_TIMEOUT_SECONDS

    async def diagnose(self, request: LLMRequest) -> LLMResult:
        import httpx

        body = {
            "model": self.model,
            "messages": self._compose_messages(request),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": request.max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=body)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama chat request failed: {exc}") from exc
        return self._parse(data["message"]["content"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model response."""
    match = _JSON_OBJECT.search(text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_FACT = {
    "fault_type": re.compile(r"Fault type:\s*(.+)", re.IGNORECASE),
    "top_function": re.compile(r"Faulting function:\s*(.+)", re.IGNORECASE),
    "task": re.compile(r"Task:\s*(.+)", re.IGNORECASE),
}


def _extract_crash_facts(prompt: str) -> dict[str, str]:
    """Recover the key crash fields the RAG layer wrote into the prompt."""
    facts: dict[str, str] = {}
    for key, pattern in _FACT.items():
        match = pattern.search(prompt)
        if match:
            value = match.group(1).strip().strip("`").split("\n")[0]
            if value and value.lower() not in ("none", "unknown", "n/a"):
                facts[key] = value
    return facts


def get_llm_provider(settings: Settings) -> LLMProvider:
    """Construct the LLM provider named by ``LLM_PROVIDER``."""
    if settings.LLM_PROVIDER == "openai":
        return OpenAILLMProvider(settings)
    if settings.LLM_PROVIDER == "ollama":
        return OllamaLLMProvider(settings)
    return TemplateLLMProvider()
