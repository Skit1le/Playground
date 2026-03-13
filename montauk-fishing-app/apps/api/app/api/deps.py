from functools import lru_cache
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.chlorophyll_provider import (
    FallbackChlorophyllProvider,
    LiveCoastwatchChlorophyllAdapter,
    MockChlorophyllAdapter,
    ProcessedCoastwatchChlorophyllAdapter,
)
from app.config import get_settings
from app.current_provider import ProcessedCurrentAdapter
from app.db import get_db_session
from app.environmental_inputs import (
    ChlorophyllBackedSource,
    FallbackBathymetrySource,
    FallbackChlorophyllSource,
    FallbackCurrentSource,
    FallbackWeatherSource,
    MockZoneEnvironmentalSignalStore,
    CurrentBackedSource,
    SeededBathymetrySource,
    SeededCurrentSource,
    SeededChlorophyllSource,
    SeededWeatherSource,
    StructureBackedSource,
    SstBackedTemperatureSource,
    WeatherBackedSource,
    ZoneEnvironmentalInputService,
)
from app.fallback_repositories import InMemorySpeciesConfigRepository, InMemoryZoneRepository
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.repositories import HistoricalZoneScoreSnapshotRepository, TripOutcomeRepository
from app.services.sst_map import SstMapService
from app.services.chlorophyll_map import ChlorophyllBreakMapService
from app.services.outcomes import HistoricalSnapshotService, OutcomeEvaluationService
from app.services.trip_outcomes import TripOutcomeService
from app.services.zones import ZonesService
from app.sst_provider import (
    FallbackSstProvider,
    LiveCoastwatchSstAdapter,
    MockSstAdapter,
    ProcessedCoastwatchSstAdapter,
)
from app.structure_provider import ProcessedStructureAdapter
from app.weather_provider import ProcessedWeatherAdapter

DbSession = Annotated[Session, Depends(get_db_session)]
logger = logging.getLogger(__name__)


@lru_cache
def get_signal_store() -> MockZoneEnvironmentalSignalStore:
    return MockZoneEnvironmentalSignalStore()


@lru_cache
def get_processed_sst_provider() -> ProcessedCoastwatchSstAdapter:
    settings = get_settings()
    return ProcessedCoastwatchSstAdapter(
        min_lat=settings.sst_bbox_min_lat,
        max_lat=settings.sst_bbox_max_lat,
        min_lon=settings.sst_bbox_min_lon,
        max_lon=settings.sst_bbox_max_lon,
        gradient_radius_nm=settings.sst_gradient_radius_nm,
    )


@lru_cache
def get_processed_chlorophyll_provider() -> ProcessedCoastwatchChlorophyllAdapter:
    settings = get_settings()
    return ProcessedCoastwatchChlorophyllAdapter(
        min_lat=settings.chlorophyll_bbox_min_lat,
        max_lat=settings.chlorophyll_bbox_max_lat,
        min_lon=settings.chlorophyll_bbox_min_lon,
        max_lon=settings.chlorophyll_bbox_max_lon,
    )


@lru_cache
def get_live_sst_provider() -> LiveCoastwatchSstAdapter:
    settings = get_settings()
    return LiveCoastwatchSstAdapter(
        dataset_id=settings.live_sst_dataset_id,
        base_url=settings.live_sst_base_url,
        variable_name=settings.live_sst_variable_name,
        time_suffix=settings.live_sst_time_suffix,
        extra_selectors=settings.live_sst_extra_selectors,
        longitude_mode=settings.live_sst_longitude_mode,
        min_lat=settings.sst_bbox_min_lat,
        max_lat=settings.sst_bbox_max_lat,
        min_lon=settings.sst_bbox_min_lon,
        max_lon=settings.sst_bbox_max_lon,
        gradient_radius_nm=settings.sst_gradient_radius_nm,
        timeout_seconds=settings.live_sst_timeout_seconds,
    )


LiveSstProviderDep = Annotated[LiveCoastwatchSstAdapter, Depends(get_live_sst_provider)]


@lru_cache
def get_live_chlorophyll_provider() -> LiveCoastwatchChlorophyllAdapter:
    settings = get_settings()
    return LiveCoastwatchChlorophyllAdapter(
        dataset_id=settings.live_chlorophyll_dataset_id,
        base_url=settings.live_chlorophyll_base_url,
        variable_name=settings.live_chlorophyll_variable_name,
        min_lat=settings.chlorophyll_bbox_min_lat,
        max_lat=settings.chlorophyll_bbox_max_lat,
        min_lon=settings.chlorophyll_bbox_min_lon,
        max_lon=settings.chlorophyll_bbox_max_lon,
        timeout_seconds=settings.live_chlorophyll_timeout_seconds,
    )


@lru_cache
def get_sst_provider() -> FallbackSstProvider:
    settings = get_settings()
    processed_sst_provider = get_processed_sst_provider()
    mock_sst_provider = MockSstAdapter(records=get_signal_store().records)
    processed_fallback = FallbackSstProvider(
        primary=processed_sst_provider,
        fallback=mock_sst_provider,
        timeout_seconds=settings.processed_lookup_timeout_seconds,
    )
    if not settings.live_sst_enabled:
        logger.info(
            "Live SST disabled; using processed->mock fallback chain",
            extra={
                "live_sst_enabled": settings.live_sst_enabled,
                "live_sst_dataset_id": settings.live_sst_dataset_id,
                "live_sst_base_url": settings.live_sst_base_url,
                "live_sst_variable_name": settings.live_sst_variable_name,
                "live_sst_time_suffix": settings.live_sst_time_suffix,
                "live_sst_extra_selectors": settings.live_sst_extra_selectors,
                "live_sst_longitude_mode": settings.live_sst_longitude_mode,
            },
        )
        return processed_fallback
    logger.info(
        "Live SST enabled; using live->processed->mock fallback chain",
        extra={
            "live_sst_enabled": settings.live_sst_enabled,
            "live_sst_dataset_id": settings.live_sst_dataset_id,
            "live_sst_base_url": settings.live_sst_base_url,
            "live_sst_variable_name": settings.live_sst_variable_name,
            "live_sst_time_suffix": settings.live_sst_time_suffix,
            "live_sst_extra_selectors": settings.live_sst_extra_selectors,
            "live_sst_longitude_mode": settings.live_sst_longitude_mode,
        },
    )
    return FallbackSstProvider(
        primary=get_live_sst_provider(),
        fallback=processed_fallback,
        timeout_seconds=settings.live_sst_timeout_seconds,
    )


@lru_cache
def get_chlorophyll_provider() -> FallbackChlorophyllProvider:
    settings = get_settings()
    processed_provider = get_processed_chlorophyll_provider()
    mock_provider = MockChlorophyllAdapter(records=get_signal_store().records)
    processed_fallback = FallbackChlorophyllProvider(
        primary=processed_provider,
        fallback=mock_provider,
    )
    if not settings.live_chlorophyll_enabled:
        return processed_fallback
    return FallbackChlorophyllProvider(
        primary=get_live_chlorophyll_provider(),
        fallback=processed_fallback,
    )


@lru_cache
def get_environmental_input_provider() -> ZoneEnvironmentalInputService:
    settings = get_settings()
    signal_store = get_signal_store()
    temperature_source = SstBackedTemperatureSource(get_sst_provider())
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
    chlorophyll_source = FallbackChlorophyllSource(
        primary=ChlorophyllBackedSource(get_chlorophyll_provider()),
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


@lru_cache
def get_sst_map_service() -> SstMapService:
    settings = get_settings()
    return SstMapService(
        sst_provider=get_sst_provider(),
        target_cells=settings.sst_map_target_cells,
    )


@lru_cache
def get_chlorophyll_break_map_service() -> ChlorophyllBreakMapService:
    settings = get_settings()
    return ChlorophyllBreakMapService(
        chlorophyll_provider=get_chlorophyll_provider(),
        target_cells=settings.chlorophyll_break_scoring_target_cells,
    )


def _build_repository_bundle(
    session: Session,
) -> tuple[ZoneRepository | InMemoryZoneRepository, SpeciesConfigRepository | InMemorySpeciesConfigRepository]:
    try:
        session.execute(text("SELECT 1"))
        zone_repository = ZoneRepository(session)
        species_config_repository = SpeciesConfigRepository(session)
    except OperationalError:
        zone_repository = InMemoryZoneRepository()
        species_config_repository = InMemorySpeciesConfigRepository()
    return zone_repository, species_config_repository


def get_zones_service(session: DbSession) -> ZonesService:
    settings = get_settings()
    zone_repository, species_config_repository = _build_repository_bundle(session)

    return ZonesService(
        zone_repository=zone_repository,
        species_config_repository=species_config_repository,
        environmental_input_provider=get_environmental_input_provider(),
        sst_break_target_cells=settings.sst_break_scoring_target_cells,
        chlorophyll_break_target_cells=settings.chlorophyll_break_scoring_target_cells,
        strong_break_threshold_f_per_nm=settings.sst_break_strong_threshold_f_per_nm,
        strong_chlorophyll_break_threshold_mg_m3_per_nm=settings.chlorophyll_break_strong_threshold_mg_m3_per_nm,
    )


def get_trip_outcome_service(session: DbSession) -> TripOutcomeService:
    return TripOutcomeService(repository=TripOutcomeRepository(session))


def get_historical_snapshot_service(session: DbSession) -> HistoricalSnapshotService:
    settings = get_settings()
    zone_repository, species_config_repository = _build_repository_bundle(session)
    zones_service = ZonesService(
        zone_repository=zone_repository,
        species_config_repository=species_config_repository,
        environmental_input_provider=get_environmental_input_provider(),
        sst_break_target_cells=settings.sst_break_scoring_target_cells,
        chlorophyll_break_target_cells=settings.chlorophyll_break_scoring_target_cells,
        strong_break_threshold_f_per_nm=settings.sst_break_strong_threshold_f_per_nm,
        strong_chlorophyll_break_threshold_mg_m3_per_nm=settings.chlorophyll_break_strong_threshold_mg_m3_per_nm,
    )
    return HistoricalSnapshotService(
        repository=HistoricalZoneScoreSnapshotRepository(session),
        zones_service=zones_service,
        evaluation_service=OutcomeEvaluationService(),
    )


ZonesServiceDep = Annotated[ZonesService, Depends(get_zones_service)]
SstMapServiceDep = Annotated[SstMapService, Depends(get_sst_map_service)]
ChlorophyllBreakMapServiceDep = Annotated[ChlorophyllBreakMapService, Depends(get_chlorophyll_break_map_service)]
TripOutcomeServiceDep = Annotated[TripOutcomeService, Depends(get_trip_outcome_service)]
HistoricalSnapshotServiceDep = Annotated[HistoricalSnapshotService, Depends(get_historical_snapshot_service)]
