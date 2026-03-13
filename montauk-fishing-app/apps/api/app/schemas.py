from datetime import date as DateValue, datetime as DateTimeValue
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    database: str


class ZoneCenter(BaseModel):
    lat: float
    lng: float


class ScoreBreakdown(BaseModel):
    temp_suitability: float
    temp_gradient: float
    temp_break_proximity: float = 0.0
    edge_alignment: float = 0.0
    structure_proximity: float
    chlorophyll_suitability: float
    chlorophyll_break_proximity: float = 0.0
    current_suitability: float
    weather_fishability: float


class WeightedScoreConfig(BaseModel):
    temp_suitability: float
    temp_gradient: float
    temp_break_proximity: float = 0.0
    edge_alignment: float = 0.0
    structure_proximity: float
    chlorophyll_suitability: float
    chlorophyll_break_proximity: float = 0.0
    current_suitability: float
    weather_fishability: float


class TempBreakConfig(BaseModel):
    strong_break_threshold_f_per_nm: float
    full_score_distance_nm: float
    zero_score_distance_nm: float
    factor_weight: float


class ChlorophyllBreakConfig(BaseModel):
    strong_break_threshold_mg_m3_per_nm: float
    full_score_distance_nm: float
    zero_score_distance_nm: float
    factor_weight: float


class WeightedScoreBreakdown(BaseModel):
    temp_suitability: float
    temp_gradient: float
    temp_break_proximity: float = 0.0
    edge_alignment: float = 0.0
    structure_proximity: float
    chlorophyll_suitability: float
    chlorophyll_break_proximity: float = 0.0
    current_suitability: float
    weather_fishability: float


class ScoreExplanationFactor(BaseModel):
    factor: str
    label: str
    raw_value: str
    score: float
    weighted_contribution: float
    reason: str


class ZoneScoreExplanation(BaseModel):
    headline: str
    summary: str
    best_use_case_summary: str
    confidence_score: float
    watchouts: list[str]
    top_reasons: list[str]
    factors: list[ScoreExplanationFactor]


class SpeciesConfig(BaseModel):
    species: str
    label: str
    season_window: str
    notes: str
    preferred_temp_f: list[float]
    ideal_chlorophyll_mg_m3: list[float]
    ideal_current_kts: list[float]
    temp_break_config: TempBreakConfig | None = None
    chlorophyll_break_config: ChlorophyllBreakConfig | None = None
    weights: WeightedScoreConfig


class RankedZone(BaseModel):
    id: str
    name: str
    species: list[str]
    distance_nm: int
    center: ZoneCenter
    depth_ft: int
    summary: str
    sea_surface_temp_f: float
    temp_gradient_f_per_nm: float
    nearest_strong_break_distance_nm: float | None = None
    structure_distance_nm: float
    chlorophyll_mg_m3: float
    nearest_strong_chl_break_distance_nm: float | None = None
    current_speed_kts: float
    current_break_index: float
    weather_risk_index: float
    score: float
    score_breakdown: ScoreBreakdown
    score_weights: WeightedScoreConfig
    weighted_score_breakdown: WeightedScoreBreakdown
    score_explanation: ZoneScoreExplanation
    scored_for_species: str
    scored_for_date: DateValue


class TripLog(BaseModel):
    id: str
    date: str
    zone_id: str
    species: list[str]
    vessel: str
    catch_count: int
    notes: str


class ZoneQuery(BaseModel):
    date: DateValue
    species: str = Field(pattern="^(bluefin|yellowfin|mahi)$")


class SstMapPolygonGeometry(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class SstMapFeatureProperties(BaseModel):
    sea_surface_temp_f: float
    break_intensity_f_per_nm: float


class SstMapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: SstMapPolygonGeometry
    properties: SstMapFeatureProperties


class SstMapFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SstMapFeature]


class SstMapMetadata(BaseModel):
    date: DateValue
    bbox: list[float]
    source: str
    dataset_id: str | None = None
    units: Literal["fahrenheit"] = "fahrenheit"
    point_count: int
    cell_count: int
    temp_range_f: list[float] | None = None
    break_intensity_range: list[float] | None = None
    grid_resolution: list[int] | None = None


class SstMapResponse(BaseModel):
    metadata: SstMapMetadata
    data: SstMapFeatureCollection


class ChlorophyllBreakMapPolygonGeometry(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class ChlorophyllBreakMapFeatureProperties(BaseModel):
    chlorophyll_mg_m3: float
    break_intensity_mg_m3_per_nm: float


class ChlorophyllBreakMapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: ChlorophyllBreakMapPolygonGeometry
    properties: ChlorophyllBreakMapFeatureProperties


class ChlorophyllBreakMapFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[ChlorophyllBreakMapFeature]


class ChlorophyllBreakMapMetadata(BaseModel):
    date: DateValue
    bbox: list[float]
    source: str
    dataset_id: str | None = None
    units: Literal["mg_m3"] = "mg_m3"
    point_count: int
    cell_count: int
    chlorophyll_range_mg_m3: list[float] | None = None
    break_intensity_range_mg_m3_per_nm: list[float] | None = None
    grid_resolution: list[int] | None = None


class ChlorophyllBreakMapResponse(BaseModel):
    metadata: ChlorophyllBreakMapMetadata
    data: ChlorophyllBreakMapFeatureCollection


class TripOutcomeRecord(BaseModel):
    id: str
    date: DateValue
    target_species: str
    zone_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    catch_success: float = Field(ge=0.0, le=1.0)
    catch_count: int = 0
    vessel: str
    notes: str = ""


class TripOutcomeCreate(BaseModel):
    date: DateValue
    target_species: str
    zone_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    catch_success: float = Field(ge=0.0, le=1.0)
    catch_count: int = 0
    vessel: str
    notes: str = ""


class TripOutcomeUpdate(BaseModel):
    date: DateValue | None = None
    target_species: str | None = None
    zone_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    catch_success: float | None = Field(default=None, ge=0.0, le=1.0)
    catch_count: int | None = None
    vessel: str | None = None
    notes: str | None = None


class HistoricalZoneScoreSnapshot(BaseModel):
    date: DateValue
    species: str
    zone_id: str
    score: float
    score_breakdown: ScoreBreakdown
    score_weights: WeightedScoreConfig | None = None
    weighted_score_breakdown: WeightedScoreBreakdown


class HistoricalZoneScoreSnapshotRecord(BaseModel):
    id: int
    date: DateValue
    species: str
    zone_id: str
    zone_name: str
    score: float
    score_breakdown: ScoreBreakdown
    score_weights: WeightedScoreConfig
    weighted_score_breakdown: WeightedScoreBreakdown
    environmental_snapshot: dict[str, float | str | None]
    recorded_at: DateTimeValue


class ZoneSnapshotCaptureResponse(BaseModel):
    trip_date: DateValue
    species: str
    captured_count: int
    snapshots: list[HistoricalZoneScoreSnapshotRecord]


class OutcomeCalibrationGap(BaseModel):
    zone_id: str
    species: str
    predicted_score: float
    actual_success: float
    score_error: float


class OutcomeBacktestReport(BaseModel):
    outcome_count: int
    compared_count: int
    mean_absolute_error: float | None = None
    largest_gaps: list[OutcomeCalibrationGap]
