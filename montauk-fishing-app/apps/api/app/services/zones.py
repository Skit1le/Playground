import logging
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
from app.scoring import ScoreResult, ZoneScoringEngine, build_weighted_score_config
from app.schemas import RankedZone, SpeciesConfig, ZoneCenter

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
    ):
        self.zone_repository = zone_repository
        self.species_config_repository = species_config_repository
        self.scoring_engine = scoring_engine or ZoneScoringEngine()
        self.environmental_input_provider = environmental_input_provider or ZoneEnvironmentalInputService()

    def list_ranked_zones(self, species: str, trip_date: date, limit: int) -> list[RankedZone]:
        started_at = perf_counter()
        config = self.species_config_repository.get_by_species(species)
        if config is None:
            raise SpeciesConfigNotFoundError(f"No scoring configuration found for species '{species}'.")

        zones = self.zone_repository.list_for_species(species)
        ranked_zones = [
            self._score_zone(zone=zone, config=config, species=species, trip_date=trip_date)
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
    ) -> RankedZone:
        resolved_inputs = self._resolve_zone_inputs(zone, trip_date)
        score_result = self.scoring_engine.score(resolved_inputs.signals, config, trip_date)
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
        return build_ranked_zone(zone, resolved_inputs.signals, species, trip_date, score_result)

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
        structure_distance_nm=signals.structure_distance_nm,
        chlorophyll_mg_m3=signals.chlorophyll_mg_m3,
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
        weights=build_weighted_score_config(config),
    )
