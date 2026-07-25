"""Structured logging, configured once at startup.

**Nothing here ever logs message content.** Visitor questions to a real estate
assistant routinely contain names, phone numbers, and budgets — writing them to
disk creates a PII store the project otherwise does not have, in a system with
no retention policy and no deletion path. What gets logged instead is shape:
message *length*, the guardrail decision, token usage, latency. That is enough
to tune the filter and track spend; it is not enough to identify anyone.

`_redact` exists as a backstop, not a licence. It is applied to values that
might slip through, but the rule remains: do not pass content to a logger.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, Final

import structlog

from app.core.config import Environment, Settings

#: Keys whose values must never reach a log sink, whatever the call site did.
_SENSITIVE_KEYS: Final = frozenset(
    {
        "message",
        "content",
        "answer",
        "question",
        "text",
        "prompt",
        "system_prompt",
        "api_key",
        "authorization",
        "token",
        "email",
        "phone",
    }
)

#: Fields structlog generates itself. They are never visitor input, and
#: scrubbing them corrupts the log: the first version of this module ate the
#: date out of every ISO timestamp, because "2026-07-25" is digits and dashes
#: and matched the phone pattern. 435 unit tests passed; running the server for
#: ten seconds showed it immediately.
_STRUCTURAL_KEYS: Final = frozenset({"timestamp", "level", "event", "logger", "exception"})

_EMAIL_PATTERN: Final = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

#: A *candidate* run of digits and separators. Whether it is really a phone
#: number is decided by `_scrub_phone`, because no regex distinguishes
#: "2026-07-25" from "98199 62446" on shape alone — only on digit count.
_PHONE_CANDIDATE: Final = re.compile(r"\+?\d[\d\s-]{6,}\d")

#: Shortest run treated as a phone number. Indian mobiles are 10 digits; an
#: ISO date is 8, which is what keeps timestamps intact.
_MIN_PHONE_DIGITS: Final = 10


def _scrub_phone(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    return "<phone>" if len(digits) >= _MIN_PHONE_DIGITS else raw


def _redact(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Strip sensitive values from a log event before it is rendered.

    Sensitive keys are replaced with a length summary rather than dropped, so a
    log line still says *something happened, this big* — which is what makes the
    guardrails tunable without reading anyone's messages.
    """
    for key, value in list(event_dict.items()):
        if key in _STRUCTURAL_KEYS:
            continue
        if key in _SENSITIVE_KEYS:
            event_dict[key] = f"<redacted len={len(str(value))}>"
        elif isinstance(value, str):
            value = _EMAIL_PATTERN.sub("<email>", value)
            event_dict[key] = _PHONE_CANDIDATE.sub(_scrub_phone, value)

    return event_dict


def configure_logging(settings: Settings) -> None:
    """Set up structlog. Call once, at application startup.

    JSON in production so a log aggregator can parse it; coloured key-value
    output locally so a human can read it.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.app_env is not Environment.LOCAL
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
