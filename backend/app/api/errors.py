"""Exception handlers. Nothing internal reaches a client.

Every handler here answers one question: what is the smallest true thing we can
say? Stack traces, exception class names, file paths, provider error text, and
SDK messages are all reconnaissance — they tell an attacker what the service is
built from and where its edges are.

The full detail still exists; it goes to the structured log, keyed by a request
id the client is also given, so support can correlate a complaint with a log
line without the error response carrying anything sensitive.
"""

from __future__ import annotations

import uuid
from typing import Final

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.domain.errors import DomainError, KnowledgeBaseError
from app.domain.ports.errors import LLMError

logger = get_logger(__name__)

_REQUEST_ID_HEADER: Final = "X-Request-ID"

#: Fixed client-facing text. Deliberately uninformative — an error message that
#: distinguishes "knowledge base failed to load" from "provider timed out"
#: tells a prober which subsystem they just reached.
_GENERIC: Final = "The request could not be completed. Please try again."
_INVALID: Final = "The request was not valid."
_TOO_LARGE: Final = "The request was too large."


def _respond(status_code: int, detail: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers={_REQUEST_ID_HEADER: request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that convert every failure into a safe response."""

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 for malformed input.

        FastAPI's default body echoes the offending input back. For an endpoint
        whose input is untrusted text, that is a reflection vector and a way to
        map the schema — so the response says only that validation failed, and
        the specifics go to the log.
        """
        request_id = _request_id(request)
        logger.info(
            "request_validation_failed",
            request_id=request_id,
            path=request.url.path,
            error_count=len(exc.errors()),
            fields=sorted({str(error.get("loc", ("?",))[-1]) for error in exc.errors()}),
        )
        return _respond(status.HTTP_422_UNPROCESSABLE_CONTENT, _INVALID, request_id)

    @app.exception_handler(KnowledgeBaseError)
    async def _knowledge_base(request: Request, exc: KnowledgeBaseError) -> JSONResponse:
        """The knowledge base is unusable — the service cannot answer anything."""
        request_id = _request_id(request)
        logger.error("knowledge_base_unavailable", request_id=request_id, error=str(exc))
        return _respond(status.HTTP_503_SERVICE_UNAVAILABLE, _GENERIC, request_id)

    @app.exception_handler(LLMError)
    async def _llm(request: Request, exc: LLMError) -> JSONResponse:
        """A provider failure that escaped the service's own handling.

        The service degrades provider errors to the fallback, so reaching this
        handler means something unanticipated — worth logging loudly, still not
        worth telling the client about.
        """
        request_id = _request_id(request)
        logger.error(
            "llm_error_escaped_service",
            request_id=request_id,
            error_type=type(exc).__name__,
        )
        return _respond(status.HTTP_503_SERVICE_UNAVAILABLE, _GENERIC, request_id)

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        """A business-rule violation — the caller sent something invalid."""
        request_id = _request_id(request)
        logger.info("domain_error", request_id=request_id, error_type=type(exc).__name__)
        return _respond(status.HTTP_400_BAD_REQUEST, _INVALID, request_id)

    @app.exception_handler(ValueError)
    async def _value(request: Request, exc: ValueError) -> JSONResponse:
        request_id = _request_id(request)
        logger.info("value_error", request_id=request_id)
        return _respond(status.HTTP_400_BAD_REQUEST, _INVALID, request_id)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """The catch-all.

        Without this, an unhandled exception renders Starlette's default 500 —
        which in a misconfigured deployment can include a traceback. The
        traceback is logged with `exc_info` and never serialised.
        """
        request_id = _request_id(request)
        logger.error(
            "unhandled_exception",
            request_id=request_id,
            path=request.url.path,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        return _respond(status.HTTP_500_INTERNAL_SERVER_ERROR, _GENERIC, request_id)


def _request_id(request: Request) -> str:
    """Return this request's correlation id, minting one if absent."""
    existing = getattr(request.state, "request_id", None)
    return str(existing) if existing else str(uuid.uuid4())


__all__ = ["_REQUEST_ID_HEADER", "_TOO_LARGE", "register_exception_handlers"]
