import logging
from dataclasses import replace
from time import perf_counter
from datetime import date

from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.environmental_inputs import (
    EnvironmentalInputProvider,
    ResolvedZoneEnvironmentalInputs,
    ZoneSignalSourceMetadata,
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
from app.schemas import (
    RankedZone,
    ScoreExplanationFactor,
    SignalSourceMetadata,
    SpeciesConfig,
    ZoneCenter,
    ZoneScoreExplanation,
    ZoneSourceMetadata,
)
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
        return build_ranked_zone(zone, signals, species, trip_date, score_result, resolved_inputs.metadata)

    def _resolve_zone_inputs(self, zone: ZoneModel, trip_date: date) -> ResolvedZoneEnvironmentalInputs:
        if hasattr(self.environmental_input_provider, "resolve_zone_inputs"):
            return self.environmental_input_provider.resolve_zone_inputs(zone, trip_date)
        return ResolvedZoneEnvironmentalInputs(
            signals=self.environmental_input_provider.get_zone_signals(zone, trip_date),
            metadata=ZoneEnvironmentalSourceMetadata(
                sst=ZoneSignalSourceMetadata(source="unknown"),
                chlorophyll=ZoneSignalSourceMetadata(source="unknown"),
                current=ZoneSignalSourceMetadata(source="unknown"),
                bathymetry=ZoneSignalSourceMetadata(source="unknown"),
                weather=ZoneSignalSourceMetadata(source="unknown"),
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
    source_metadata: ZoneEnvironmentalSourceMetadata,
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
        score_explanation=build_zone_score_explanation(zone, signals, species, score_result, source_metadata),
        source_metadata=_build_zone_source_metadata(source_metadata),
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


def build_zone_score_explanation(
    zone: ZoneModel,
    signals: ZoneEnvironmentalSignals,
    species: str,
    score_result: ScoreResult,
    source_metadata: ZoneEnvironmentalSourceMetadata,
) -> ZoneScoreExplanation:
    factors = [
        ScoreExplanationFactor(
            factor="temp_suitability",
            label="Species temperature fit",
            raw_value=f"{signals.sea_surface_temp_f:.1f} F",
            score=score_result.breakdown.temp_suitability,
            weighted_contribution=score_result.weighted_breakdown.temp_suitability,
            reason=f"Water temperature lines up with the preferred {species} range.",
        ),
        ScoreExplanationFactor(
            factor="temp_break_proximity",
            label="SST break proximity",
            raw_value=_format_distance(signals.nearest_strong_break_distance_nm),
            score=score_result.breakdown.temp_break_proximity,
            weighted_contribution=score_result.weighted_breakdown.temp_break_proximity,
            reason="Closer zones sit nearer to meaningful temperature breaks where bait and pelagics often stack.",
        ),
        ScoreExplanationFactor(
            factor="chlorophyll_break_proximity",
            label="Chlorophyll edge proximity",
            raw_value=_format_distance(signals.nearest_strong_chl_break_distance_nm),
            score=score_result.breakdown.chlorophyll_break_proximity,
            weighted_contribution=score_result.weighted_breakdown.chlorophyll_break_proximity,
            reason="Nearby water-color breaks can mark bait concentration and cleaner feeding lanes.",
        ),
        ScoreExplanationFactor(
            factor="edge_alignment",
            label="Edge overlap",
            raw_value=f"SST {score_result.breakdown.temp_break_proximity:.1f} / CHL {score_result.breakdown.chlorophyll_break_proximity:.1f}",
            score=score_result.breakdown.edge_alignment,
            weighted_contribution=score_result.weighted_breakdown.edge_alignment,
            reason="This bonus only grows when both the temperature front and color edge are nearby together.",
        ),
        ScoreExplanationFactor(
            factor="structure_proximity",
            label="Structure proximity",
            raw_value=f"{signals.structure_distance_nm:.1f} nm",
            score=score_result.breakdown.structure_proximity,
            weighted_contribution=score_result.weighted_breakdown.structure_proximity,
            reason="Nearby contour or structure influence helps hold bait and predators.",
        ),
        ScoreExplanationFactor(
            factor="chlorophyll_suitability",
            label="Chlorophyll suitability",
            raw_value=f"{signals.chlorophyll_mg_m3:.2f} mg/m3",
            score=score_result.breakdown.chlorophyll_suitability,
            weighted_contribution=score_result.weighted_breakdown.chlorophyll_suitability,
            reason="Absolute chlorophyll level still matters separately from the edge itself.",
        ),
        ScoreExplanationFactor(
            factor="current_suitability",
            label="Current setup",
            raw_value=f"{signals.current_speed_kts:.1f} kts / break {signals.current_break_index:.2f}",
            score=score_result.breakdown.current_suitability,
            weighted_contribution=score_result.weighted_breakdown.current_suitability,
            reason="Current speed and current edges help define productive drifts and bait positioning.",
        ),
        ScoreExplanationFactor(
            factor="weather_fishability",
            label="Fishable weather",
            raw_value=f"risk {signals.weather_risk_index:.2f}",
            score=score_result.breakdown.weather_fishability,
            weighted_contribution=score_result.weighted_breakdown.weather_fishability,
            reason="Good scores here mean the zone looks workable, not just theoretically productive.",
        ),
    ]
    ranked_factors = sorted(factors, key=lambda factor: factor.weighted_contribution, reverse=True)
    top_reasons = [
        f"{factor.label}: {factor.reason}"
        for factor in ranked_factors[:3]
        if factor.weighted_contribution > 0
    ]
    return ZoneScoreExplanation(
        headline=f"{zone.name} ranks well for {species} because the water setup is stacking multiple favorable signals.",
        summary=(
            f"SST {signals.sea_surface_temp_f:.1f} F, chlorophyll {signals.chlorophyll_mg_m3:.2f} mg/m3, "
            f"SST break {_format_distance(signals.nearest_strong_break_distance_nm)}, "
            f"chlorophyll break {_format_distance(signals.nearest_strong_chl_break_distance_nm)}."
        ),
        best_use_case_summary=_build_best_use_case_summary(species, signals),
        confidence_score=_build_confidence_score(score_result, source_metadata),
        watchouts=_build_watchouts(signals, score_result, source_metadata),
        top_reasons=top_reasons,
        factors=ranked_factors,
    )


def _format_distance(distance_nm: float | None) -> str:
    if distance_nm is None:
        return "not nearby"
    return f"{distance_nm:.1f} nm"


def _build_signal_source_metadata(signal: ZoneSignalSourceMetadata) -> SignalSourceMetadata:
    return SignalSourceMetadata(
        source=signal.source,
        source_status=signal.source_status,
        live_data_available=signal.live_data_available,
        fallback_used=signal.fallback_used,
        provider_name=signal.provider_name,
        dataset_id=signal.dataset_id,
        resolved_timestamp=signal.resolved_timestamp,
        failure_reason=signal.failure_reason,
        upstream_host=signal.upstream_host,
        attempted_urls=list(signal.attempted_urls),
        provider_diagnostics=signal.provider_diagnostics or {},
        warning_messages=list(signal.warning_messages),
    )


def _build_zone_source_metadata(source_metadata: ZoneEnvironmentalSourceMetadata) -> ZoneSourceMetadata:
    signals = (
        source_metadata.sst,
        source_metadata.chlorophyll,
        source_metadata.current,
        source_metadata.bathymetry,
        source_metadata.weather,
    )
    warning_messages = [
        warning
        for signal in signals
        for warning in signal.warning_messages
    ]
    return ZoneSourceMetadata(
        sst=_build_signal_source_metadata(source_metadata.sst),
        chlorophyll=_build_signal_source_metadata(source_metadata.chlorophyll),
        current=_build_signal_source_metadata(source_metadata.current),
        bathymetry=_build_signal_source_metadata(source_metadata.bathymetry),
        weather=_build_signal_source_metadata(source_metadata.weather),
        live_data_available=any(signal.live_data_available for signal in signals),
        fallback_used=any(signal.fallback_used for signal in signals),
        warning_messages=warning_messages,
    )


def _build_source_confidence_penalty(source_metadata: ZoneEnvironmentalSourceMetadata) -> float:
    penalty_by_source = {
        "sst": {"processed": 3.0, "cached_real": 2.0, "mock": 11.0, "mock_fallback": 14.0, "unavailable": 18.0},
        "chlorophyll": {"processed": 4.0, "cached_real": 2.5, "mock": 14.0, "mock_fallback": 18.0, "unavailable": 22.0},
        "current": {"processed": 1.5, "mock": 5.0, "mock_fallback": 7.0, "unavailable": 10.0},
        "bathymetry": {"processed": 0.0, "mock": 2.0, "mock_fallback": 4.0, "unavailable": 6.0},
        "weather": {"processed": 1.5, "mock": 4.0, "mock_fallback": 6.0, "unavailable": 8.0},
    }
    penalty = 0.0
    penalty += penalty_by_source["sst"].get(source_metadata.sst.source, 0.0)
    penalty += penalty_by_source["chlorophyll"].get(source_metadata.chlorophyll.source, 0.0)
    penalty += penalty_by_source["current"].get(source_metadata.current.source, 0.0)
    penalty += penalty_by_source["bathymetry"].get(source_metadata.bathymetry.source, 0.0)
    penalty += penalty_by_source["weather"].get(source_metadata.weather.source, 0.0)
    return penalty


def _build_source_watchouts(source_metadata: ZoneEnvironmentalSourceMetadata) -> list[str]:
    watchouts: list[str] = []
    if source_metadata.chlorophyll.source in {"mock", "mock_fallback", "unavailable"}:
        watchouts.append(
            "Chlorophyll is estimated for this request, so edge confidence is lower than when live satellite color is available."
        )
    elif source_metadata.chlorophyll.source == "cached_real":
        watchouts.append(
            "Chlorophyll is coming from the last known good real feed, so the color edge may be slightly older than the latest live water."
        )
    elif source_metadata.chlorophyll.source == "processed":
        watchouts.append(
            "Chlorophyll is coming from cached imagery for this request, so the color edge may lag the latest live water."
        )
    if source_metadata.sst.source in {"mock", "mock_fallback", "unavailable"}:
        watchouts.append(
            "SST support is estimated for this request, so the exact break position may be softer than the score suggests."
        )
    elif source_metadata.sst.source == "cached_real":
        watchouts.append("SST is coming from the last known good real feed, so the exact break may lag the latest live water slightly.")
    elif source_metadata.sst.source == "processed":
        watchouts.append("SST is coming from cached processed water, not the freshest live grid.")
    if source_metadata.current.source in {"mock", "mock_fallback", "unavailable"}:
        watchouts.append("Current setup is estimated here, so drift quality may differ from the model when you arrive.")
    if source_metadata.weather.source in {"mock", "mock_fallback", "unavailable"}:
        watchouts.append("Weather fishability is estimated for this request, so ride quality could tighten faster than expected.")
    return watchouts


def _build_confidence_score(score_result: ScoreResult, source_metadata: ZoneEnvironmentalSourceMetadata) -> float:
    positive_factors = [
        contribution
        for contribution in score_result.weighted_breakdown.model_dump().values()
        if contribution > 0
    ]
    concentration_bonus = min(len(positive_factors), 6) / 6
    fallback_penalty = _build_source_confidence_penalty(source_metadata)
    confidence_score = min(100.0, (score_result.total * 0.78) + (concentration_bonus * 22))
    return round(max(22.0, confidence_score - fallback_penalty), 1)


def _build_watchouts(
    signals: ZoneEnvironmentalSignals,
    score_result: ScoreResult,
    source_metadata: ZoneEnvironmentalSourceMetadata,
) -> list[str]:
    watchouts: list[str] = []
    if signals.weather_risk_index >= 0.35:
        watchouts.append("Weather risk is elevated enough that fishability could drop faster than the score implies.")
    if signals.nearest_strong_break_distance_nm is None or signals.nearest_strong_break_distance_nm > 8:
        watchouts.append("Temperature break support is not especially tight, so the edge could feel less defined on arrival.")
    if signals.nearest_strong_chl_break_distance_nm is None or signals.nearest_strong_chl_break_distance_nm > 8:
        watchouts.append("Chlorophyll edge support is loose, so water color may not be as crisp as the best overlap zones.")
    if score_result.breakdown.temp_suitability < 45:
        watchouts.append("The water temperature is workable, but it is outside the strongest part of the preferred species band.")
    if score_result.breakdown.structure_proximity < 45:
        watchouts.append("Structure influence is lighter here, so the area may need visible life before it earns a full commitment.")
    for source_watchout in _build_source_watchouts(source_metadata):
        if source_watchout not in watchouts:
            watchouts.append(source_watchout)
    return watchouts[:3]


def _build_best_use_case_summary(species: str, signals: ZoneEnvironmentalSignals) -> str:
    edge_summary = (
        f"SST break {_format_distance(signals.nearest_strong_break_distance_nm)} and "
        f"chlorophyll break {_format_distance(signals.nearest_strong_chl_break_distance_nm)}"
    )
    if species == "bluefin":
        return f"Best for a disciplined bluefin start where you want defined edge water with nearby structure support. {edge_summary}."
    if species == "yellowfin":
        return f"Best for working warmer offshore edge water where current and color transitions can hold yellowfin through the day. {edge_summary}."
    if species == "mahi":
        return f"Best for hunting cleaner warm water, current seams, and surface life where mahi can stack around subtle edges. {edge_summary}."
    return f"Best when you want multiple environmental edges lining up instead of relying on one single signal. {edge_summary}."
