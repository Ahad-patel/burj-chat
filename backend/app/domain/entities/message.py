"""A single turn in a conversation.

Python note: `@dataclass(frozen=True, slots=True)` gives an immutable value
object — `frozen` blocks attribute assignment after construction (roughly Dart's
`final` fields on a `const` class), and `slots` skips the per-instance `__dict__`
for a smaller, faster object. Immutability matters here because a `Message` is
passed into the guardrails and then into an adapter; nothing downstream should
be able to rewrite what the user actually said.

`__post_init__` runs right after the generated `__init__`, and is where a
stdlib dataclass enforces invariants. Pydantic would do this declaratively, but
the domain layer deliberately has no framework dependencies — see
`tests/architecture/test_layer_boundaries.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from app.domain.errors import InvalidMessageError

#: Longest accepted user message. Bounds prompt-injection payload size and caps
#: input-token spend; a genuine question about a flat never approaches this.
MAX_MESSAGE_LENGTH: Final = 2_000


class Role(StrEnum):
    """Who produced a message.

    Deliberately only two values. There is no `SYSTEM` role: the system prompt
    is built by `domain/prompts/` and travels in `LLMRequest.system_prompt`. If
    a system message could be constructed as an ordinary `Message`, anything
    that appends to a conversation could inject instructions — exactly the
    attack the guardrails exist to stop.
    """

    USER = "user"
    ASSISTANT = "assistant"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class Message:
    """One conversational turn, validated at construction."""

    role: Role
    content: str
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.role, Role):
            raise InvalidMessageError(f"role must be a Role, got {type(self.role).__name__}")

        if not self.content.strip():
            raise InvalidMessageError("message content must not be empty or whitespace")

        if len(self.content) > MAX_MESSAGE_LENGTH:
            raise InvalidMessageError(
                f"message content exceeds {MAX_MESSAGE_LENGTH} characters "
                f"({len(self.content)} given)"
            )

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> Message:
        return cls(role=Role.ASSISTANT, content=content)

    @property
    def is_user(self) -> bool:
        return self.role is Role.USER
