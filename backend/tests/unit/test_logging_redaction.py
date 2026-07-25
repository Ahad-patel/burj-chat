"""The log redaction processor.

This is a security control, not a formatting nicety. Visitor questions to a
real-estate assistant routinely contain names, phone numbers, and budgets;
writing them to disk would create a PII store this project otherwise does not
have, with no retention policy and no deletion path.

The rule is *don't log content*. This processor is the backstop for when
someone does it anyway.
"""

from __future__ import annotations

import pytest

from app.core.config import Environment, Provider, Settings
from app.core.logging import _redact, configure_logging, get_logger


def redact(**event: object) -> dict[str, object]:
    return dict(_redact(None, "info", dict(event)))


class TestSensitiveKeys:
    @pytest.mark.parametrize(
        "key",
        ["message", "content", "answer", "question", "prompt", "api_key", "token", "email"],
    )
    def test_sensitive_values_never_survive(self, key: str) -> None:
        result = redact(**{key: "My name is Priya and my budget is 2 crore"})

        assert "Priya" not in str(result[key])
        assert "crore" not in str(result[key])

    def test_a_length_summary_replaces_the_value(self) -> None:
        """Redacted, not dropped — shape is what makes the filter tunable."""
        result = redact(message="hello world")

        assert result["message"] == "<redacted len=11>"

    def test_an_api_key_cannot_leak_through_a_log_line(self) -> None:
        result = redact(api_key="AIzaSyD-REAL-LOOKING-KEY-000000000000000")

        assert "AIzaSy" not in str(result["api_key"])


class TestPatternScrubbing:
    def test_emails_are_scrubbed_from_arbitrary_fields(self) -> None:
        """Catches PII in a field nobody thought to add to the deny list."""
        result = redact(detail="contact buyer@example.com about the flat")

        assert "buyer@example.com" not in str(result["detail"])
        assert "<email>" in str(result["detail"])

    @pytest.mark.parametrize("phone", ["+91 98765 43210", "9876543210", "+91-98765-43210"])
    def test_phone_numbers_are_scrubbed(self, phone: str) -> None:
        result = redact(detail=f"call {phone} tomorrow")

        assert phone not in str(result["detail"])


class TestNonSensitiveFieldsSurvive:
    def test_operational_metrics_are_preserved(self) -> None:
        """Redaction must not blind the operator to what the system is doing."""
        result = redact(
            event="answered",
            outcome="blocked_by_filter",
            input_tokens=1200,
            output_tokens=45,
            elapsed_ms=830,
        )

        assert result["outcome"] == "blocked_by_filter"
        assert result["input_tokens"] == 1200
        assert result["elapsed_ms"] == 830

    def test_short_numbers_are_not_mistaken_for_phone_numbers(self) -> None:
        result = redact(detail="G+32 storeys over 1.75 lakh sq.ft")

        assert "G+32" in str(result["detail"])


class TestConfiguration:
    @pytest.mark.parametrize("env", [Environment.LOCAL, Environment.PRODUCTION])
    def test_logging_configures_without_error(self, env: Environment) -> None:
        configure_logging(Settings(app_env=env, llm_provider=Provider.GEMINI, gemini_api_key="k"))

        logger = get_logger("test")
        logger.info("configured", outcome="ok")  # must not raise


class TestRedactionDoesNotCorruptTheLog:
    """Regression tests for a bug 435 unit tests missed.

    The first version of the phone pattern matched any run of digits and
    dashes, so it ate the date out of every ISO timestamp — turning
    `2026-07-25T13:36:10Z` into `<phone>T13:36:10Z`. The whole suite passed;
    starting the server for ten seconds made it obvious.
    """

    def test_iso_timestamps_survive(self) -> None:
        result = redact(timestamp="2026-07-25T13:36:10.432849Z")

        assert result["timestamp"] == "2026-07-25T13:36:10.432849Z"

    def test_a_date_inside_an_arbitrary_field_survives(self) -> None:
        """The structural-key skip is not the only defence — the pattern
        itself must not treat an 8-digit date as a 10-digit phone number."""
        result = redact(detail="scraped on 2026-07-25 at 13:36")

        assert "2026-07-25" in str(result["detail"])

    @pytest.mark.parametrize("key", ["level", "event", "logger"])
    def test_structural_fields_are_left_alone(self, key: str) -> None:
        result = redact(**{key: "knowledge_base_loaded"})

        assert result[key] == "knowledge_base_loaded"

    def test_real_phone_numbers_are_still_caught(self) -> None:
        """The fix must not have simply disabled the control."""
        result = redact(detail="call 98199 62446 or +91 98765 43210")

        assert "98199 62446" not in str(result["detail"])
        assert "+91 98765 43210" not in str(result["detail"])

    @pytest.mark.parametrize(
        "text",
        ["G+32 storeys", "1.75 lakh sq.ft", "400010", "refuge areas on 8th, 15th and 22nd"],
    )
    def test_knowledge_base_figures_are_not_mistaken_for_phone_numbers(self, text: str) -> None:
        assert redact(detail=text)["detail"] == text
