"""Adapter for any service speaking the OpenAI chat-completions API.

**One adapter, many providers.** Groq, OpenRouter, Together, DeepInfra,
Fireworks, vLLM, LM Studio, and Ollama all expose the same
`POST /chat/completions` shape, so they are configuration rather than code:
point `OPENAI_COMPAT_BASE_URL` at whichever one you want and the rest of the
system is unaware anything changed.

This is what the `LLMClient` port was for. Adding a third provider meant one
new file and three lines in the composition root — no change to the domain, the
guardrails, the service, or the API layer.

**No SDK.** The wire format is a JSON POST, so this uses `httpx` (already a
dependency) rather than pulling in the `openai` package. That keeps the
dependency surface — and `pip-audit`'s workload — flat, and avoids a client
library whose defaults are tuned for a provider we are not talking to.

**A caveat worth stating.** Open-weight models follow instructions less
reliably than the frontier models, so Layer 4 rejects their answers more often.
That is the guardrail working, not failing — but expect a higher fallback rate,
and prefer larger instruct-tuned models for this workload.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from app.domain.entities.message import Role
from app.domain.ports.errors import (
    LLMContentBlockedError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.domain.ports.llm_client import (
    LLMRequest,
    LLMResponse,
    ResponseFormat,
    TokenUsage,
)

_ROLE_TO_OPENAI: Final = {Role.USER: "user", Role.ASSISTANT: "assistant"}

_RATE_LIMIT_STATUS: Final = 429
_SERVER_ERROR_FLOOR: Final = 500

#: Finish reasons that mean the provider withheld output rather than completing.
_BLOCKED_REASONS: Final = frozenset({"content_filter"})


class OpenAICompatibleClient:
    """Talks to any OpenAI-compatible endpoint, and satisfies `LLMClient`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

        # Some self-hosted runtimes (Ollama, vLLM) need no key at all. Sending
        # `Bearer ` with an empty value makes those reject the request, so the
        # header is omitted entirely when there is nothing to send.
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout_seconds,
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a request and normalise the reply into the port's shape."""
        payload: dict[str, Any] = {
            "model": self._model,
            # The system prompt is a message with role "system" here, unlike
            # Anthropic's dedicated field and Gemini's `system_instruction`.
            # Absorbing that difference is the adapter's entire job.
            "messages": [
                {"role": "system", "content": request.system_prompt},
                *(
                    {"role": _ROLE_TO_OPENAI[m.role], "content": m.content}
                    for m in request.messages
                ),
            ],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }

        if request.response_format is ResponseFormat.JSON:
            # Widely supported but not universal — Ollama and some smaller
            # runtimes ignore it. That is survivable: the system prompt asks
            # for JSON regardless, and Layer 4's parser tolerates fenced or
            # prose-wrapped objects before it fails closed.
            payload["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as error:
            raise LLMTimeoutError(f"{self._base_url} timed out: {error}") from error
        except httpx.HTTPError as error:
            raise LLMUnavailableError(f"Could not reach {self._base_url}: {error}") from error

        if response.status_code == _RATE_LIMIT_STATUS:
            raise LLMRateLimitError(f"{self._base_url} rate limit exceeded")

        if response.status_code >= _SERVER_ERROR_FLOOR:
            raise LLMUnavailableError(f"{self._base_url} server error ({response.status_code})")

        if response.status_code >= httpx.codes.BAD_REQUEST:
            # The body often names the model or quota problem. It goes to the
            # exception, which is logged — never to the visitor.
            raise LLMUnavailableError(
                f"{self._base_url} returned {response.status_code}: {response.text[:200]}"
            )

        return self._to_domain_response(response.json())

    def _to_domain_response(self, body: dict[str, Any]) -> LLMResponse:
        choices = body.get("choices") or []
        if not choices:
            raise LLMUnavailableError("Provider returned no choices")

        choice = choices[0]
        finish_reason = str(choice.get("finish_reason") or "")

        if finish_reason in _BLOCKED_REASONS:
            # The provider's own safety filter, not our grounding fallback.
            # Conflating them sends the next person to debug this hunting the
            # knowledge base for a problem that is not there.
            raise LLMContentBlockedError(
                f"{self._base_url} filtered the response (finish_reason: {finish_reason})"
            )

        text = str(choice.get("message", {}).get("content") or "")
        if not text.strip():
            raise LLMContentBlockedError(
                f"Provider returned empty content (finish_reason: {finish_reason or 'unknown'})"
            )

        usage = body.get("usage") or {}

        return LLMResponse(
            text=text,
            usage=TokenUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            ),
            stop_reason=finish_reason,
            model=str(body.get("model") or self._model),
        )

    async def aclose(self) -> None:
        """Release the connection pool. Called on application shutdown."""
        await self._client.aclose()
