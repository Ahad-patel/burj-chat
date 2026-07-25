"""Gemini adapter for the `LLMClient` port.

One of exactly two modules permitted to import a vendor SDK — enforced by
`tests/architecture/test_layer_boundaries.py`.

The adapter's whole job is translation: our `LLMRequest` in, the SDK's shapes
out, and every `google.genai` exception converted into an `LLMError`. Nothing
about Gemini escapes this file, which is what makes `LLM_PROVIDER=anthropic` a
one-line change rather than a refactor.
"""

from __future__ import annotations

from typing import Final

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

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

#: Gemini names the assistant role "model"; the domain calls it "assistant".
#: Mapping it here rather than in the domain keeps a vendor's vocabulary out of
#: our entities.
_ROLE_TO_GEMINI: Final = {Role.USER: "user", Role.ASSISTANT: "model"}

_RATE_LIMIT_STATUS: Final = 429
_SERVER_ERROR_FLOOR: Final = 500


class GeminiClient:
    """Talks to Google AI Studio, and satisfies `LLMClient` structurally.

    Note it inherits from nothing and imports no port class. mypy verifies
    conformance where the composition root assigns it to an `LLMClient`.
    """

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        self._model = model
        # The SDK takes its timeout in milliseconds.
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a request to Gemini and normalise the reply."""
        config = types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            # Gemini forces JSON with a MIME type. Anthropic uses a different
            # mechanism entirely — absorbing that difference is precisely why
            # `response_format` is a port concept and not a provider one.
            response_mime_type=(
                "application/json"
                if request.response_format is ResponseFormat.JSON
                else "text/plain"
            ),
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    _to_content(message.role, message.content) for message in request.messages
                ],
                config=config,
            )
        except genai_errors.APIError as error:
            raise _translate(error) from error
        except TimeoutError as error:
            raise LLMTimeoutError(f"Gemini timed out: {error}") from error

        return _to_domain_response(response, model=self._model)


def _to_content(role: Role, text: str) -> types.Content:
    return types.Content(role=_ROLE_TO_GEMINI[role], parts=[types.Part(text=text)])


def _to_domain_response(response: types.GenerateContentResponse, *, model: str) -> LLMResponse:
    """Convert an SDK response into the port's shape.

    Gemini returns an empty `.text` when its own safety filters block a
    response. That is a vendor refusal, not our grounding fallback, and the two
    must not be conflated — a visitor told "I don't have information about
    that" when Gemini actually declined would send us hunting the knowledge
    base for a problem that is not there.
    """
    if not (text := response.text or ""):
        reason = _blocked_reason(response)
        raise LLMContentBlockedError(f"Gemini returned no content (reason: {reason})")

    usage = response.usage_metadata
    return LLMResponse(
        text=text,
        usage=TokenUsage(
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=(usage.candidates_token_count or 0) if usage else 0,
        ),
        stop_reason=_finish_reason(response),
        model=model,
    )


def _blocked_reason(response: types.GenerateContentResponse) -> str:
    if (feedback := response.prompt_feedback) and feedback.block_reason:
        return str(feedback.block_reason)
    return _finish_reason(response) or "unknown"


def _finish_reason(response: types.GenerateContentResponse) -> str:
    if response.candidates and (reason := response.candidates[0].finish_reason):
        return str(reason)
    return ""


def _translate(error: genai_errors.APIError) -> Exception:
    """Map a Gemini SDK error onto the provider-neutral `LLMError` family.

    Without this, a service would have to write `except genai_errors.APIError`
    — and that clause would silently do nothing the moment `LLM_PROVIDER` is
    set to `anthropic`.
    """
    status = getattr(error, "code", None)

    if status == _RATE_LIMIT_STATUS:
        return LLMRateLimitError(f"Gemini rate limit exceeded: {error}")
    if isinstance(status, int) and status >= _SERVER_ERROR_FLOOR:
        return LLMUnavailableError(f"Gemini server error ({status}): {error}")

    return LLMUnavailableError(f"Gemini request failed: {error}")
