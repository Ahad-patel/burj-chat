"""Provider-neutral LLM failures.

Each adapter catches its SDK's exceptions and re-raises one of these. The domain
and service layers only ever handle this family, which is what lets them stay
identical across providers — an `except anthropic.RateLimitError` in a service
would silently break Gemini, and vice versa.
"""

from __future__ import annotations

from app.domain.errors import DomainError


class LLMError(DomainError):
    """Base class for any failure originating from a language model provider."""


class LLMTimeoutError(LLMError):
    """The provider did not respond within the configured timeout."""


class LLMRateLimitError(LLMError):
    """The provider rejected the request for exceeding a quota."""


class LLMUnavailableError(LLMError):
    """The provider is unreachable, misconfigured, or returned a server error."""


class LLMContentBlockedError(LLMError):
    """The provider's own safety filters refused the request or the response.

    Distinct from our guardrails: this is the vendor declining, not us. Worth
    separating because it usually means a prompt needs revising rather than a
    retry, and because we never want to present a vendor safety notice as if it
    were our own grounding fallback.
    """
