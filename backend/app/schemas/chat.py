"""Wire models for the chat endpoint.

This is the only layer where Pydantic appears. The domain uses stdlib
dataclasses so that "the domain has no framework dependencies" is a fact an
architecture test can enforce, not a slogan.

These models are the trust boundary: everything arriving from the widget is
untrusted until it has been through here.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.entities.message import MAX_MESSAGE_LENGTH

#: Control characters other than tab/newline. Stripped rather than rejected —
#: a stray \x00 from a browser quirk should not cost a visitor their question,
#: but it must never reach the prompt.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_UUID4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE
)


class ChatRequest(BaseModel):
    """One visitor message.

    `conversation_id` is optional: the server mints a UUID4 on the first
    request and the widget echoes it back thereafter. Requiring UUID4 format is
    a deliberate control — there is no authentication on this endpoint, so
    unguessable identifiers are the only thing preventing someone from
    enumerating `1`, `2`, `3` and reading other visitors' conversations.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]
    conversation_id: str | None = None

    @field_validator("message")
    @classmethod
    def _strip_control_characters(cls, value: str) -> str:
        return _CONTROL_CHARS.sub("", value)

    @field_validator("conversation_id")
    @classmethod
    def _must_be_uuid4(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _UUID4.match(value):
            raise ValueError("conversation_id must be a UUID4")
        return value.lower()

    @model_validator(mode="after")
    def _reject_message_that_is_only_control_characters(self) -> Self:
        """Catch input that was non-empty on arrival but empty after stripping.

        Field validators run before this, so `min_length` has already passed on
        the raw value — without this check, "\\x00\\x00" would reach the domain
        and raise there instead of returning a clean 422.
        """
        if not self.message.strip():
            raise ValueError("message must contain readable text")
        return self

    def resolved_conversation_id(self) -> str:
        return self.conversation_id or str(uuid.uuid4())


class ChatResponse(BaseModel):
    """The assistant's reply.

    Deliberately does **not** carry the internal `outcome` or `reason`. Those
    say *which* guardrail refused, and handing that to a caller turns the
    endpoint into an oracle for probing the filter.

    `is_fallback` is safe to expose because it adds nothing an attacker cannot
    already read: the fallback sentence is fixed and self-identifying, so its
    presence is observable from the answer text alone. It exists so the widget
    can style a refusal differently.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    answer: str
    is_fallback: bool


class HealthResponse(BaseModel):
    """Liveness and readiness.

    Detail is withheld in production: model names and section counts are free
    reconnaissance, and the load balancer only needs `status`.
    """

    model_config = ConfigDict(extra="forbid")

    status: str
    knowledge_base_sections: int | None = None
    provider: str | None = None


class ErrorResponse(BaseModel):
    """A client-safe error.

    One flat shape for every failure. Stack traces, exception types, and
    provider messages never appear here — see `api/errors.py`.
    """

    model_config = ConfigDict(extra="forbid")

    detail: str
