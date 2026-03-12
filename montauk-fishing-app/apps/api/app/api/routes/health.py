from fastapi import APIRouter

from app.config import get_settings
from app.db import database_is_available
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    database_status = "ok" if settings.database_url and database_is_available() else "unavailable"

    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.api_env,
        database=database_status,
    )
