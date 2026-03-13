import logging
from dataclasses import replace
from time import perf_counter
from datetime import date

from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.environmental_inputs import (
    EnvironmentalInputProvider,
    ResolvedZoneEnvironmentalInputs,
    ZoneEnvironmentalInputService,
    ZoneEnvironmentalSignals,
    ZoneEnvironmentalSourceMetadata,
)
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.scoring import (
    ScoreResult,
    ZoneScoringEngine,
    build_chlorophyll_break_config,
    build_temp_break_config,
    build_weighted_score_config,
)
from app.schemas import RankedZone, SpeciesConfig, ZoneCenter
from app.services.chlorophyll_edges import (
    build_chlorophyll_cell_signals,
    nearest_strong_chlorophyll_break_distance_nm,
)
from app.services.sst_map import build_sst_cell_signals, nearest_strong_break_distance_nm

logger = logging.getLogger(__name__)


class SpeciesConfigNotFoundError(ValueError):
    pass


class ZonesService:
    def __init__(
        self,
        zone_repository: ZoneRepository,
        species_config_repository: SpeciesConfigRepository,
        scoring_engine: ZoneScoringEngine | None = None,
        environmental_input_provider: EnvironmentalInputProvider | None = None,
        sst_break_target_cells: int = 480,
        chlorophyll_break_target_cells: int = 720,
        strong_break_threshold_f_per_nm: float = 0.05,
        strong_chlorophyll_break_threshold_mg_m3_per_nm: float = 0.01,
    ):
        self.zone_repository = zone_repository
        self.species_config_repository = species_config_repository
        self.scoring_engine = scoring_engine or ZoneScoringEngine()
        self.environmental_input_provider = environmental_input_provider or ZoneEnvironmentalInputService()
        self.sst_break_target_cells = sst_break_target_cells
        self.chlorophyll_break_target_cells = chlorophyll_break_target_cells
        self.default_strong_break_threshold_f_per_nm = strong_break_threshold_f_per_nm
        self.default_strong_chlorophyll_break_threshold_mg_m3_per_nm = strong_chlorophyll_break_threshold_mg_m3_per_nm

    def list_ranked_zones(self, species: str, trip_date: date, limit: int) -> list[RankedZone]:
        started_at = perf_counter()
        config = self.species_config_repository.get_by_species(species)
        if config is None:
            raise SpeciesConfigNotFoundError(f"No scoring configuration found for species '{species}'.")

        zones = self.zone_repository.list_for_species(species)
        break_distances_by_zone = self._build_zone_break_distances(zones, species, trip_date)
        chlorophyll_break_distances_by_zone = self._build_zone_chlorophyll_break_distances(
            zones,
            species,
            trip_date,
        )
        ranked_zones = [
            self._score_zone(
                zone=zone,
                config=config,
                species=species,
                trip_date=trip_date,
                nearest_strong_break_distance_nm=break_distances_by_zone.get(zone.id),
                nearest_strong_chl_break_distance_nm=chlorophyll_break_distances_by_zone.get(zone.id),
            )
            for zone in zones
        ]
        ranked_zones.sort(key=lambda zone: zone.score, reverse=True)
        limited_ranked_zones = ranked_zones[:limit]
        logger.info(
            "Completed zones ranking request",
            extra={
                "trip_date": trip_date.isoformat(),
                "species": species,
                "zone_count": len(zones),
                "returned_zone_count": len(limited_ranked_zones),
                "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
            },
        )
        return limited_ranked_zones

    def rank_zones(self, species: str, trip_date: date, limit: int) -> list[RankedZone]:
        return self.list_ranked_zones(species=species, trip_date=trip_date, limit=limit)

    def list_species_configs(self) -> list[SpeciesConfig]:
        return [build_species_config(config) for config in self.species_config_repository.list_all()]

    def _score_zone(
        self,
        zone: ZoneModel,
        config: SpeciesScoringConfigModel,
        species: str,
        trip_date: date,
        nearest_strong_break_distance_nm: float | None,
        nearest_strong_chl_break_distance_nm: float | None,
    ) -> RankedZone:
        resolved_inputs = self._resolve_zone_inputs(zone, trip_date)
        signals = replace(
            resolved_inputs.signals,
            nearest_strong_break_distance_nm=nearest_strong_break_distance_nm,
            nearest_strong_chl_break_distance_nm=nearest_strong_chl_break_distance_nm,
        )
        score_result = self.scoring_engine.score(signals, config, trip_date)
        logger.info(
            "Resolved zone environmental sources",
            extra={
                "zone_id": zone.id,
                "trip_date": trip_date.isoformat(),
                "sst_source": resolved_inputs.metadata.sst_source,
                "sst_dataset_id": getattr(self.environmental_input_provider.temperature_source, "last_dataset_id", None)
                if hasattr(self.environmental_input_provider, "temperature_source")
                else None,
                "sst_cache_key": getattr(self.environmental_input_provider.temperature_source, "last_cache_key", "")
                if hasattr(self.environmental_input_provider, "temperature_source")
                else "",
                "chlorophyll_source": resolved_inputs.metadata.chlorophyll_source,
                "current_source": resolved_inputs.metadata.current_source,
                "bathymetry_source": resolved_inputs.metadata.bathymetry_source,
                "weather_source": resolved_inputs.metadata.weather_source,
            },
        )
        return build_ranked_zone(zone, signals, species, trip_date, score_result)

    def _resolve_zone_inputs(self, zone: ZoneModel, trip_date: date) -> ResolvedZoneEnvironmentalInputs:
        if hasattr(self.environmental_input_provider, "resolve_zone_inputs"):
            return self.environmental_input_provider.resolve_zone_inputs(zone, trip_date)
        return ResolvedZoneEnvironmentalInputs(
            signals=self.environmental_input_provider.get_zone_signals(zone, trip_date),
            metadata=ZoneEnvironmentalSourceMetadata(
                sst_source="unknown",
                chlorophyll_source="unknown",
                current_source="unknown",
                bathymetry_source="unknown",
                weather_source="unknown",
            ),
        )

    def _build_zone_break_distances(
        self,
        zones: list[ZoneModel],
        species: str,
        trip_date: date,
    ) -> dict[str, float | None]:
        sst_provider = _extract_sst_provider(self.environmental_input_provider)
        if sst_provider is None or not zones:
            return {zone.id: None for zone in zones}

        bbox = _resolve_grid_provider_bbox(sst_provider, zones)
        temp_break_config = build_temp_break_config(species)
        try:
            points = sst_provider.get_sst_points(
                trip_date,
                min_lat=bbox[1],
                max_lat=bbox[3],
                min_lon=bbox[0],
                max_lon=bbox[2],
            )
        except Exception:
            logger.warning(
                "Unable to derive SST break distances for /zones request",
                extra={"trip_date": trip_date.isoformat(), "zone_count": len(zones)},
            )
            return {zone.id: None for zone in zones}

        cells = build_sst_cell_signals(points, bbox, self.sst_break_target_cells)
        return {
            zone.id: nearest_strong_break_distance_nm(
                latitude=zone.center_lat,
                longitude=zone.center_lng,
                cells=cells,
                minimum_break_intensity_f_per_nm=(
                    temp_break_config.strong_break_threshold_f_per_nm
                    or self.default_strong_break_threshold_f_per_nm
                ),
            )
            for zone in zones
        }

    def _build_zone_chlorophyll_break_distances(
        self,
        zones: list[ZoneModel],
        species: str,
        trip_date: date,
    ) -> dict[str, float | None]:
        chlorophyll_provider = _extract_chlorophyll_provider(self.environmental_input_provider)
        if chlorophyll_provider is None or not zones:
            return {zone.id: None for zone in zones}

        bbox = _resolve_grid_provider_bbox(chlorophyll_provider, zones)
        chlorophyll_break_config = build_chlorophyll_break_config(species)
        try:
            points = chlorophyll_provider.get_chlorophyll_points(
                trip_date,
                min_lat=bbox[1],
                max_lat=bbox[3],
                min_lon=bbox[0],
                max_lon=bbox[2],
            )
        except Exception:
            logger.warning(
                "Unable to derive chlorophyll break distances for /zones request",
                extra={"trip_date": trip_date.isoformat(), "zone_count": len(zones)},
            )
            return {zone.id: None for zone in zones}

        cells = build_chlorophyll_cell_signals(points, bbox, self.chlorophyll_break_target_cells)
        return {
            zone.id: nearest_strong_chlorophyll_break_distance_nm(
                latitude=zone.center_lat,
                longitude=zone.center_lng,
                cells=cells,
                minimum_break_intensity_mg_m3_per_nm=(
                    chlorophyll_break_config.strong_break_threshold_mg_m3_per_nm
                    or self.default_strong_chlorophyll_break_threshold_mg_m3_per_nm
                ),
            )
            for zone in zones
        }


def _extract_sst_provider(environmental_input_provider: EnvironmentalInputProvider | object):
    temperature_source = getattr(environmental_input_provider, "temperature_source", None)
    if temperature_source is None:
        return None
    for candidate in (
        getattr(temperature_source, "sst_provider", None),
        getattr(getattr(temperature_source, "primary", None), "sst_provider", None),
        getattr(getattr(temperature_source, "fallback", None), "sst_provider", None),
    ):
        if candidate is not None and hasattr(candidate, "get_sst_points"):
            return candidate
    return None


def _extract_chlorophyll_provider(environmental_input_provider: EnvironmentalInputProvider | object):
    chlorophyll_source = getattr(environmental_input_provider, "chlorophyll_source", None)
    if chlorophyll_source is None:
        return None
    for candidate in (
        getattr(chlorophyll_source, "chlorophyll_provider", None),
        getattr(getattr(chlorophyll_source, "primary", None), "chlorophyll_provider", None),
        getattr(getattr(chlorophyll_source, "fallback", None), "chlorophyll_provider", None),
    ):
        if candidate is not None and hasattr(candidate, "get_chlorophyll_points"):
            return candidate
    return None


def _resolve_grid_provider_bbox(
    provider: object,
    zones: list[ZoneModel],
) -> tuple[float, float, float, float]:
    min_lat = getattr(provider, "min_lat", None)
    max_lat = getattr(provider, "max_lat", None)
    min_lon = getattr(provider, "min_lon", None)
    max_lon = getattr(provider, "max_lon", None)
    if None not in (min_lat, max_lat, min_lon, max_lon):
        return (float(min_lon), float(min_lat), float(max_lon), float(max_lat))

    latitudes = [zone.center_lat for zone in zones]
    longitudes = [zone.center_lng for zone in zones]
    padding = 0.4
    return (
        round(min(longitudes) - padding, 4),
        round(min(latitudes) - padding, 4),
        round(max(longitudes) + padding, 4),
        round(max(latitudes) + padding, 4),
    )


def build_ranked_zone(
    zone: ZoneModel,
    signals: ZoneEnvironmentalSignals,
    species: str,
    trip_date: date,
    score_result: ScoreResult,
) -> RankedZone:
    return RankedZone(
        id=zone.id,
        name=zone.name,
        species=zone.species,
        distance_nm=zone.distance_nm,
        center=ZoneCenter(lat=zone.center_lat, lng=zone.center_lng),
        depth_ft=zone.depth_ft,
        summary=zone.summary,
        sea_surface_temp_f=signals.sea_surface_temp_f,
        temp_gradient_f_per_nm=signals.temp_gradient_f_per_nm,
        nearest_strong_break_distance_nm=signals.nearest_strong_break_distance_nm,
        structure_distance_nm=signals.structure_distance_nm,
        chlorophyll_mg_m3=signals.chlorophyll_mg_m3,
        nearest_strong_chl_break_distance_nm=signals.nearest_strong_chl_break_distance_nm,
        current_speed_kts=signals.current_speed_kts,
        current_break_index=signals.current_break_index,
        weather_risk_index=signals.weather_risk_index,
        score=score_result.total,
        score_breakdown=score_result.breakdown,
        score_weights=score_result.weights,
        weighted_score_breakdown=score_result.weighted_breakdown,
        scored_for_species=species,
        scored_for_date=trip_date,
    )


def build_species_config(config: SpeciesScoringConfigModel) -> SpeciesConfig:
    return SpeciesConfig(
        species=config.species,
        label=config.label,
        season_window=config.season_window,
        notes=config.notes,
        preferred_temp_f=[config.preferred_temp_min_f, config.preferred_temp_max_f],
        ideal_chlorophyll_mg_m3=[config.ideal_chlorophyll_min, config.ideal_chlorophyll_max],
        ideal_current_kts=[config.ideal_current_min_kts, config.ideal_current_max_kts],
        temp_break_config=build_temp_break_config(config.species),
        chlorophyll_break_config=build_chlorophyll_break_config(config.species),
        weights=build_weighted_score_config(config),
    )
