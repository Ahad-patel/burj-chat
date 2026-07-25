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

_EMAIL_PATTERN: Final = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_PATTERN: Final = re.compile(r"(?:\+?\d[\d\s-]{7,}\d)")


def _redact(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Strip sensitive values from a log event before it is rendered.

    Sensitive keys are replaced with a length summary rather than dropped, so a
    log line still says *something happened, this big* — which is what makes the
    guardrails tunable without reading anyone's messages.
    """
    for key, value in list(event_dict.items()):
        if key in _SENSITIVE_KEYS:
            event_dict[key] = f"<redacted len={len(str(value))}>"
        elif isinstance(value, str):
            value = _EMAIL_PATTERN.sub("<email>", value)
            event_dict[key] = _PHONE_PATTERN.sub("<phone>", value)

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
