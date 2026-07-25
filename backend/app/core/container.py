"""Composition root — the only place that knows both providers exist.

Everything downstream receives an `LLMClient` and cannot tell which
implementation it got. That is what makes the promise in the README literally
true: `grep -ri gemini backend/app` outside `infrastructure/llm/` and this file
returns nothing, and an architecture test fails the build if that changes.

Python note: this is dependency injection without a DI framework. "Injection"
here just means collaborators are passed into `__init__` rather than
constructed inside it — which is also what lets the whole service be tested
against a fake client with no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config import Provider, Settings, get_settings
from app.core.logging import get_logger
from app.domain.entities.knowledge_base import KnowledgeBase
from app.domain.guardrails.relevance import RelevanceFilter
from app.domain.guardrails.validator import ResponseValidator
from app.domain.ports.llm_client import LLMClient
from app.infrastructure.kb.loader import load_knowledge_base
from app.infrastructure.llm.anthropic_client import AnthropicClient
from app.infrastructure.llm.gemini_client import GeminiClient
from app.services.conversation_service import ConversationService
from app.services.conversation_store import ConversationStore

logger = get_logger(__name__)


def build_llm_client(settings: Settings) -> LLMClient:
    """Construct the provider named by `LLM_PROVIDER`.

    The return type is the port, not the concrete class — so a caller that
    tried to reach for a Gemini-specific method would fail type checking.
    """
    match settings.llm_provider:
        case Provider.GEMINI:
            client: LLMClient = GeminiClient(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                timeout_seconds=settings.llm_timeout_seconds,
            )
            model = settings.gemini_model
        case Provider.ANTHROPIC:
            client = AnthropicClient(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
                timeout_seconds=settings.llm_timeout_seconds,
            )
            model = settings.anthropic_model

    logger.info("llm_client_built", provider=settings.llm_provider.value, model=model)
    return client


@dataclass(frozen=True, slots=True)
class Container:
    """Everything the API layer needs, wired once at startup."""

    settings: Settings
    knowledge_base: KnowledgeBase
    conversation_service: ConversationService


def build_container(settings: Settings | None = None) -> Container:
    """Wire the application graph.

    Called once on startup. The knowledge base is parsed here rather than per
    request — it is a ~21KB file that changes when the client's website
    changes, so re-reading it per visitor question would buy nothing.
    """
    settings = settings or get_settings()
    knowledge_base = load_knowledge_base(settings.kb_path)

    service = ConversationService(
        llm=build_llm_client(settings),
        knowledge_base=knowledge_base,
        relevance=RelevanceFilter(knowledge_base),
        validator=ResponseValidator(knowledge_base),
        store=ConversationStore(
            ttl_minutes=settings.conversation_ttl_minutes,
            max_messages=settings.max_messages_per_conversation,
        ),
        max_output_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
    )

    return Container(
        settings=settings,
        knowledge_base=knowledge_base,
        conversation_service=service,
    )


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Process-wide container, built on first use."""
    return build_container()
