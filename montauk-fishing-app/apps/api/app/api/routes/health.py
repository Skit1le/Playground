import logging

from fastapi import APIRouter, Request

from app.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
def healthcheck(request: Request) -> HealthResponse:
    database_status = getattr(request.app.state, "database_status", "unknown")
    logger.info(
        "Handling /health request",
        extra={
            "database_status": database_status,
        },
    )

    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.api_env,
        database=database_status,
    )
