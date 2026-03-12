from dataclasses import dataclass
from datetime import date

from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.schemas import RankedZone, ScoreBreakdown, SpeciesConfig, WeightedScoreConfig, ZoneCenter


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _score_range(value: float, lower: float, upper: float, tolerance: float) -> float:
    if lower <= value <= upper:
        return 1.0
    if value < lower:
        return _clamp(1 - ((lower - value) / tolerance))
    return _clamp(1 - ((value - upper) / tolerance))


def _score_gradient(value: float) -> float:
    return _clamp(value / 2.5)


def _score_structure(distance_nm: float) -> float:
    return _clamp(1 - (distance_nm / 6.0))


def _score_current(speed_kts: float, break_index: float, lower: float, upper: float) -> float:
    speed_score = _score_range(speed_kts, lower, upper, tolerance=1.2)
    return _clamp((speed_score * 0.7) + (break_index * 0.3))


def _score_weather(weather_risk_index: float, trip_date: date) -> float:
    seasonal_buffer = 0.06 if trip_date.month in {6, 7, 8, 9} else 0.0
    return _clamp(1 - weather_risk_index + seasonal_buffer)


@dataclass(frozen=True)
class ScoreResult:
    total: float
    breakdown: ScoreBreakdown


class ZoneScoringService:
    def score_zone(
        self,
        zone: ZoneModel,
        config: SpeciesScoringConfigModel,
        trip_date: date,
    ) -> ScoreResult:
        weights = self._weights(config)
        temp_suitability = _score_range(
            zone.sea_surface_temp_f,
            config.preferred_temp_min_f,
            config.preferred_temp_max_f,
            tolerance=6.0,
        )
        temp_gradient = _score_gradient(zone.temp_gradient_f_per_nm)
        structure_proximity = _score_structure(zone.structure_distance_nm)
        chlorophyll_suitability = _score_range(
            zone.chlorophyll_mg_m3,
            config.ideal_chlorophyll_min,
            config.ideal_chlorophyll_max,
            tolerance=0.18,
        )
        current_suitability = _score_current(
            zone.current_speed_kts,
            zone.current_break_index,
            config.ideal_current_min_kts,
            config.ideal_current_max_kts,
        )
        weather_fishability = _score_weather(zone.weather_risk_index, trip_date)

        breakdown = ScoreBreakdown(
            temp_suitability=round(temp_suitability * 100, 1),
            temp_gradient=round(temp_gradient * 100, 1),
            structure_proximity=round(structure_proximity * 100, 1),
            chlorophyll_suitability=round(chlorophyll_suitability * 100, 1),
            current_suitability=round(current_suitability * 100, 1),
            weather_fishability=round(weather_fishability * 100, 1),
        )

        total = (
            temp_suitability * weights.temp_suitability
            + temp_gradient * weights.temp_gradient
            + structure_proximity * weights.structure_proximity
            + chlorophyll_suitability * weights.chlorophyll_suitability
            + current_suitability * weights.current_suitability
            + weather_fishability * weights.weather_fishability
        )

        return ScoreResult(total=round(total * 100, 1), breakdown=breakdown)

    @staticmethod
    def _weights(config: SpeciesScoringConfigModel) -> WeightedScoreConfig:
        raw_weights = WeightedScoreConfig(
            temp_suitability=config.temp_suitability_weight,
            temp_gradient=config.temp_gradient_weight,
            structure_proximity=config.structure_proximity_weight,
            chlorophyll_suitability=config.chlorophyll_suitability_weight,
            current_suitability=config.current_suitability_weight,
            weather_fishability=config.weather_fishability_weight,
        )
        total_weight = sum(raw_weights.model_dump().values())
        if total_weight <= 0:
            equal_weight = round(1 / 6, 4)
            return WeightedScoreConfig(
                temp_suitability=equal_weight,
                temp_gradient=equal_weight,
                structure_proximity=equal_weight,
                chlorophyll_suitability=equal_weight,
                current_suitability=equal_weight,
                weather_fishability=equal_weight,
            )

        normalized = {key: value / total_weight for key, value in raw_weights.model_dump().items()}
        return WeightedScoreConfig(**normalized)


def build_species_config(config: SpeciesScoringConfigModel) -> SpeciesConfig:
    return SpeciesConfig(
        species=config.species,
        label=config.label,
        season_window=config.season_window,
        notes=config.notes,
        preferred_temp_f=[config.preferred_temp_min_f, config.preferred_temp_max_f],
        ideal_chlorophyll_mg_m3=[config.ideal_chlorophyll_min, config.ideal_chlorophyll_max],
        ideal_current_kts=[config.ideal_current_min_kts, config.ideal_current_max_kts],
        weights=ZoneScoringService._weights(config),
    )


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
