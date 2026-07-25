"""Security headers and client identification.

The headers here are chosen for a **JSON API**, not for a web page. That
distinction matters: the widget's own CSP is the host site's concern, and
copying a page-oriented policy onto an API endpoint produces headers that look
reassuring and protect nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import Settings

#: An API serves JSON and must never be a source of executable content or be
#: framed. `default-src 'none'` is the strongest possible starting point and is
#: correct here precisely because this endpoint loads nothing.
_CSP: Final = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

_BASE_HEADERS: Final = {
    "Content-Security-Policy": _CSP,
    # Stops a browser from MIME-sniffing a JSON response into something
    # executable.
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # Responses are visitor-specific and must not be held by a shared cache.
    "Cache-Control": "no-store",
}

#: Two years, with preload — the value required for HSTS preload eligibility.
_HSTS: Final = "max-age=63072000; includeSubDomains; preload"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach security headers to every response, including error responses.

    Applied as middleware rather than per-route because the responses most
    worth hardening are the ones no route handler produced — a 422 from
    validation, a 500 from an unhandled exception.
    """

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._headers = dict(_BASE_HEADERS)

        # HSTS is only meaningful over TLS, and sending it from a local HTTP
        # dev server can pin a developer's browser to https://localhost for two
        # years — an unpleasant thing to debug.
        if settings.is_production:
            self._headers["Strict-Transport-Security"] = _HSTS

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in self._headers.items():
            response.headers.setdefault(header, value)
        return response


def client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    """Identify the caller for per-IP rate limiting.

    `X-Forwarded-For` is client-controlled. Trusting it unconditionally means
    an attacker sends a fresh value per request and the per-IP limit stops
    existing — so it is honoured only when the deployment is explicitly
    configured to sit behind a proxy that overwrites the header.

    Getting this wrong is silent: the limiter still looks like it is working.
    """
    if trust_proxy_headers and (forwarded := request.headers.get("x-forwarded-for")):
        # Left-most entry is the original client; the rest are proxy hops.
        return forwarded.split(",")[0].strip()

    return request.client.host if request.client else "unknown"
