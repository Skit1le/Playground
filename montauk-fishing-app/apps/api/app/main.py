import logging
from contextlib import asynccontextmanager
from time import sleep

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.api.routes.admin import router as admin_router
from app.api.routes.configs import router as configs_router
from app.api.routes.health import router as health_router
from app.api.routes.map import router as map_router
from app.api.routes.trip_logs import router as trip_logs_router
from app.api.routes.trip_outcomes import router as trip_outcomes_router
from app.api.routes.zones import router as zones_router
from app.config import get_settings
from app.db import SessionLocal
from app.seed import initialize_database, seed_database

settings = get_settings()
logger = logging.getLogger(__name__)


def wait_for_database(max_attempts: int, delay_seconds: int) -> None:
    last_error: OperationalError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            initialize_database()
            with SessionLocal() as session:
                seed_database(session)
            logger.info("Database initialization completed on attempt %s.", attempt)
            return
        except OperationalError as exc:
            last_error = exc
            logger.warning(
                "Database not ready on attempt %s/%s. Retrying in %s seconds.",
                attempt,
                max_attempts,
                delay_seconds,
            )
            sleep(delay_seconds)

    if last_error is not None:
        raise last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.database_status = "unknown"
    try:
        wait_for_database(
            max_attempts=settings.database_startup_max_attempts,
            delay_seconds=settings.database_startup_delay_seconds,
        )
        app.state.database_status = "ok"
    except OperationalError:
        if settings.database_required_on_startup:
            raise
        app.state.database_status = "unavailable"
        logger.warning(
            "Database startup check failed; continuing in degraded local mode with seeded fallbacks."
        )
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Montauk offshore fishing intelligence API with a weighted scoring engine.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(zones_router)
app.include_router(map_router)
app.include_router(trip_logs_router)
app.include_router(trip_outcomes_router)
app.include_router(configs_router)
app.include_router(admin_router)
