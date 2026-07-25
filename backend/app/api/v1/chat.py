"""The chat endpoint.

Thin by design: validate, rate limit, delegate, serialise. Every decision about
*what to answer* lives in the domain and the service — this module's only job
is to be a safe front door.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies import ConversationServiceDep, enforce_rate_limits
from app.schemas.chat import ChatRequest, ChatResponse, ErrorResponse

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

    This handler has no failure branch of its own. The service degrades every
    error — guardrail rejection, provider outage, invalid input — into the same
    fallback reply, so a visitor never sees a 500 for an ordinary question.
    """
    conversation_id = payload.resolved_conversation_id()
    reply = await service.respond(conversation_id, payload.message)

    # Echoed so the widget can correlate a report with a log line. The service
    # logs the same id alongside the guardrail decision.
    response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")

    return ChatResponse(
        conversation_id=reply.conversation_id,
        answer=reply.answer,
        is_fallback=reply.is_fallback,
    )
