from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.services.zones import ZonesService

DbSession = Annotated[Session, Depends(get_db_session)]


def get_zones_service(session: DbSession) -> ZonesService:
    return ZonesService(
        zone_repository=ZoneRepository(session),
        species_config_repository=SpeciesConfigRepository(session),
    )


ZonesServiceDep = Annotated[ZonesService, Depends(get_zones_service)]
