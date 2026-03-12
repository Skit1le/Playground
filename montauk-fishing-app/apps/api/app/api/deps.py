from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.chlorophyll_provider import ProcessedCoastwatchChlorophyllAdapter
from app.config import get_settings
from app.current_provider import ProcessedCurrentAdapter
from app.db import get_db_session
from app.environmental_inputs import (
    ChlorophyllBackedSource,
    FallbackBathymetrySource,
    FallbackChlorophyllSource,
    FallbackCurrentSource,
    FallbackTemperatureSource,
    FallbackWeatherSource,
    MockZoneEnvironmentalSignalStore,
    CurrentBackedSource,
    SeededBathymetrySource,
    SeededCurrentSource,
    SeededChlorophyllSource,
    SeededTemperatureSource,
    SeededWeatherSource,
    StructureBackedSource,
    SstBackedTemperatureSource,
    WeatherBackedSource,
    ZoneEnvironmentalInputService,
)
from app.fallback_repositories import InMemorySpeciesConfigRepository, InMemoryZoneRepository
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.services.zones import ZonesService
from app.sst_provider import ProcessedCoastwatchSstAdapter
from app.structure_provider import ProcessedStructureAdapter
from app.weather_provider import ProcessedWeatherAdapter

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
    chlorophyll_provider = ProcessedCoastwatchChlorophyllAdapter(
        min_lat=settings.chlorophyll_bbox_min_lat,
        max_lat=settings.chlorophyll_bbox_max_lat,
        min_lon=settings.chlorophyll_bbox_min_lon,
        max_lon=settings.chlorophyll_bbox_max_lon,
    )
    current_provider = ProcessedCurrentAdapter(
        min_lat=settings.current_bbox_min_lat,
        max_lat=settings.current_bbox_max_lat,
        min_lon=settings.current_bbox_min_lon,
        max_lon=settings.current_bbox_max_lon,
        break_radius_nm=settings.current_break_radius_nm,
    )
    structure_provider = ProcessedStructureAdapter(
        min_lat=settings.structure_bbox_min_lat,
        max_lat=settings.structure_bbox_max_lat,
        min_lon=settings.structure_bbox_min_lon,
        max_lon=settings.structure_bbox_max_lon,
    )
    weather_provider = ProcessedWeatherAdapter(
        min_lat=settings.weather_bbox_min_lat,
        max_lat=settings.weather_bbox_max_lat,
        min_lon=settings.weather_bbox_min_lon,
        max_lon=settings.weather_bbox_max_lon,
    )
    temperature_source = FallbackTemperatureSource(
        primary=SstBackedTemperatureSource(sst_provider),
        fallback=SeededTemperatureSource(signal_store),
        timeout_seconds=settings.processed_lookup_timeout_seconds,
    )
    chlorophyll_source = FallbackChlorophyllSource(
        primary=ChlorophyllBackedSource(chlorophyll_provider),
        fallback=SeededChlorophyllSource(signal_store),
        timeout_seconds=settings.processed_lookup_timeout_seconds,
    )
    current_source = FallbackCurrentSource(
        primary=CurrentBackedSource(current_provider),
        fallback=SeededCurrentSource(signal_store),
        timeout_seconds=settings.processed_lookup_timeout_seconds,
    )
    bathymetry_source = FallbackBathymetrySource(
        primary=StructureBackedSource(structure_provider),
        fallback=SeededBathymetrySource(signal_store),
        timeout_seconds=settings.processed_lookup_timeout_seconds,
    )
    weather_source = FallbackWeatherSource(
        primary=WeatherBackedSource(weather_provider),
        fallback=SeededWeatherSource(signal_store),
        timeout_seconds=settings.processed_lookup_timeout_seconds,
    )
    return ZoneEnvironmentalInputService(
        temperature_source=temperature_source,
        bathymetry_source=bathymetry_source,
        chlorophyll_source=chlorophyll_source,
        current_source=current_source,
        weather_source=weather_source,
        signal_store=signal_store,
    )


def get_zones_service(session: DbSession) -> ZonesService:
    try:
        session.execute(text("SELECT 1"))
        zone_repository = ZoneRepository(session)
        species_config_repository = SpeciesConfigRepository(session)
    except OperationalError:
        zone_repository = InMemoryZoneRepository()
        species_config_repository = InMemorySpeciesConfigRepository()

    return ZonesService(
        zone_repository=zone_repository,
        species_config_repository=species_config_repository,
        environmental_input_provider=get_environmental_input_provider(),
    )


ZonesServiceDep = Annotated[ZonesService, Depends(get_zones_service)]
