"""Application factory.

Everything expensive happens once, at startup: the knowledge base is parsed,
the provider client is constructed, the rate limiters are allocated. If any of
that fails the process refuses to start — which is the correct behaviour. A
service that boots with a broken knowledge base answers every question with the
fallback while every health check stays green.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.api.errors import register_exception_handlers
from app.api.v1 import chat, health
from app.core.config import Settings, get_settings
from app.core.container import build_container
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import SecurityHeadersMiddleware

logger = get_logger(__name__)

API_PREFIX = "/api/v1"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Give every request a correlation id.

    Written to `request.state` so error handlers and the service can log the
    same value, and echoed to the client so a bug report carries something we
    can search for — without the response body having to reveal anything.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the object graph on startup, tear it down on shutdown."""
    settings: Settings = app.state.settings

    app.state.container = build_container(settings)
    app.state.ip_limiter = SlidingWindowLimiter(
        limit=settings.rate_limit_per_ip_per_minute, window_seconds=60
    )
    app.state.session_limiter = SlidingWindowLimiter(
        limit=settings.rate_limit_per_session_per_hour, window_seconds=3600
    )

    logger.info(
        "application_started",
        environment=settings.app_env.value,
        provider=settings.llm_provider.value,
        allowed_origins=list(settings.allowed_origins),
        trust_proxy_headers=settings.trust_proxy_headers,
    )

    yield

    logger.info("application_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the ASGI application.

    A factory rather than a module-level `app` so tests can build an instance
    with their own settings instead of mutating global state.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Burj Constructions AI Assistant",
        version="0.1.0",
        lifespan=lifespan,
        # The interactive docs describe the attack surface. Useful locally,
        # gratuitous in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings

    # Middleware runs in reverse registration order, so the last one added is
    # outermost. Security headers go on last, guaranteeing they are attached to
    # every response — including ones produced by CORS or by a failure inside
    # another middleware.
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # An explicit list, never a wildcard. `allow_credentials` with `*` is
        # rejected by browsers anyway, and a permissive API origin lets any
        # site on the internet spend this client's LLM budget.
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    register_exception_handlers(app)

    app.include_router(chat.router, prefix=API_PREFIX)
    app.include_router(health.router)

    return app


# Deliberately no module-level `app = create_app()`.
#
# A module-level instance would run settings validation at *import* time, so
# `import app.main` — which every test, linter, and type checker does — would
# fail on any machine without a live API key. Serve with the factory flag
# instead:
#
#     uvicorn app.main:create_app --factory
