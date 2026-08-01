"""The chat endpoint.

Thin by design: validate, rate limit, delegate, serialise. Every decision about
*what to answer* lives in the domain and the service — this module's only job
is to be a safe front door.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.dependencies import ConversationServiceDep, enforce_rate_limits
from app.schemas.chat import ChatRequest, ChatResponse, ErrorResponse
from app.services.conversation_service import Outcome

router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
        status.HTTP_429_TOO_MANY_REQUESTS: {"model": ErrorResponse},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ErrorResponse},
    },
    summary="Ask the assistant a question",
)
async def chat(
    payload: ChatRequest,
    request: Request,
    response: Response,
    service: ConversationServiceDep,
    _limits: Annotated[None, Depends(enforce_rate_limits)],
) -> ChatResponse:
    """Answer from the knowledge base, or return the fallback.

    Guardrail refusals return 200 with the fallback — a refusal is a valid
    answer, not an error.

    A **provider outage is different** and returns 503. The service degrades it
    to the same fallback text internally, and returning that verbatim would
    tell a visitor "I don't have information about that" when the truth is that
    nothing was ever asked. That is actively misleading: it implies the
    knowledge base was consulted and came up empty, and it makes an outage
    indistinguishable from a grounding refusal for whoever is debugging.

    This leaks nothing. An upstream failure is not a guardrail decision, so
    naming it tells an attacker nothing about the filter — unlike the *reason*
    a guardrail fired, which is still never disclosed.
    """
    conversation_id = payload.resolved_conversation_id()
    reply = await service.respond(conversation_id, payload.message)

    if reply.outcome is Outcome.PROVIDER_ERROR:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily unavailable. Please try again shortly.",
            headers={"Retry-After": "30"},
        )

    # Echoed so the widget can correlate a report with a log line. The service
    # logs the same id alongside the guardrail decision.
    response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")

    return ChatResponse(
        conversation_id=reply.conversation_id,
        answer=reply.answer,
        is_fallback=reply.is_fallback,
    )
