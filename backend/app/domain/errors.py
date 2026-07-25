"""Domain error hierarchy.

Every exception the domain raises descends from `DomainError`, so outer layers
can catch the whole family without importing individual error types or
accidentally swallowing a genuine bug (a `KeyError`, say) alongside a business
rule violation.

Python note: exceptions are classes, and `raise X("msg")` instantiates one.
Subclassing is how you build a catchable hierarchy — `except DomainError` will
catch any subclass listed here.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every business-rule violation in the domain layer."""


class InvalidMessageError(DomainError):
    """A message failed its invariants — empty, too long, or wrong type."""


class ConversationLimitError(DomainError):
    """A conversation exceeded its configured message ceiling."""


class KnowledgeBaseError(DomainError):
    """The knowledge base is missing, empty, or structurally unusable."""
