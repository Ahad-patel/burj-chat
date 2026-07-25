"""The `LLMClient` port — the seam that makes providers swappable."""

from __future__ import annotations

import pytest

from app.domain.entities.message import Message
from app.domain.errors import DomainError
from app.domain.ports.errors import (
    LLMContentBlockedError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.domain.ports.llm_client import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    ResponseFormat,
    TokenUsage,
)
from tests.conftest import FakeLLMClient


class TestLLMRequest:
    def test_defaults_are_conservative(self) -> None:
        """Low temperature: we want faithful recall, not creative writing."""
        request = LLMRequest(system_prompt="You are an assistant.", messages=(Message.user("hi"),))

        assert request.temperature == 0.2
        assert request.response_format is ResponseFormat.TEXT

    def test_is_immutable(self) -> None:
        request = LLMRequest(system_prompt="prompt", messages=(Message.user("hi"),))

        with pytest.raises(AttributeError):
            request.temperature = 1.5  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"system_prompt": "  "}, "system_prompt"),
            ({"messages": ()}, "messages"),
            ({"max_output_tokens": 0}, "max_output_tokens"),
            ({"temperature": -0.1}, "temperature"),
            ({"temperature": 2.5}, "temperature"),
        ],
    )
    def test_invalid_requests_are_rejected(self, kwargs: dict[str, object], match: str) -> None:
        defaults: dict[str, object] = {
            "system_prompt": "prompt",
            "messages": (Message.user("hi"),),
        }

        with pytest.raises(ValueError, match=match):
            LLMRequest(**{**defaults, **kwargs})  # type: ignore[arg-type]


class TestTokenUsage:
    def test_total_is_the_sum(self) -> None:
        assert TokenUsage(input_tokens=100, output_tokens=25).total_tokens == 125

    def test_defaults_to_zero(self) -> None:
        assert TokenUsage().total_tokens == 0


class TestProtocolConformance:
    def test_fake_client_satisfies_the_port(self, fake_llm: FakeLLMClient) -> None:
        """Structural typing in action.

        `FakeLLMClient` inherits nothing and imports nothing from the port — it
        conforms purely by having a matching `generate` method. Assigning it to
        an `LLMClient`-annotated name is what makes mypy verify that at CI time.
        """
        client: LLMClient = fake_llm

        assert client is fake_llm

    async def test_fake_client_records_requests(self, fake_llm: FakeLLMClient) -> None:
        request = LLMRequest(system_prompt="prompt", messages=(Message.user("hello"),))

        result = await fake_llm.generate(request)

        assert isinstance(result, LLMResponse)
        assert fake_llm.call_count == 1
        assert fake_llm.requests[0] is request

    async def test_fake_client_returns_queued_responses_in_order(self) -> None:
        client = FakeLLMClient("first", "second")
        request = LLMRequest(system_prompt="prompt", messages=(Message.user("hi"),))

        assert (await client.generate(request)).text == "first"
        assert (await client.generate(request)).text == "second"
        # Exhausted queue repeats the last response rather than raising.
        assert (await client.generate(request)).text == "second"


class TestErrorHierarchy:
    @pytest.mark.parametrize(
        "error_type",
        [LLMTimeoutError, LLMRateLimitError, LLMUnavailableError, LLMContentBlockedError],
    )
    def test_every_provider_error_is_catchable_as_llm_error(
        self, error_type: type[LLMError]
    ) -> None:
        """Services handle one family, so they stay identical across providers.

        An `except anthropic.RateLimitError` in a service would silently do
        nothing under Gemini — and vice versa.
        """
        with pytest.raises(LLMError):
            raise error_type("provider failed")

    def test_llm_errors_are_domain_errors(self) -> None:
        assert issubclass(LLMError, DomainError)
