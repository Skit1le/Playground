from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db_session
from app.environmental_inputs import (
    FallbackTemperatureSource,
    MockZoneEnvironmentalSignalStore,
    SeededTemperatureSource,
    SstBackedTemperatureSource,
    ZoneEnvironmentalInputService,
)
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.services.zones import ZonesService
from app.sst_provider import ProcessedCoastwatchSstAdapter

DbSession = Annotated[Session, Depends(get_db_session)]


@lru_cache
def get_environmental_input_provider() -> ZoneEnvironmentalInputService:
    settings = get_settings()
    signal_store = MockZoneEnvironmentalSignalStore()
    sst_provider = ProcessedCoastwatchSstAdapter(
        min_lat=settings.sst_bbox_min_lat,
        max_lat=settings.sst_bbox_max_lat,
        min_lon=settings.sst_bbox_min_lon,
        max_lon=settings.sst_bbox_max_lon,
        gradient_radius_nm=settings.sst_gradient_radius_nm,
    )
    temperature_source = FallbackTemperatureSource(
        primary=SstBackedTemperatureSource(sst_provider),
        fallback=SeededTemperatureSource(signal_store),
    )
    return ZoneEnvironmentalInputService(
        temperature_source=temperature_source,
        signal_store=signal_store,
    )


def get_zones_service(session: DbSession) -> ZonesService:
    return ZonesService(
        zone_repository=ZoneRepository(session),
        species_config_repository=SpeciesConfigRepository(session),
        environmental_input_provider=get_environmental_input_provider(),
    )


ZonesServiceDep = Annotated[ZonesService, Depends(get_zones_service)]
