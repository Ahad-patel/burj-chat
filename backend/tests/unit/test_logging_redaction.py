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
