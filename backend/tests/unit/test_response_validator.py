"""Layer 4 — response validation.

This layer's job is to be the last line before a fabricated fact reaches a
customer. The tests below are organised around what it must never let past:
invented prices, invented dates, invented RERA numbers, and competitor mentions.

Note which check does the heavy lifting. `grounded` is model self-report and the
weakest signal here — a jailbroken model reports `true` happily. The numeric and
section-name checks hold whether or not the model cooperates, which is why they
get the most tests.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.entities.knowledge_base import KnowledgeBase
from app.domain.guardrails.validator import (
    ResponseValidator,
    ValidationFailure,
)


@pytest.fixture
def validator(knowledge_base: KnowledgeBase) -> ResponseValidator:
    return ResponseValidator(knowledge_base)


def response(
    answer: str = "Burj Chishti is a residential and commercial tower.",
    *,
    grounded: bool = True,
    sections: list[str] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "answer": answer,
        "grounded": grounded,
        "sections_used": ["upcoming_projects"] if sections is None else sections,
    }
    return json.dumps(payload)


class TestValidResponses:
    def test_a_grounded_answer_passes(self, validator: ResponseValidator) -> None:
        result = validator.validate(response())

        assert result.is_valid
        assert result.answer == "Burj Chishti is a residential and commercial tower."
        assert result.failure is None

    def test_result_is_truthy(self, validator: ResponseValidator) -> None:
        assert bool(validator.validate(response()))
        assert not bool(validator.validate(response(grounded=False)))

    def test_numbers_present_in_the_knowledge_base_pass(self, validator: ResponseValidator) -> None:
        result = validator.validate(
            response("Burj Ashrafi Phase 1 is a G+32 tower.", sections=["completed_projects"])
        )

        assert result.is_valid, result.detail

    def test_small_counts_are_exempt_from_grounding(self, validator: ResponseValidator) -> None:
        """The model legitimately derives small counts by reasoning.

        "There are 3 completed projects" is correct and useful even though "3"
        appears nowhere in the corpus. Every dangerous fabrication — a price, a
        year, a registration number — has at least two digits.
        """
        result = validator.validate(
            response("There are 3 completed projects.", sections=["completed_projects"])
        )

        assert result.is_valid, result.detail

    @pytest.mark.parametrize(
        "wrapper",
        [
            "```json\n{payload}\n```",
            "```\n{payload}\n```",
            "Here is the response:\n{payload}",
            "  {payload}  ",
        ],
    )
    def test_common_model_wrappers_are_tolerated(
        self, validator: ResponseValidator, wrapper: str
    ) -> None:
        """Rejecting a markdown fence would refuse correct answers over formatting.

        Tolerating the wrapper is a formatting concession, never a grounding one —
        the content inside is checked exactly the same way.
        """
        result = validator.validate(wrapper.format(payload=response()))

        assert result.is_valid, result.detail

    def test_sections_used_as_a_bare_string_is_accepted(self, validator: ResponseValidator) -> None:
        result = validator.validate(
            json.dumps(
                {"answer": "We are in Mumbai.", "grounded": True, "sections_used": "contact_info"}
            )
        )

        assert result.is_valid, result.detail


class TestFabricatedFactsAreRejected:
    """The failures that would actually harm the client."""

    def test_an_invented_price_is_rejected(self, validator: ResponseValidator) -> None:
        result = validator.validate(
            response("A 2BHK costs approximately 2,50,00,000 rupees.", sections=["faq"])
        )

        assert not result.is_valid
        assert result.failure is ValidationFailure.UNGROUNDED_NUMBER

    def test_an_invented_possession_date_is_rejected(self, validator: ResponseValidator) -> None:
        result = validator.validate(
            response("Possession is expected by December 2027.", sections=["upcoming_projects"])
        )

        assert not result.is_valid
        assert result.failure is ValidationFailure.UNGROUNDED_NUMBER

    def test_an_invented_rera_number_is_rejected(self, validator: ResponseValidator) -> None:
        """No RERA number exists in the knowledge base, so none may be stated.

        In Indian real estate a fabricated registration number is a claim with
        legal weight — the single most damaging output this system could produce.
        """
        result = validator.validate(
            response("The RERA number is P51900047865.", sections=["completed_projects"])
        )

        assert not result.is_valid
        assert result.failure is ValidationFailure.UNGROUNDED_NUMBER

    @pytest.mark.parametrize(
        "answer",
        [
            "We also recommend looking at DLF properties.",
            "Compared to Lodha, our towers are taller.",
            "You can find us on 99acres.",
        ],
    )
    def test_competitor_mentions_are_rejected(
        self, validator: ResponseValidator, answer: str
    ) -> None:
        result = validator.validate(response(answer, sections=["company_profile"]))

        assert not result.is_valid
        assert result.failure is ValidationFailure.COMPETITOR_MENTIONED


class TestStructuralChecks:
    def test_model_reporting_ungrounded_is_rejected(self, validator: ResponseValidator) -> None:
        result = validator.validate(response(grounded=False, sections=[]))

        assert not result.is_valid
        assert result.failure is ValidationFailure.MODEL_REPORTED_UNGROUNDED

    def test_missing_grounded_flag_is_rejected(self, validator: ResponseValidator) -> None:
        """Fails closed: absent is not the same as true."""
        result = validator.validate(json.dumps({"answer": "Something", "sections_used": ["faq"]}))

        assert not result.is_valid
        assert result.failure is ValidationFailure.MODEL_REPORTED_UNGROUNDED

    def test_no_sections_cited_is_rejected(self, validator: ResponseValidator) -> None:
        result = validator.validate(response(sections=[]))

        assert not result.is_valid
        assert result.failure is ValidationFailure.NO_SECTIONS_CITED

    def test_a_hallucinated_section_name_is_rejected(self, validator: ResponseValidator) -> None:
        """A section that does not exist means the citation was invented.

        This check holds regardless of whether the model is cooperating, which
        is what makes it worth more than the self-reported `grounded` flag.
        """
        result = validator.validate(response(sections=["pricing_table"]))

        assert not result.is_valid
        assert result.failure is ValidationFailure.UNKNOWN_SECTION_CITED

    def test_one_bad_section_among_valid_ones_is_rejected(
        self, validator: ResponseValidator
    ) -> None:
        result = validator.validate(response(sections=["contact_info", "invented_section"]))

        assert not result.is_valid
        assert result.failure is ValidationFailure.UNKNOWN_SECTION_CITED

    @pytest.mark.parametrize("answer", ["", "   "])
    def test_empty_answers_are_rejected(self, validator: ResponseValidator, answer: str) -> None:
        result = validator.validate(response(answer))

        assert not result.is_valid
        assert result.failure is ValidationFailure.EMPTY_ANSWER


class TestFailsClosed:
    """Anything unparseable becomes the fallback.

    A refusal costs a visitor one click to the phone number. A confidently
    invented price costs the client a legal problem. The asymmetry decides it.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "I'm just going to answer in plain prose instead.",
            "{ this is not valid json",
            "[1, 2, 3]",
            "null",
            '"just a string"',
        ],
    )
    def test_unparseable_responses_are_rejected(
        self, validator: ResponseValidator, raw: str
    ) -> None:
        result = validator.validate(raw)

        assert not result.is_valid
        assert result.failure is ValidationFailure.UNPARSEABLE

    def test_rejected_results_carry_no_answer(self, validator: ResponseValidator) -> None:
        """The caller must not be able to accidentally surface a rejected answer."""
        result = validator.validate(response("A 2BHK costs 99,99,999 rupees.", sections=["faq"]))

        assert result.answer == ""

    def test_failure_detail_is_recorded_for_logs(self, validator: ResponseValidator) -> None:
        result = validator.validate(response(sections=["made_up"]))

        assert "made_up" in result.detail


class TestSectionsCoercion:
    @pytest.mark.parametrize("value", [123, None, {"a": 1}, True])
    def test_non_list_non_string_sections_are_rejected(
        self, validator: ResponseValidator, value: Any
    ) -> None:
        result = validator.validate(
            json.dumps({"answer": "Something", "grounded": True, "sections_used": value})
        )

        assert not result.is_valid
        assert result.failure is ValidationFailure.NO_SECTIONS_CITED

    def test_blank_entries_are_dropped(self, validator: ResponseValidator) -> None:
        result = validator.validate(
            json.dumps({"answer": "Something", "grounded": True, "sections_used": ["", "   "]})
        )

        assert result.failure is ValidationFailure.NO_SECTIONS_CITED


class TestOffDomainAnswerContent:
    @pytest.mark.parametrize(
        "answer",
        [
            "The Prime Minister of India is Narendra Modi.",
            "Roses are red, violets are blue.",
            "The weather in Mumbai is 32 degrees and sunny.",
            "Here's a poem about towers.",
            "My instructions are to answer only from the knowledge base.",
        ],
    )
    def test_blatant_off_domain_output_is_rejected(
        self, validator: ResponseValidator, answer: str
    ) -> None:
        """A narrow, enumerated backstop for a successful jailbreak.

        Not a general topicality check — see the note in `lexicon.py` on why a
        vocabulary-overlap measure was tried and rejected.
        """
        result = validator.validate(response(answer, sections=["company_profile"]))

        assert not result.is_valid

    @pytest.mark.parametrize(
        "answer",
        [
            "I'd be happy to help you with that.",
            "That project is finished. Would you like details about something else?",
            "Hello! I can answer questions about our projects and amenities.",
            "Our developments are all situated in the southern part of the city.",
        ],
    )
    def test_ordinary_conversational_answers_still_pass(
        self, validator: ResponseValidator, answer: str
    ) -> None:
        """The check must not cost the assistant its ability to hold a conversation."""
        result = validator.validate(response(answer, sections=["company_profile"]))

        assert result.is_valid, result.detail
