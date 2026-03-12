from dataclasses import dataclass
from datetime import date

from app.db_models import SpeciesScoringConfigModel
from app.environmental_inputs import ZoneEnvironmentalSignals
from app.schemas import ScoreBreakdown, WeightedScoreBreakdown, WeightedScoreConfig


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _score_range(value: float, lower: float, upper: float, tolerance: float) -> float:
    if lower <= value <= upper:
        return 1.0
    if value < lower:
        return _clamp(1 - ((lower - value) / tolerance))
    return _clamp(1 - ((value - upper) / tolerance))


def _score_temperature(value: float, config: SpeciesScoringConfigModel) -> float:
    lower_tolerance = 6.0
    upper_tolerance = 6.0

    if config.species == "bluefin":
        lower_tolerance = 7.0
        upper_tolerance = 9.0

    if config.preferred_temp_min_f <= value <= config.preferred_temp_max_f:
        return 1.0
    if value < config.preferred_temp_min_f:
        return _clamp(1 - ((config.preferred_temp_min_f - value) / lower_tolerance))
    return _clamp(1 - ((value - config.preferred_temp_max_f) / upper_tolerance))


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
    weights: WeightedScoreConfig
    weighted_breakdown: WeightedScoreBreakdown


class ZoneScoringEngine:
    def score(
        self,
        signals: ZoneEnvironmentalSignals,
        config: SpeciesScoringConfigModel,
        trip_date: date,
    ) -> ScoreResult:
        weights = build_weighted_score_config(config)
        temp_suitability = _score_temperature(signals.sea_surface_temp_f, config)
        temp_gradient = _score_gradient(signals.temp_gradient_f_per_nm)
        structure_proximity = _score_structure(signals.structure_distance_nm)
        chlorophyll_suitability = _score_range(
            signals.chlorophyll_mg_m3,
            config.ideal_chlorophyll_min,
            config.ideal_chlorophyll_max,
            tolerance=0.18,
        )
        current_suitability = _score_current(
            signals.current_speed_kts,
            signals.current_break_index,
            config.ideal_current_min_kts,
            config.ideal_current_max_kts,
        )
        weather_fishability = _score_weather(signals.weather_risk_index, trip_date)

        breakdown = ScoreBreakdown(
            temp_suitability=round(temp_suitability * 100, 1),
            temp_gradient=round(temp_gradient * 100, 1),
            structure_proximity=round(structure_proximity * 100, 1),
            chlorophyll_suitability=round(chlorophyll_suitability * 100, 1),
            current_suitability=round(current_suitability * 100, 1),
            weather_fishability=round(weather_fishability * 100, 1),
        )
        weighted_breakdown = WeightedScoreBreakdown(
            temp_suitability=round(temp_suitability * weights.temp_suitability * 100, 1),
            temp_gradient=round(temp_gradient * weights.temp_gradient * 100, 1),
            structure_proximity=round(structure_proximity * weights.structure_proximity * 100, 1),
            chlorophyll_suitability=round(chlorophyll_suitability * weights.chlorophyll_suitability * 100, 1),
            current_suitability=round(current_suitability * weights.current_suitability * 100, 1),
            weather_fishability=round(weather_fishability * weights.weather_fishability * 100, 1),
        )

        total = (
            temp_suitability * weights.temp_suitability
            + temp_gradient * weights.temp_gradient
            + structure_proximity * weights.structure_proximity
            + chlorophyll_suitability * weights.chlorophyll_suitability
            + current_suitability * weights.current_suitability
            + weather_fishability * weights.weather_fishability
        )

        return ScoreResult(
            total=round(total * 100, 1),
            breakdown=breakdown,
            weights=weights,
            weighted_breakdown=weighted_breakdown,
        )


def build_weighted_score_config(config: SpeciesScoringConfigModel) -> WeightedScoreConfig:
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
