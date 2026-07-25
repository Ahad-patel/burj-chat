"""Infrastructure: config, KB loader, adapters, and the composition root.

The adapter tests here use mocks rather than the network. What they verify is
the *translation* each adapter performs — the thing that actually differs
between providers and the thing that breaks when an SDK changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Environment, Provider, Settings
from app.core.container import build_llm_client
from app.domain.entities.message import Message
from app.domain.errors import KnowledgeBaseError
from app.domain.ports.errors import LLMContentBlockedError, LLMRateLimitError
from app.domain.ports.llm_client import LLMClient, LLMRequest, ResponseFormat
from app.infrastructure.kb.loader import load_knowledge_base
from app.infrastructure.llm.anthropic_client import AnthropicClient
from app.infrastructure.llm.gemini_client import GeminiClient

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_PATH = REPO_ROOT / "knowledge-base" / "knowledge_base.xml"


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_provider": Provider.GEMINI,
        "gemini_api_key": "test-key",
        "anthropic_api_key": "test-key",
    }
    return Settings(**{**base, **overrides})


class TestSettings:
    def test_defaults_to_gemini(self) -> None:
        """The free tier is the development default, per the build plan."""
        assert settings().llm_provider is Provider.GEMINI

    def test_missing_key_for_the_active_provider_fails_at_startup(self) -> None:
        """A crash on boot beats a 500 on the first visitor question."""
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            Settings(llm_provider=Provider.GEMINI, gemini_api_key="", anthropic_api_key="x")

    def test_only_the_active_providers_key_is_required(self) -> None:
        """Running on Gemini must not force an unused Anthropic credential."""
        config = Settings(
            llm_provider=Provider.GEMINI, gemini_api_key="present", anthropic_api_key=""
        )

        assert config.active_api_key == "present"

    def test_an_unknown_provider_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="llm_provider"):
            Settings(llm_provider="openai", gemini_api_key="x")  # type: ignore[arg-type]

    def test_cors_origins_are_parsed_and_trimmed(self) -> None:
        config = settings(cors_allowed_origins="https://a.com, https://b.com ,")

        assert config.allowed_origins == ("https://a.com", "https://b.com")

    @pytest.mark.parametrize("value", [-0.1, 2.5])
    def test_out_of_range_temperature_is_rejected(self, value: float) -> None:
        with pytest.raises(ValueError, match="llm_temperature"):
            settings(llm_temperature=value)

    def test_is_production(self) -> None:
        assert settings(app_env=Environment.PRODUCTION).is_production
        assert not settings(app_env=Environment.LOCAL).is_production


class TestKnowledgeBaseLoader:
    def test_loads_the_committed_knowledge_base(self) -> None:
        knowledge_base = load_knowledge_base(KB_PATH)

        assert knowledge_base.word_count > 1_000
        assert knowledge_base.has_section("contact_info")
        assert "burj" in knowledge_base.vocabulary

    def test_contact_details_come_from_the_knowledge_base(self) -> None:
        """Not hardcoded in the domain — changing the sales number is a data edit."""
        contact = load_knowledge_base(KB_PATH).contact

        assert contact.is_complete
        assert "@" in contact.email

    def test_a_missing_file_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(KnowledgeBaseError, match="not found"):
            load_knowledge_base(tmp_path / "absent.xml")

    def test_malformed_xml_fails_loudly(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.xml"
        broken.write_text("<knowledge_base><unclosed>", encoding="utf-8")

        with pytest.raises(KnowledgeBaseError, match="not valid XML"):
            load_knowledge_base(broken)

    def test_a_structurally_valid_but_empty_file_fails_loudly(self, tmp_path: Path) -> None:
        """The silent-failure mode a scraper-backed system must never have.

        An empty knowledge base boots fine and answers every question with the
        fallback while every health check stays green.
        """
        empty = tmp_path / "empty.xml"
        empty.write_text("<knowledge_base></knowledge_base>", encoding="utf-8")

        with pytest.raises(KnowledgeBaseError, match="no readable sections"):
            load_knowledge_base(empty)

    def test_attribute_values_are_indexed(self, tmp_path: Path) -> None:
        """Project names live in attributes, not text.

        Dropping them would leave "Burj Qadri" out of the vocabulary Layer 1
        matches against.
        """
        path = tmp_path / "kb.xml"
        path.write_text(
            '<kb><projects><project name="Burj Qadri" status="Completed">'
            "<p>A tower.</p></project></projects></kb>",
            encoding="utf-8",
        )

        assert "qadri" in load_knowledge_base(path).vocabulary


class TestAnthropicAdapter:
    """The adapter that most justifies having a port at all."""

    @pytest.mark.parametrize(
        "model", ["claude-opus-5", "claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7"]
    )
    def test_temperature_is_omitted_for_models_that_reject_it(self, model: str) -> None:
        """Current Claude models return a 400 for `temperature`.

        The domain expresses intent ("be faithful, not creative") as a port
        field; the adapter decides how to honour it per model. Without this,
        flipping LLM_PROVIDER to anthropic would 400 on the first question —
        breaking the exact promise this architecture is built on.
        """
        client = AnthropicClient(api_key="k", model=model, timeout_seconds=5)

        assert client._sends_temperature is False

    @pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-opus-4-6", "claude-sonnet-4-6"])
    def test_temperature_is_sent_to_models_that_accept_it(self, model: str) -> None:
        client = AnthropicClient(api_key="k", model=model, timeout_seconds=5)

        assert client._sends_temperature is True

    async def test_json_mode_declares_the_output_schema(self) -> None:
        client = AnthropicClient(api_key="k", model="claude-opus-5", timeout_seconds=5)
        create = AsyncMock(return_value=_fake_claude_message("{}"))

        with patch.object(client._client.messages, "create", create):
            await client.generate(_request(ResponseFormat.JSON))

        kwargs = create.call_args.kwargs
        assert kwargs["output_config"]["format"]["type"] == "json_schema"
        assert "temperature" not in kwargs, "opus-5 rejects temperature"

    async def test_a_leading_thinking_block_does_not_break_extraction(self) -> None:
        """`content[0].text` is unsafe — thinking blocks lead on current models."""
        client = AnthropicClient(api_key="k", model="claude-opus-5", timeout_seconds=5)
        message = _fake_claude_message("the answer", with_leading_thinking=True)

        with patch.object(client._client.messages, "create", AsyncMock(return_value=message)):
            response = await client.generate(_request())

        assert response.text == "the answer"

    async def test_a_safety_refusal_is_not_a_grounding_fallback(self) -> None:
        """Vendor refusal and our refusal must stay distinguishable in logs."""
        client = AnthropicClient(api_key="k", model="claude-opus-5", timeout_seconds=5)
        message = _fake_claude_message("", stop_reason="refusal")

        with (
            patch.object(client._client.messages, "create", AsyncMock(return_value=message)),
            pytest.raises(LLMContentBlockedError),
        ):
            await client.generate(_request())


class TestGeminiAdapter:
    async def test_roles_are_translated_to_gemini_vocabulary(self) -> None:
        """Gemini calls the assistant "model"; the domain calls it "assistant"."""
        client = GeminiClient(api_key="k", model="gemini-2.0-flash", timeout_seconds=5)
        generate = AsyncMock(return_value=_fake_gemini_response("hi"))

        with patch.object(client._client.aio.models, "generate_content", generate):
            await client.generate(
                LLMRequest(
                    system_prompt="p",
                    messages=(Message.user("q"), Message.assistant("a"), Message.user("q2")),
                )
            )

        roles = [c.role for c in generate.call_args.kwargs["contents"]]
        assert roles == ["user", "model", "user"]

    async def test_json_mode_sets_the_response_mime_type(self) -> None:
        client = GeminiClient(api_key="k", model="gemini-2.0-flash", timeout_seconds=5)
        generate = AsyncMock(return_value=_fake_gemini_response("{}"))

        with patch.object(client._client.aio.models, "generate_content", generate):
            await client.generate(_request(ResponseFormat.JSON))

        assert generate.call_args.kwargs["config"].response_mime_type == "application/json"

    async def test_an_empty_response_is_a_content_block_not_an_answer(self) -> None:
        client = GeminiClient(api_key="k", model="gemini-2.0-flash", timeout_seconds=5)
        blocked = _fake_gemini_response("")

        with (
            patch.object(
                client._client.aio.models, "generate_content", AsyncMock(return_value=blocked)
            ),
            pytest.raises(LLMContentBlockedError),
        ):
            await client.generate(_request())

    async def test_sdk_errors_become_domain_errors(self) -> None:
        """No caller should ever have to write `except genai_errors.APIError`."""
        from google.genai import errors as genai_errors

        client = GeminiClient(api_key="k", model="gemini-2.0-flash", timeout_seconds=5)
        rate_limited = genai_errors.APIError(429, {"message": "quota exceeded"})

        with (
            patch.object(
                client._client.aio.models, "generate_content", AsyncMock(side_effect=rate_limited)
            ),
            pytest.raises(LLMRateLimitError),
        ):
            await client.generate(_request())


class TestCompositionRoot:
    """The claim under test: swapping providers costs exactly one env var."""

    def test_gemini_is_built_for_the_gemini_provider(self) -> None:
        client = build_llm_client(settings(llm_provider=Provider.GEMINI))

        assert isinstance(client, GeminiClient)

    def test_anthropic_is_built_for_the_anthropic_provider(self) -> None:
        client = build_llm_client(settings(llm_provider=Provider.ANTHROPIC))

        assert isinstance(client, AnthropicClient)

    def test_both_satisfy_the_port(self) -> None:
        """Structural typing, verified by mypy where these are annotated."""
        gemini: LLMClient = build_llm_client(settings(llm_provider=Provider.GEMINI))
        claude: LLMClient = build_llm_client(settings(llm_provider=Provider.ANTHROPIC))

        assert callable(gemini.generate)
        assert callable(claude.generate)

    def test_only_the_provider_field_differs(self) -> None:
        """Nothing else in the configuration changes across the swap."""
        gemini = settings(llm_provider=Provider.GEMINI)
        claude = settings(llm_provider=Provider.ANTHROPIC)

        differing = {
            field
            for field in Settings.model_fields
            if getattr(gemini, field) != getattr(claude, field)
        }

        assert differing == {"llm_provider"}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _request(response_format: ResponseFormat = ResponseFormat.TEXT) -> LLMRequest:
    return LLMRequest(
        system_prompt="You are a test.",
        messages=(Message.user("hello"),),
        response_format=response_format,
    )


def _fake_claude_message(
    text: str, *, stop_reason: str = "end_turn", with_leading_thinking: bool = False
) -> MagicMock:
    from anthropic.types import TextBlock

    blocks: list[Any] = []
    if with_leading_thinking:
        thinking = MagicMock()
        thinking.__class__ = type("ThinkingBlock", (), {})
        blocks.append(thinking)
    if text:
        blocks.append(TextBlock(type="text", text=text, citations=None))

    message = MagicMock()
    message.content = blocks
    message.stop_reason = stop_reason
    message.model = "claude-opus-5"
    message.usage.input_tokens = 100
    message.usage.output_tokens = 20
    return message


def _fake_gemini_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.usage_metadata.prompt_token_count = 100
    response.usage_metadata.candidates_token_count = 20
    response.candidates = [MagicMock(finish_reason="STOP")]
    response.prompt_feedback = None
    return response


class TestContainerWiring:
    def test_the_whole_graph_builds(self) -> None:
        """Smoke test for startup.

        Catches wiring mistakes — a missing argument, a renamed field — that
        would otherwise surface as a crash on first boot in production rather
        than on this machine.
        """
        from app.core.container import build_container

        container = build_container(settings(kb_path=KB_PATH))

        assert container.knowledge_base.word_count > 1_000
        assert container.conversation_service is not None
        assert container.settings.llm_provider is Provider.GEMINI

    async def test_the_built_service_refuses_an_off_topic_question(self) -> None:
        """End-to-end through the real container, without touching the network.

        Layer 1 short-circuits before the provider is reached, so this
        exercises the full wiring with no API key required.
        """
        from app.core.container import build_container
        from app.services.conversation_service import Outcome

        container = build_container(settings(kb_path=KB_PATH))

        reply = await container.conversation_service.respond(
            "wiring", "who is the prime minister of India"
        )

        assert reply.outcome is Outcome.BLOCKED_BY_FILTER
