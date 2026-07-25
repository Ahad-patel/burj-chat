"""Layer 4 — verify a generated answer is actually grounded before returning it.

The design question here is how to check grounding cheaply. Three options were
considered:

* **A second LLM call as judge.** Doubles cost and latency on every message, and
  the judge is exactly as jailbreakable as the model it judges. Rejected.
* **Pure entity/overlap heuristics.** Too brittle — any correct paraphrase gets
  rejected, which trains the client to distrust the guardrail.
* **A structured-output contract, checked deterministically.** Chosen.

The model returns `{"answer", "grounded", "sections_used"}` and this module
checks it without another model call.

**Being honest about the limit.** `grounded` is the model's self-report, and a
successfully jailbroken model will happily report `true`. It is the *weakest*
signal here. The checks that hold independently of the model's cooperation are
the ones that matter:

* `sections_used` must name sections that genuinely exist in the knowledge base
* every multi-digit number in the answer must appear in the knowledge base
* no competitor may be named in the answer

The numeric check is the sharpest tool in this file. Prices, possession dates,
and RERA registration numbers are exactly the fabrications that would damage the
client, and every one of them is a multi-digit number that will not be found in
the corpus.

This layer **fails closed**: anything it cannot parse or verify becomes the
fallback. A refusal costs a visitor one click to the phone number; a confidently
invented price costs the client a legal problem.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from app.domain.entities.knowledge_base import KnowledgeBase, normalise_number
from app.domain.guardrails.lexicon import COMPETITOR_TERMS, OFF_DOMAIN_ANSWER_PATTERNS

#: Numbers with fewer than this many digits are exempt from the grounding check.
#: The model legitimately produces small counts by reasoning over the knowledge
#: base ("there are 3 completed projects") that appear nowhere in the text.
#: Every dangerous fabrication — a price, a year, a registration number — has at
#: least two digits, so the exemption costs nothing that matters.
_MIN_CHECKED_DIGITS: Final = 2

_NUMBER_PATTERN: Final = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD_SPLIT: Final = re.compile(r"[^a-z0-9']+")
_JSON_FENCE: Final = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_JSON_OBJECT: Final = re.compile(r"\{.*\}", re.S)


class ValidationFailure(StrEnum):
    """Why an answer was rejected. Logged for tuning, never shown to a visitor."""

    UNPARSEABLE = "unparseable_response"
    EMPTY_ANSWER = "empty_answer"
    MODEL_REPORTED_UNGROUNDED = "model_reported_ungrounded"
    NO_SECTIONS_CITED = "no_sections_cited"
    UNKNOWN_SECTION_CITED = "unknown_section_cited"
    UNGROUNDED_NUMBER = "ungrounded_number"
    COMPETITOR_MENTIONED = "competitor_mentioned"
    OFF_DOMAIN_CONTENT = "off_domain_content"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of validating one model response."""

    is_valid: bool
    answer: str = ""
    failure: ValidationFailure | None = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.is_valid


class ResponseValidator:
    """Checks a model response against the knowledge base it was given."""

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self._knowledge_base = knowledge_base

    def validate(self, raw_response: str) -> ValidationResult:
        """Validate a structured response, failing closed on any doubt."""
        payload = _parse_json_object(raw_response)
        if payload is None:
            return _reject(ValidationFailure.UNPARSEABLE, "response was not a JSON object")

        answer = str(payload.get("answer", "")).strip()
        if not answer:
            return _reject(ValidationFailure.EMPTY_ANSWER, "answer field was empty")

        if payload.get("grounded") is not True:
            return _reject(
                ValidationFailure.MODEL_REPORTED_UNGROUNDED,
                "model set grounded=false",
            )

        sections = _string_list(payload.get("sections_used"))
        if not sections:
            return _reject(ValidationFailure.NO_SECTIONS_CITED, "sections_used was empty")

        unknown = [name for name in sections if not self._knowledge_base.has_section(name)]
        if unknown:
            return _reject(
                ValidationFailure.UNKNOWN_SECTION_CITED,
                f"cited non-existent sections: {sorted(unknown)}",
            )

        # Competitors are checked before figures because several competitor
        # names contain digits ("99acres"). Both checks reject the answer either
        # way, but the recorded reason drives tuning — and a competitor mention
        # filed under "ungrounded number" would send the next reader the wrong
        # way entirely.
        if named := _competitors_in(answer):
            return _reject(
                ValidationFailure.COMPETITOR_MENTIONED,
                f"answer names competitors: {sorted(named)}",
            )

        if any(pattern.search(answer) for pattern in OFF_DOMAIN_ANSWER_PATTERNS):
            return _reject(
                ValidationFailure.OFF_DOMAIN_CONTENT,
                "answer contains off-domain content",
            )

        if ungrounded := self._ungrounded_numbers(answer):
            return _reject(
                ValidationFailure.UNGROUNDED_NUMBER,
                f"answer contains figures absent from the knowledge base: {sorted(ungrounded)}",
            )

        return ValidationResult(is_valid=True, answer=answer)

    def _ungrounded_numbers(self, answer: str) -> set[str]:
        """Return figures in `answer` that do not appear in the knowledge base."""
        found: set[str] = set()

        for raw in _NUMBER_PATTERN.findall(answer):
            digits = re.sub(r"\D", "", raw)
            if len(digits) < _MIN_CHECKED_DIGITS:
                continue
            if normalise_number(raw) not in self._knowledge_base.numbers:
                found.add(raw)

        return found


def _reject(failure: ValidationFailure, detail: str) -> ValidationResult:
    return ValidationResult(is_valid=False, failure=failure, detail=detail)


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    """Extract a JSON object from a model response.

    Tolerates the two wrappers models add unprompted — markdown fences and
    surrounding prose — because rejecting those would mean refusing correct
    answers over formatting. It does not tolerate anything it cannot parse into
    an object: that is the fail-closed path.
    """
    candidates = [raw.strip()]

    if fenced := _JSON_FENCE.search(raw):
        candidates.insert(0, fenced.group(1))
    if embedded := _JSON_OBJECT.search(raw):
        candidates.append(embedded.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _string_list(value: Any) -> list[str]:
    """Coerce `sections_used` to a list of non-empty strings.

    Models occasionally return a bare string instead of a list; accepting that
    is a formatting concession, not a grounding one — the names are still
    checked against the real knowledge base.
    """
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _competitors_in(answer: str) -> set[str]:
    lowered = answer.casefold()
    tokens = _tokens(lowered)

    return {
        term
        for term in COMPETITOR_TERMS
        if (term in lowered if " " in term or "." in term else term in tokens)
    }


def _tokens(lowered: str) -> set[str]:
    """Split into comparable tokens, with possessives normalised.

    Without stripping the possessive, "Lodha's" tokenises to "lodha's" and
    never matches the competitor list — so "how do your flats compare to
    Lodha's?" walked straight through. Apostrophes are kept in the split so
    contractions stay whole, then removed from the tail.
    """
    words = {word for word in _WORD_SPLIT.split(lowered) if word}
    return words | {word.removesuffix("'s").removesuffix("s'") for word in words}
