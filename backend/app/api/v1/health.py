"""Health and readiness.

Two endpoints rather than one, because they answer different questions:
`/health` is "is this process alive" (restart me if not) and `/ready` is "can
this process serve traffic" (route to me if so). Conflating them means a
knowledge-base failure triggers a restart loop instead of pulling the instance
out of rotation.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.api.dependencies import ContainerDep
from app.schemas.chat import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness")
async def health(container: ContainerDep) -> HealthResponse:
    """Report liveness.

    Detail is withheld in production. Model names and section counts are free
    reconnaissance for anyone probing the service, and a load balancer only
    reads `status`.
    """
    if container.settings.is_production:
        return HealthResponse(status="ok")

    return HealthResponse(
        status="ok",
        knowledge_base_sections=len(container.knowledge_base.sections),
        provider=container.settings.llm_provider.value,
    )


@router.get("/ready", summary="Readiness")
async def ready(container: ContainerDep) -> JSONResponse:
    """Report whether this instance can actually answer questions.

    A loaded-but-empty knowledge base is the failure this guards against: the
    process is perfectly healthy and every answer is the fallback. Without a
    readiness check that inspects content, that outage looks like uptime.
    """
    if not container.knowledge_base.sections:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready"})
