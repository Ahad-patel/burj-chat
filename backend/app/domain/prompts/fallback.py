"""The refusal message, and the single place its wording is defined.

Every guardrail layer converges here. Defining it once matters more than it
looks: Layer 3 instructs the model to emit this exact sentence, and Layers 1 and
4 substitute it directly. If the wording drifted between them, a visitor could
tell which layer refused them — and so could an attacker probing for a bypass.
"""

from __future__ import annotations

from typing import Final

from app.domain.entities.knowledge_base import ContactDetails, KnowledgeBase

_BASE: Final = "I don't have information about that."

_WITH_BOTH: Final = (
    "{base} For help with this, please contact the Burj Constructions team "
    "on {phone} or at {email}."
)
_WITH_ONE: Final = (
    "{base} For help with this, please contact the Burj Constructions team on {detail}."
)
_WITHOUT_CONTACT: Final = (
    "{base} Please contact the Burj Constructions team directly and they will be happy to help."
)


def build_fallback_message(contact: ContactDetails) -> str:
    """Render the refusal, including whatever contact details we actually have.

    Degrades rather than failing: a refusal that names no contact is still far
    better than a crash, or than an invented phone number.
    """
    if contact.is_complete:
        return _WITH_BOTH.format(base=_BASE, phone=contact.phone, email=contact.email)

    if detail := (contact.phone or contact.email):
        return _WITH_ONE.format(base=_BASE, detail=detail)

    return _WITHOUT_CONTACT.format(base=_BASE)


def fallback_for(knowledge_base: KnowledgeBase) -> str:
    """Convenience wrapper — the fallback for a given knowledge base."""
    return build_fallback_message(knowledge_base.contact)
