"""The single source of truth the assistant is allowed to draw on.

This entity holds *already-parsed* content. XML parsing lives in
`infrastructure/kb/`, because `defusedxml` is a third-party package and the
domain layer takes no third-party dependencies. The loader turns a file into
sections; this class turns sections into the derived indexes the guardrails
need.

Two of those indexes do real work:

* `vocabulary` — every meaningful word in the knowledge base. Layer 1 scores a
  question against it to decide whether it is plausibly about this company.
* `numbers` — every numeric token. Layer 4 checks that figures in a generated
  answer actually appear here, which is what catches an invented price,
  possession date, or RERA registration number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from app.domain.errors import KnowledgeBaseError

#: Words too common to signal anything about topic. This list is load-bearing:
#: Layer 1 falls back to matching a question against the knowledge base's own
#: vocabulary, so leaving ordinary function words in would make almost any
#: English sentence look relevant and quietly disable the filter.
#:
#: Only function words belong here. Short domain terms — "bhk", "emi", "gym",
#: "buy", "rera" — must survive, which is why this is a curated list rather
#: than a minimum-length rule.
_STOPWORDS: Final = frozenset(
    {
        # Common short function words
        "the",
        "and",
        "for",
        "are",
        "was",
        "you",
        "our",
        "not",
        "can",
        "has",
        "had",
        "its",
        "who",
        "why",
        "how",
        "all",
        "but",
        "his",
        "her",
        "she",
        "him",
        "may",
        "out",
        "get",
        "got",
        "did",
        "does",
        "too",
        "yet",
        "via",
        "per",
        "off",
        "own",
        "one",
        "two",
        "way",
        "day",
        "now",
        "new",
        "use",
        "let",
        "say",
        "see",
        "put",
        "take",
        "give",
        "know",
        "want",
        "tell",
        "will",
        "shall",
        "could",
        "might",
        "must",
        "would",
        "been",
        "were",
        # Longer function words
        "about",
        "above",
        "after",
        "again",
        "against",
        "also",
        "another",
        "any",
        "because",
        "before",
        "being",
        "below",
        "between",
        "both",
        "came",
        "come",
        "doing",
        "done",
        "down",
        "during",
        "each",
        "even",
        "ever",
        "every",
        "from",
        "further",
        "have",
        "having",
        "here",
        "hers",
        "herself",
        "himself",
        "into",
        "itself",
        "just",
        "like",
        "made",
        "make",
        "many",
        "more",
        "most",
        "much",
        "myself",
        "need",
        "only",
        "other",
        "ours",
        "ourselves",
        "over",
        "same",
        "should",
        "since",
        "some",
        "such",
        "than",
        "that",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "until",
        "upon",
        "very",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "your",
        "yours",
        "yourself",
    }
)

_WORD_PATTERN: Final = re.compile(r"[a-z][a-z'-]{2,}")

#: Numbers as they appear in prose: "1.75", "400,010", "G+32" -> "32".
_NUMBER_PATTERN: Final = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Shortest token counted as vocabulary. Below this, matches are mostly noise.
_MIN_TERM_LENGTH: Final = 3


@dataclass(frozen=True, slots=True)
class KnowledgeSection:
    """One labelled region of the knowledge base, e.g. `completed_projects`."""

    name: str
    text: str


@dataclass(frozen=True, slots=True)
class ContactDetails:
    """Where to send a visitor whose question we cannot answer.

    Carried on the knowledge base rather than hardcoded in the fallback string
    so that changing the sales number is a data edit in `overrides.yaml`, not a
    code change in the domain layer.
    """

    phone: str = ""
    email: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.phone and self.email)


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    """Parsed knowledge base plus the indexes the guardrails run against."""

    document: str
    sections: tuple[KnowledgeSection, ...]
    contact: ContactDetails = field(default_factory=ContactDetails)
    section_names: frozenset[str] = field(default_factory=frozenset)
    vocabulary: frozenset[str] = field(default_factory=frozenset)
    numbers: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.document.strip():
            raise KnowledgeBaseError("knowledge base document is empty")
        if not self.sections:
            raise KnowledgeBaseError("knowledge base contains no sections")

    @classmethod
    def build(
        cls,
        *,
        document: str,
        sections: tuple[KnowledgeSection, ...],
        contact: ContactDetails | None = None,
    ) -> KnowledgeBase:
        """Construct a knowledge base, deriving the guardrail indexes.

        Python note: a `classmethod` used as an alternative constructor is the
        idiomatic replacement for overloaded constructors, which Python lacks.
        """
        corpus = " ".join(section.text for section in sections)

        return cls(
            document=document,
            sections=sections,
            contact=contact or ContactDetails(),
            section_names=frozenset(section.name for section in sections),
            vocabulary=extract_terms(corpus),
            numbers=extract_numbers(corpus),
        )

    def has_section(self, name: str) -> bool:
        return name in self.section_names

    @property
    def word_count(self) -> int:
        return sum(len(section.text.split()) for section in self.sections)


def extract_terms(text: str) -> frozenset[str]:
    """Return the meaningful lowercase words in `text`.

    Shared by the knowledge base and Layer 1 so a question and the corpus are
    tokenised identically — if they diverged, every affinity score would be
    quietly wrong.
    """
    return frozenset(
        word
        for word in _WORD_PATTERN.findall(text.casefold())
        if len(word) >= _MIN_TERM_LENGTH and word not in _STOPWORDS
    )


def extract_numbers(text: str) -> frozenset[str]:
    """Return every numeric token in `text`, normalised for comparison.

    Commas are stripped and trailing zeros after a decimal point are ignored so
    that "1,00,000" and "100000", or "1.75" and "1.750", compare equal. Without
    that, Layer 4 would reject correct answers over pure formatting.
    """
    return frozenset(normalise_number(match) for match in _NUMBER_PATTERN.findall(text))


def normalise_number(raw: str) -> str:
    """Reduce a numeric token to a canonical comparable form."""
    cleaned = raw.replace(",", "")
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned or "0"
