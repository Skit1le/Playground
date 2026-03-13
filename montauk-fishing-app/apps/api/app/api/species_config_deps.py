from typing import Annotated

from fastapi import Depends, Request

from app.db import SessionLocal
from app.fallback_repositories import InMemorySpeciesConfigRepository
from app.services.species_configs import SpeciesConfigService


def get_species_config_service(request: Request) -> SpeciesConfigService:
    database_status = getattr(request.app.state, "database_status", "unknown")
    fallback_repository = InMemorySpeciesConfigRepository()

    if database_status != "ok":
        return SpeciesConfigService(species_config_repository=fallback_repository)

    return SpeciesConfigService(
        session_factory=SessionLocal,
        fallback_repository=fallback_repository,
    )


SpeciesConfigServiceDep = Annotated[SpeciesConfigService, Depends(get_species_config_service)]
