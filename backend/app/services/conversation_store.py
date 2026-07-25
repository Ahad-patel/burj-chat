"""In-memory conversation storage with a TTL.

**There is deliberately no database.** Conversations exist only to resolve
follow-up questions ("and the price?") within a single visit; nothing here is
worth surviving a restart. A datastore would add an operational dependency, a
backup story, and a retention policy for what is effectively PII — to hold
data whose useful life is measured in minutes.

The consequence is stated plainly rather than hidden: conversations are lost on
restart, and a multi-instance deployment needs sticky sessions or Redis. At the
traffic a single construction company's website sees, one instance is the right
answer, and this class is small enough to swap when that stops being true.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.domain.entities.conversation import Conversation
from app.domain.errors import ConversationLimitError


@dataclass(slots=True)
class _Entry:
    conversation: Conversation
    expires_at: datetime


@dataclass(slots=True)
class ConversationStore:
    """A TTL-bounded map of conversation id to conversation.

    Guarded by an `asyncio.Lock`: FastAPI serves requests concurrently on one
    event loop, so two messages from the same session can interleave. Without
    the lock, a read-modify-write would drop a turn.
    """

    ttl_minutes: int = 30
    max_messages: int = 40
    _entries: dict[str, _Entry] = field(default_factory=dict, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def get(self, conversation_id: str) -> Conversation:
        """Return the stored conversation, or a fresh empty one."""
        async with self._lock:
            self._evict_expired()
            entry = self._entries.get(conversation_id)
            return entry.conversation if entry else Conversation(id=conversation_id)

    async def save(self, conversation: Conversation) -> None:
        """Store a conversation and refresh its expiry."""
        async with self._lock:
            self._evict_expired()
            self._entries[conversation.id] = _Entry(
                conversation=conversation,
                expires_at=datetime.now(UTC) + timedelta(minutes=self.ttl_minutes),
            )

    async def drop(self, conversation_id: str) -> None:
        async with self._lock:
            self._entries.pop(conversation_id, None)

    async def size(self) -> int:
        async with self._lock:
            self._evict_expired()
            return len(self._entries)

    def trim(self, conversation: Conversation) -> Conversation:
        """Drop the oldest turns if the conversation is at its ceiling.

        Without this a long session would raise `ConversationLimitError` and
        the visitor would simply stop getting answers. Sliding the window keeps
        the exchange alive; the knowledge base — not the history — is what the
        model actually answers from, so losing the earliest turns costs little.
        """
        if len(conversation.messages) < self.max_messages:
            return conversation

        keep = self.max_messages - 1
        return Conversation(id=conversation.id, messages=conversation.messages[-keep:])

    def _evict_expired(self) -> None:
        """Drop timed-out conversations. Caller must hold the lock."""
        now = datetime.now(UTC)
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            del self._entries[key]


__all__ = ["ConversationLimitError", "ConversationStore"]
