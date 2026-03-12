from sqlalchemy import text

from fastapi import APIRouter

from app.api.deps import DbSession
from app.config import get_settings
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health", response_model=HealthResponse)
def healthcheck(session: DbSession) -> HealthResponse:
    database_status = "missing"
    if settings.database_url:
        session.execute(text("SELECT 1"))
        database_status = "ok"

    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.api_env,
        database=database_status,
    )
