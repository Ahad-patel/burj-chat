"""FastAPI dependencies — the wiring between HTTP and the service layer.

Python note: a "dependency" here is just a callable FastAPI runs before the
handler, injecting its return value. It is how cross-cutting concerns (rate
limiting, resolving the container) stay out of the handler body without a
framework-wide middleware that cannot see route-specific arguments.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings
from app.core.container import Container
from app.core.logging import get_logger
from app.core.security import client_ip
from app.services.conversation_service import ConversationService

logger = get_logger(__name__)


def get_container(request: Request) -> Container:
    """Return the container built once during startup.

    Held on `app.state` rather than rebuilt per request — the knowledge base is
    parsed at boot and the provider client holds a connection pool.
    """
    container: Container = request.app.state.container
    return container


def get_settings_dep(request: Request) -> Settings:
    return get_container(request).settings


def get_conversation_service(request: Request) -> ConversationService:
    return get_container(request).conversation_service


ContainerDep = Annotated[Container, Depends(get_container)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


async def enforce_rate_limits(request: Request) -> None:
    """Apply the per-IP and per-conversation limits.

    Both are checked because they stop different things. The per-IP limit stops
    one machine hammering the endpoint. The per-conversation limit stops a
    distributed set of IPs sharing a single conversation id to bypass it — and
    caps what any one session can cost regardless of where it comes from.

    The IP limit is checked first: it is the cheaper key and does not require
    reading the body.
    """
    container: Container = request.app.state.container
    settings = container.settings

    ip = client_ip(request, trust_proxy_headers=settings.trust_proxy_headers)
    verdict = request.app.state.ip_limiter.check(ip)

    if not verdict.allowed:
        logger.info("rate_limited", scope="ip", retry_after=verdict.retry_after_seconds)
        raise _too_many_requests(verdict.retry_after_seconds)

    # The conversation id lives in the body, which FastAPI has already parsed
    # and cached by the time dependencies run — reading it here does not
    # consume the stream a second time.
    conversation_id = await _conversation_id(request)
    if conversation_id is None:
        return  # a new conversation has no history to limit yet

    session_verdict = request.app.state.session_limiter.check(conversation_id)
    if not session_verdict.allowed:
        logger.info(
            "rate_limited", scope="session", retry_after=session_verdict.retry_after_seconds
        )
        raise _too_many_requests(session_verdict.retry_after_seconds)


async def _conversation_id(request: Request) -> str | None:
    """Read `conversation_id` from the body without failing on malformed input.

    A body that does not parse is not this dependency's problem — the schema
    will reject it with a 422 moments later. Raising here would turn a
    validation error into a rate-limiter error and confuse the logs.
    """
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return None

    if not isinstance(body, dict):
        return None

    value = body.get("conversation_id")
    return value if isinstance(value, str) and value else None


def _too_many_requests(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests. Please wait a moment and try again.",
        headers={"Retry-After": str(retry_after)},
    )
