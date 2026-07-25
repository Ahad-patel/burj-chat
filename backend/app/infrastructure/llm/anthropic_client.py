"""Anthropic adapter for the `LLMClient` port.

The second and last module permitted to import a vendor SDK.

**This adapter is the clearest justification for the whole port design.**
Current Claude models — Opus 5, Sonnet 5, Opus 4.8, Opus 4.7 — *reject*
`temperature` with a 400; older ones accept it. Gemini requires it. If the
service layer set `temperature` directly on an SDK call, switching
`LLM_PROVIDER` to `anthropic` would produce a hard runtime failure on the first
visitor question. Because the domain expresses intent ("be faithful, not
creative") as a port field, this file can honour that intent on models that
support it and drop it silently on models that do not. One env var, no code
change, no 400.
"""

from __future__ import annotations

import re
from typing import Any, Final

import anthropic
from anthropic.types import MessageParam, TextBlock

from app.core.logging import get_logger
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

logger = get_logger(__name__)

_ROLE_TO_ANTHROPIC: Final[dict[Role, Any]] = {Role.USER: "user", Role.ASSISTANT: "assistant"}

#: Model families that still accept sampling parameters. Newer models return a
#: 400 for `temperature`, so the safe default is to omit it and only send it
#: where it is known to be accepted — the reverse would turn a model upgrade
#: into a production outage.
_ACCEPTS_TEMPERATURE: Final = re.compile(
    r"claude-(?:haiku|3)|claude-(?:opus|sonnet)-4-[56]",
    re.IGNORECASE,
)

#: The JSON contract Layer 4 validates. Declaring it as a schema rather than
#: trusting the prompt means the provider enforces the shape, so the validator
#: spends its effort on grounding instead of on parsing.
_ANSWER_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "grounded": {"type": "boolean"},
        "sections_used": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "grounded", "sections_used"],
    "additionalProperties": False,
}


class AnthropicClient:
    """Talks to the Claude API, and satisfies `LLMClient` structurally."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        self._model = model
        self._sends_temperature = bool(_ACCEPTS_TEMPERATURE.search(model))
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)

        if not self._sends_temperature:
            logger.info(
                "anthropic_temperature_omitted",
                model=model,
                reason="model rejects sampling parameters; grounding is enforced by the prompt",
            )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a request to Claude and normalise the reply."""
        extra: dict[str, Any] = {}

        if self._sends_temperature:
            extra["temperature"] = request.temperature

        if request.response_format is ResponseFormat.JSON:
            extra["output_config"] = {"format": {"type": "json_schema", "schema": _ANSWER_SCHEMA}}

        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=request.max_output_tokens,
                system=request.system_prompt,
                messages=[
                    MessageParam(role=_ROLE_TO_ANTHROPIC[m.role], content=m.content)
                    for m in request.messages
                ],
                **extra,
            )
        except anthropic.APITimeoutError as error:
            raise LLMTimeoutError(f"Claude timed out: {error}") from error
        except anthropic.RateLimitError as error:
            raise LLMRateLimitError(f"Claude rate limit exceeded: {error}") from error
        except anthropic.APIConnectionError as error:
            raise LLMUnavailableError(f"Could not reach Claude: {error}") from error
        except anthropic.APIStatusError as error:
            raise LLMUnavailableError(
                f"Claude returned {error.status_code}: {error.message}"
            ) from error

        # A safety refusal is a vendor decision, not our grounding fallback.
        # Conflating them would send the next person to debug this hunting the
        # knowledge base for a problem that is not there.
        if message.stop_reason == "refusal":
            raise LLMContentBlockedError("Claude declined the request on safety grounds")

        if not (text := _first_text(message.content)):
            raise LLMContentBlockedError(
                f"Claude returned no text (stop_reason: {message.stop_reason})"
            )

        return LLMResponse(
            text=text,
            usage=TokenUsage(
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
            ),
            stop_reason=message.stop_reason or "",
            model=message.model,
        )


def _first_text(blocks: list[Any]) -> str:
    """Return the first text block's content.

    A response is a list of typed blocks — text, thinking, tool use. Indexing
    `content[0].text` blindly breaks the moment a thinking block leads, which
    is the default on current Claude models.
    """
    for block in blocks:
        if isinstance(block, TextBlock):
            return block.text
    return ""
