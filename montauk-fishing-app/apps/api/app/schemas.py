from datetime import date
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
    structure_proximity: float
    chlorophyll_suitability: float
    current_suitability: float
    weather_fishability: float


class WeightedScoreConfig(BaseModel):
    temp_suitability: float
    temp_gradient: float
    structure_proximity: float
    chlorophyll_suitability: float
    current_suitability: float
    weather_fishability: float


class WeightedScoreBreakdown(BaseModel):
    temp_suitability: float
    temp_gradient: float
    structure_proximity: float
    chlorophyll_suitability: float
    current_suitability: float
    weather_fishability: float


class SpeciesConfig(BaseModel):
    species: str
    label: str
    season_window: str
    notes: str
    preferred_temp_f: list[float]
    ideal_chlorophyll_mg_m3: list[float]
    ideal_current_kts: list[float]
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
    structure_distance_nm: float
    chlorophyll_mg_m3: float
    current_speed_kts: float
    current_break_index: float
    weather_risk_index: float
    score: float
    score_breakdown: ScoreBreakdown
    score_weights: WeightedScoreConfig
    weighted_score_breakdown: WeightedScoreBreakdown
    scored_for_species: str
    scored_for_date: date


class TripLog(BaseModel):
    id: str
    date: str
    zone_id: str
    species: list[str]
    vessel: str
    catch_count: int
    notes: str


class ZoneQuery(BaseModel):
    date: date
    species: str = Field(pattern="^(bluefin|yellowfin|mahi)$")


class SstMapPolygonGeometry(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]


class SstMapFeatureProperties(BaseModel):
    sea_surface_temp_f: float


class SstMapFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: SstMapPolygonGeometry
    properties: SstMapFeatureProperties


class SstMapFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SstMapFeature]


class SstMapMetadata(BaseModel):
    date: date
    bbox: list[float]
    source: str
    dataset_id: str | None = None
    units: Literal["fahrenheit"] = "fahrenheit"
    point_count: int
    cell_count: int
    temp_range_f: list[float] | None = None


class SstMapResponse(BaseModel):
    metadata: SstMapMetadata
    data: SstMapFeatureCollection
