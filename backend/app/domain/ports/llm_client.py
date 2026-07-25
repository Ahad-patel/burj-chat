"""The `LLMClient` port — the domain's contract with any language model.

This is the seam that makes the LLM provider swappable. The domain declares what
it needs; `GeminiClient` and `AnthropicClient` in the infrastructure layer
satisfy it. Nothing here imports an SDK, and an AST test in
`tests/architecture/` fails the build if that ever changes.

**Ports and adapters, concretely.** The dependency arrow points inward: the
adapter knows about the domain, the domain knows nothing about the adapter. That
inversion is the entire reason `LLM_PROVIDER=anthropic` is a one-line change
rather than a refactor.

Python note (`Protocol` vs `ABC`): a `Protocol` is *structural* typing —
`GeminiClient` satisfies `LLMClient` merely by having a matching `generate`
method. It never imports or inherits from this module. An `ABC` would demand
`class GeminiClient(LLMClient)`, which is legal but couples infrastructure to
the domain for no benefit. mypy still verifies conformance at CI time, so we get
the safety without the coupling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.domain.entities.message import Message


class ResponseFormat(StrEnum):
    """How the model should shape its output.

    `JSON` exists for Layer 4 of the guardrail chain, which needs a structured
    response it can check rather than prose it must interpret. Gemini and
    Anthropic force JSON through different mechanisms; absorbing that difference
    is precisely the adapter's job.
    """

    TEXT = "text"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Everything an adapter needs to call its provider.

    A request object rather than loose `(system, context, user_message)`
    arguments, for two reasons:

    1. Three strings cannot carry conversation history, and multi-turn is not
       optional for a chat widget — "what about the 3BHK?" is meaningless alone.
    2. Adding a field (`response_format`) touches one dataclass instead of two
       adapters and every call site.

    The knowledge base is folded into `system_prompt` rather than passed
    separately: where the context belongs in the payload is prompt *policy*,
    which lives in `domain/prompts/`, not transport detail for an adapter to
    decide. Leaving that choice to adapters is how two providers quietly start
    behaving differently.
    """

    system_prompt: str
    messages: tuple[Message, ...]
    max_output_tokens: int = 1024
    temperature: float = 0.2
    response_format: ResponseFormat = ResponseFormat.TEXT

    def __post_init__(self) -> None:
        if not self.system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        if not self.messages:
            raise ValueError("messages must not be empty")
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token counts, for cost tracking and rate accounting."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A provider's reply, normalised across vendors."""

    text: str
    usage: TokenUsage = TokenUsage()
    stop_reason: str = ""
    model: str = ""


class LLMClient(Protocol):
    """The single method the domain needs from any language model."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Produce a completion, or raise an `LLMError` subclass.

        Adapters must translate their SDK's exceptions into the `LLMError`
        family. If `google.genai.errors.APIError` ever reaches a caller, the
        abstraction has leaked and swapping providers stops being free the
        moment anyone writes an `except` clause against it.
        """
        ...
