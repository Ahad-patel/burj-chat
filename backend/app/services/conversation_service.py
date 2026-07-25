"""The use case: turn a visitor's message into a grounded answer, or the fallback.

This is where the four guardrail layers are actually sequenced:

    Layer 1  relevance pre-filter  ──reject──▶ fallback  (no model call, no cost)
    Layer 2  knowledge base as delimited XML sections
    Layer 3  strict system prompt + JSON output contract
    Layer 4  response validation    ──reject──▶ fallback

Two properties this file is responsible for, both load-bearing:

**The model is never called for a message Layer 1 rejects.** That is not just a
cost optimisation — an attack that never reaches the model cannot talk it into
anything.

**Every failure path ends at the same sentence.** A guardrail rejection, an
unparseable response, a provider outage, and a rate limit all produce the exact
fallback. If they differed, a visitor — or an attacker probing the filter —
could tell which layer stopped them and map the system from the outside.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter

from app.core.logging import get_logger
from app.domain.entities.conversation import Conversation
from app.domain.entities.knowledge_base import KnowledgeBase
from app.domain.entities.message import Message
from app.domain.errors import InvalidMessageError
from app.domain.guardrails.relevance import RelevanceFilter
from app.domain.guardrails.validator import ResponseValidator
from app.domain.ports.errors import LLMError
from app.domain.ports.llm_client import (
    LLMClient,
    LLMRequest,
    ResponseFormat,
)
from app.domain.prompts.fallback import fallback_for
from app.domain.prompts.system_prompt import build_system_prompt
from app.services.conversation_store import ConversationStore

logger = get_logger(__name__)


class Outcome(StrEnum):
    """How a reply was produced. Logged for tuning; never shown to a visitor."""

    ANSWERED = "answered"
    BLOCKED_BY_FILTER = "blocked_by_filter"
    FAILED_VALIDATION = "failed_validation"
    PROVIDER_ERROR = "provider_error"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True, slots=True)
class Reply:
    """What the API layer returns to the widget."""

    conversation_id: str
    answer: str
    outcome: Outcome
    #: Machine-readable detail for logs and tests. Never serialised to a client
    #: — it would tell an attacker exactly which rule stopped them.
    reason: str = ""

    @property
    def is_fallback(self) -> bool:
        return self.outcome is not Outcome.ANSWERED


class ConversationService:
    """Orchestrates the guardrail chain for one visitor message.

    Depends on the `LLMClient` *port*, so it is identical under either
    provider and fully testable with an in-memory fake.
    """

    def __init__(
        self,
        *,
        llm: LLMClient,
        knowledge_base: KnowledgeBase,
        relevance: RelevanceFilter,
        validator: ResponseValidator,
        store: ConversationStore,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> None:
        self._llm = llm
        self._knowledge_base = knowledge_base
        self._relevance = relevance
        self._validator = validator
        self._store = store
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature

        # Built once: the knowledge base is immutable for the process lifetime,
        # so rebuilding this per request would burn CPU and — because the bytes
        # would be identical anyway — buy nothing. A stable prefix is also what
        # makes provider-side prompt caching possible.
        self._system_prompt = build_system_prompt(knowledge_base)
        self._fallback = fallback_for(knowledge_base)

    async def respond(self, conversation_id: str, message: str) -> Reply:
        """Produce a grounded answer for `message`, or the fallback."""
        started = perf_counter()

        try:
            user_message = Message.user(message)
        except InvalidMessageError as error:
            # Empty or oversized input. The API layer validates too; this is the
            # domain refusing to build a nonsensical entity regardless of caller.
            return self._refuse(
                conversation_id, Outcome.INVALID_INPUT, str(error), started, chars=len(message)
            )

        conversation = await self._store.get(conversation_id)

        # --- Layer 1 -----------------------------------------------------------
        verdict = self._relevance.check(user_message.content, conversation)
        if not verdict.allowed:
            # Recorded so the *next* turn's follow-up detection sees an honest
            # history, and so a visitor cannot retry the same blocked question
            # into a "fresh" conversation.
            await self._remember(conversation, user_message, self._fallback)
            return self._refuse(
                conversation_id,
                Outcome.BLOCKED_BY_FILTER,
                verdict.reason.value,
                started,
                chars=len(user_message.content),
            )

        # --- Layers 2 and 3 ----------------------------------------------------
        request = LLMRequest(
            system_prompt=self._system_prompt,
            messages=(*conversation.recent(), user_message),
            max_output_tokens=self._max_output_tokens,
            temperature=self._temperature,
            response_format=ResponseFormat.JSON,
        )

        try:
            response = await self._llm.generate(request)
        except LLMError as error:
            # One family for every provider — this clause behaves identically
            # whether Gemini or Claude is configured.
            logger.warning(
                "llm_call_failed",
                conversation_id=conversation_id,
                error_type=type(error).__name__,
                elapsed_ms=_elapsed_ms(started),
            )
            await self._remember(conversation, user_message, self._fallback)
            return self._refuse(
                conversation_id, Outcome.PROVIDER_ERROR, type(error).__name__, started
            )

        # --- Layer 4 -----------------------------------------------------------
        result = self._validator.validate(response.text)
        if not result.is_valid:
            logger.warning(
                "response_failed_validation",
                conversation_id=conversation_id,
                failure=result.failure.value if result.failure else "unknown",
                detail=result.detail,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            await self._remember(conversation, user_message, self._fallback)
            return self._refuse(
                conversation_id,
                Outcome.FAILED_VALIDATION,
                result.failure.value if result.failure else "unknown",
                started,
            )

        await self._remember(conversation, user_message, result.answer)

        logger.info(
            "answered",
            conversation_id=conversation_id,
            allow_reason=verdict.reason.value,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            answer_chars=len(result.answer),
            elapsed_ms=_elapsed_ms(started),
        )

        return Reply(
            conversation_id=conversation_id,
            answer=result.answer,
            outcome=Outcome.ANSWERED,
        )

    async def _remember(
        self, conversation: Conversation, user_message: Message, answer: str
    ) -> None:
        """Append the exchange and persist it, trimming if at the ceiling.

        Trimmed before each append rather than once, because two messages are
        added per turn — trimming only at the start would let the second append
        cross the ceiling and raise.
        """
        updated = self._store.trim(conversation).append(user_message)
        updated = self._store.trim(updated).append(Message.assistant(answer))
        await self._store.save(updated)

    def _refuse(
        self,
        conversation_id: str,
        outcome: Outcome,
        reason: str,
        started: float,
        **extra: object,
    ) -> Reply:
        """Return the fallback. Every rejection path funnels through here.

        One construction site for the refusal means the wording cannot drift
        between layers — which is what stops the response itself from leaking
        which guardrail fired.
        """
        logger.info(
            "refused",
            conversation_id=conversation_id,
            outcome=outcome.value,
            reason=reason,
            elapsed_ms=_elapsed_ms(started),
            **extra,
        )
        return Reply(
            conversation_id=conversation_id,
            answer=self._fallback,
            outcome=outcome,
            reason=reason,
        )


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
