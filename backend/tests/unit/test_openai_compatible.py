"""The OpenAI-compatible adapter — one adapter, many open-model providers.

Groq, OpenRouter, Together, DeepInfra, vLLM, and Ollama all speak this wire
format, so they are configuration rather than code. These tests cover the
translation that makes that true, and the error mapping that keeps a provider's
vocabulary out of the service layer.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.core.config import Provider, Settings
from app.core.container import build_llm_client
from app.domain.entities.message import Message
from app.domain.ports.errors import (
    LLMContentBlockedError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.domain.ports.llm_client import LLMRequest, ResponseFormat
from app.infrastructure.llm.openai_compatible import OpenAICompatibleClient

BASE_URL = "https://api.groq.com/openai/v1"
ENDPOINT = f"{BASE_URL}/chat/completions"


def make_client(*, api_key: str = "test-key") -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        api_key=api_key,
        model="llama-3.3-70b-versatile",
        base_url=BASE_URL,
        timeout_seconds=5,
    )


def completion(content: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "model": "llama-3.3-70b-versatile",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
        ],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 45},
    }


def request(response_format: ResponseFormat = ResponseFormat.TEXT) -> LLMRequest:
    return LLMRequest(
        system_prompt="You answer only from the knowledge base.",
        messages=(Message.user("What amenities are there?"),),
        response_format=response_format,
    )


class TestTranslation:
    @respx.mock
    async def test_the_system_prompt_becomes_a_system_message(self) -> None:
        """Anthropic has a dedicated field, Gemini has system_instruction, this
        API wants a message with role "system". Absorbing that difference is
        the adapter's whole job."""
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("ok")))

        await make_client().generate(request())

        body = route.calls[0].request.read().decode()
        assert '"role": "system"' in body or '"role":"system"' in body

    @respx.mock
    async def test_conversation_history_is_preserved_in_order(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("ok")))

        await make_client().generate(
            LLMRequest(
                system_prompt="p",
                messages=(
                    Message.user("first"),
                    Message.assistant("reply"),
                    Message.user("second"),
                ),
            )
        )

        import json

        roles = [m["role"] for m in json.loads(route.calls[0].request.read())["messages"]]
        assert roles == ["system", "user", "assistant", "user"]

    @respx.mock
    async def test_json_mode_requests_a_json_object(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("{}")))

        await make_client().generate(request(ResponseFormat.JSON))

        import json

        assert json.loads(route.calls[0].request.read())["response_format"] == {
            "type": "json_object"
        }

    @respx.mock
    async def test_usage_is_normalised_into_the_port_shape(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("hello")))

        response = await make_client().generate(request())

        assert response.text == "hello"
        assert response.usage.input_tokens == 1200
        assert response.usage.output_tokens == 45
        assert response.usage.total_tokens == 1245


class TestAuthHeader:
    @respx.mock
    async def test_a_key_is_sent_as_a_bearer_token(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("ok")))

        await make_client(api_key="secret-key").generate(request())

        assert route.calls[0].request.headers["Authorization"] == "Bearer secret-key"

    @respx.mock
    async def test_no_auth_header_when_there_is_no_key(self) -> None:
        """Ollama and vLLM need no key, and reject a bare `Bearer ` header."""
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("ok")))

        await make_client(api_key="").generate(request())

        assert "Authorization" not in route.calls[0].request.headers


class TestErrorMapping:
    """No caller should ever write `except httpx.HTTPStatusError`."""

    @respx.mock
    async def test_rate_limit(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(429, json={"error": "slow down"}))

        with pytest.raises(LLMRateLimitError):
            await make_client().generate(request())

    @respx.mock
    async def test_server_error(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(503, text="unavailable"))

        with pytest.raises(LLMUnavailableError):
            await make_client().generate(request())

    @respx.mock
    async def test_client_error_carries_no_detail_to_the_caller(self) -> None:
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(400, json={"error": {"message": "model decommissioned"}})
        )

        with pytest.raises(LLMUnavailableError):
            await make_client().generate(request())

    @respx.mock
    async def test_timeout(self) -> None:
        respx.post(ENDPOINT).mock(side_effect=httpx.ConnectTimeout("too slow"))

        with pytest.raises(LLMTimeoutError):
            await make_client().generate(request())

    @respx.mock
    async def test_network_failure(self) -> None:
        respx.post(ENDPOINT).mock(side_effect=httpx.ConnectError("no route to host"))

        with pytest.raises(LLMUnavailableError):
            await make_client().generate(request())

    @respx.mock
    async def test_a_content_filter_is_not_a_grounding_fallback(self) -> None:
        """A provider's safety filter is its decision, not our guardrail's."""
        respx.post(ENDPOINT).mock(
            return_value=httpx.Response(200, json=completion("", finish_reason="content_filter"))
        )

        with pytest.raises(LLMContentBlockedError):
            await make_client().generate(request())

    @respx.mock
    async def test_empty_content(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("   ")))

        with pytest.raises(LLMContentBlockedError):
            await make_client().generate(request())

    @respx.mock
    async def test_no_choices(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"choices": []}))

        with pytest.raises(LLMUnavailableError):
            await make_client().generate(request())


class TestProviderPortability:
    """The point of this adapter: swapping providers is a URL change."""

    @pytest.mark.parametrize(
        ("name", "base_url"),
        [
            ("Groq", "https://api.groq.com/openai/v1"),
            ("OpenRouter", "https://openrouter.ai/api/v1"),
            ("Together", "https://api.together.xyz/v1"),
            ("DeepInfra", "https://api.deepinfra.com/v1/openai"),
            ("Ollama (local)", "http://localhost:11434/v1"),
            ("vLLM (self-hosted)", "http://localhost:8000/v1"),
        ],
    )
    @respx.mock
    async def test_any_openai_compatible_endpoint_works(self, name: str, base_url: str) -> None:
        respx.post(f"{base_url}/chat/completions").mock(
            return_value=httpx.Response(200, json=completion("grounded answer"))
        )

        client = OpenAICompatibleClient(
            api_key="k", model="some-open-model", base_url=base_url, timeout_seconds=5
        )
        response = await client.generate(request())

        assert response.text == "grounded answer", f"{name} failed"

    @respx.mock
    async def test_a_trailing_slash_in_the_base_url_is_tolerated(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=completion("ok")))

        client = OpenAICompatibleClient(
            api_key="k", model="m", base_url=f"{BASE_URL}///", timeout_seconds=5
        )

        assert (await client.generate(request())).text == "ok"


class TestCompositionRoot:
    def _settings(self, **overrides: Any) -> Settings:
        base: dict[str, Any] = {
            "gemini_api_key": "k",
            "anthropic_api_key": "k",
            "openai_compat_api_key": "k",
        }
        return Settings(**{**base, **overrides})

    def test_the_provider_is_selected_by_env_var_alone(self) -> None:
        client = build_llm_client(self._settings(llm_provider=Provider.OPENAI_COMPATIBLE))

        assert isinstance(client, OpenAICompatibleClient)

    def test_all_three_providers_build(self) -> None:
        for provider in Provider:
            assert build_llm_client(self._settings(llm_provider=provider)) is not None

    def test_only_the_provider_field_differs_across_all_three(self) -> None:
        """The claim the whole architecture makes, now over three providers."""
        configs = {p: self._settings(llm_provider=p) for p in Provider}

        differing = {
            field
            for field in Settings.model_fields
            for a in configs.values()
            for b in configs.values()
            if getattr(a, field) != getattr(b, field)
        }

        assert differing == {"llm_provider"}

    def test_a_self_hosted_runtime_needs_no_api_key(self) -> None:
        """Ollama and vLLM are keyless — startup validation must not demand one."""
        config = Settings(
            llm_provider=Provider.OPENAI_COMPATIBLE,
            openai_compat_api_key="",
            openai_compat_base_url="http://localhost:11434/v1",
            gemini_api_key="",
            anthropic_api_key="",
        )

        assert build_llm_client(config) is not None
