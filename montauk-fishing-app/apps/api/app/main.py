from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.configs import router as configs_router
from app.api.routes.health import router as health_router
from app.api.routes.trip_logs import router as trip_logs_router
from app.api.routes.zones import router as zones_router
from app.config import get_settings
from app.db import SessionLocal
from app.seed import initialize_database, seed_database

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    with SessionLocal() as session:
        seed_database(session)
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(zones_router)
app.include_router(trip_logs_router)
app.include_router(configs_router)
