from datetime import date

from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.environmental_inputs import EnvironmentalInputProvider, MockEnvironmentalInputProvider
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.scoring import ScoreResult, ZoneScoringEngine, build_weighted_score_config
from app.schemas import RankedZone, SpeciesConfig, ZoneCenter


class SpeciesConfigNotFoundError(ValueError):
    pass


class ZoneRankingService:
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
        self.environmental_input_provider = environmental_input_provider or MockEnvironmentalInputProvider()

    def rank_zones(self, species: str, trip_date: date, limit: int) -> list[RankedZone]:
        config = self.species_config_repository.get_by_species(species)
        if config is None:
            raise SpeciesConfigNotFoundError(f"No scoring configuration found for species '{species}'.")

        zones = self.zone_repository.list_for_species(species)
        ranked_zones = []
        for zone in zones:
            signals = self.environmental_input_provider.get_zone_signals(zone, trip_date)
            score_result = self.scoring_engine.score(signals, config, trip_date)
            ranked_zones.append(build_ranked_zone(zone, species, trip_date, score_result))

        ranked_zones.sort(key=lambda zone: zone.score, reverse=True)
        return ranked_zones[:limit]

    def list_species_configs(self) -> list[SpeciesConfig]:
        return [build_species_config(config) for config in self.species_config_repository.list_all()]


# Response schema remains unchanged; this mapper only centralizes transformation.
def build_ranked_zone(
    zone: ZoneModel,
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
        sea_surface_temp_f=zone.sea_surface_temp_f,
        temp_gradient_f_per_nm=zone.temp_gradient_f_per_nm,
        structure_distance_nm=zone.structure_distance_nm,
        chlorophyll_mg_m3=zone.chlorophyll_mg_m3,
        current_speed_kts=zone.current_speed_kts,
        current_break_index=zone.current_break_index,
        weather_risk_index=zone.weather_risk_index,
        score=score_result.total,
        score_breakdown=score_result.breakdown,
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
