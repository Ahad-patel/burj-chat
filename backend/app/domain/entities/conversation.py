"""An ordered, immutable exchange of messages.

`Conversation` is immutable: `append` returns a *new* conversation rather than
mutating in place. That costs a small tuple copy per turn — irrelevant at 40
messages — and buys two things worth more: a conversation handed to a guardrail
cannot be modified behind the caller's back, and the value can be shared across
async tasks without locking.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Final

from app.domain.entities.message import Message, Role
from app.domain.errors import ConversationLimitError

#: Ceiling on turns retained per conversation. Bounds prompt size (and so cost)
#: and stops a single session growing without limit in the in-memory store.
MAX_MESSAGES: Final = 40

#: How many recent turns accompany a request to the model. The knowledge base
#: dominates the prompt; history only needs to be long enough to resolve
#: follow-ups like "and the price?".
DEFAULT_HISTORY_TURNS: Final = 8


@dataclass(frozen=True, slots=True)
class Conversation:
    """A session's message history."""

    id: str
    messages: tuple[Message, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("conversation id must not be empty")
        if len(self.messages) > MAX_MESSAGES:
            raise ConversationLimitError(
                f"conversation exceeds {MAX_MESSAGES} messages ({len(self.messages)} given)"
            )

    def append(self, message: Message) -> Conversation:
        """Return a new conversation with `message` added.

        Python note: `dataclasses.replace` copies a frozen dataclass with some
        fields changed — the standard way to "modify" an immutable value.
        """
        if len(self.messages) >= MAX_MESSAGES:
            raise ConversationLimitError(
                f"cannot append: conversation already holds {MAX_MESSAGES} messages"
            )
        return replace(self, messages=(*self.messages, message))

    def recent(self, turns: int = DEFAULT_HISTORY_TURNS) -> tuple[Message, ...]:
        """Return the last `turns` messages, oldest first."""
        if turns <= 0:
            return ()
        return self.messages[-turns:]

    @property
    def is_empty(self) -> bool:
        return not self.messages

    @property
    def last_user_message(self) -> Message | None:
        return self._last_with_role(Role.USER)

    @property
    def last_assistant_message(self) -> Message | None:
        return self._last_with_role(Role.ASSISTANT)

    @property
    def has_prior_exchange(self) -> bool:
        """True once the assistant has replied at least once.

        Layer 1 consults this: a terse follow-up like "and the price?" carries
        no topic words of its own and is only interpretable — and only safe to
        pass through — when there is a previous exchange to anchor it.
        """
        return self.last_assistant_message is not None

    def _last_with_role(self, role: Role) -> Message | None:
        for message in reversed(self.messages):
            if message.role is role:
                return message
        return None
