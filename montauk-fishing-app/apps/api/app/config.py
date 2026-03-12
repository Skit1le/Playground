from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Montauk Fishing API"
    api_env: str = "development"
    database_url: str = "postgresql://montauk:montauk@localhost:5432/montauk"
    default_zone_limit: int = 10
    sst_bbox_min_lat: float = Field(default=39.8, alias="SST_BBOX_MIN_LAT")
    sst_bbox_max_lat: float = Field(default=41.4, alias="SST_BBOX_MAX_LAT")
    sst_bbox_min_lon: float = Field(default=-72.4, alias="SST_BBOX_MIN_LON")
    sst_bbox_max_lon: float = Field(default=-69.8, alias="SST_BBOX_MAX_LON")
    sst_gradient_radius_nm: float = Field(default=18.0, alias="SST_GRADIENT_RADIUS_NM")
    chlorophyll_bbox_min_lat: float = Field(default=39.8, alias="CHLOROPHYLL_BBOX_MIN_LAT")
    chlorophyll_bbox_max_lat: float = Field(default=41.4, alias="CHLOROPHYLL_BBOX_MAX_LAT")
    chlorophyll_bbox_min_lon: float = Field(default=-72.4, alias="CHLOROPHYLL_BBOX_MIN_LON")
    chlorophyll_bbox_max_lon: float = Field(default=-69.8, alias="CHLOROPHYLL_BBOX_MAX_LON")
    current_bbox_min_lat: float = Field(default=39.8, alias="CURRENT_BBOX_MIN_LAT")
    current_bbox_max_lat: float = Field(default=41.4, alias="CURRENT_BBOX_MAX_LAT")
    current_bbox_min_lon: float = Field(default=-72.4, alias="CURRENT_BBOX_MIN_LON")
    current_bbox_max_lon: float = Field(default=-69.8, alias="CURRENT_BBOX_MAX_LON")
    current_break_radius_nm: float = Field(default=18.0, alias="CURRENT_BREAK_RADIUS_NM")
    structure_bbox_min_lat: float = Field(default=39.8, alias="STRUCTURE_BBOX_MIN_LAT")
    structure_bbox_max_lat: float = Field(default=41.4, alias="STRUCTURE_BBOX_MAX_LAT")
    structure_bbox_min_lon: float = Field(default=-72.4, alias="STRUCTURE_BBOX_MIN_LON")
    structure_bbox_max_lon: float = Field(default=-69.8, alias="STRUCTURE_BBOX_MAX_LON")
    weather_bbox_min_lat: float = Field(default=39.8, alias="WEATHER_BBOX_MIN_LAT")
    weather_bbox_max_lat: float = Field(default=41.4, alias="WEATHER_BBOX_MAX_LAT")
    weather_bbox_min_lon: float = Field(default=-72.4, alias="WEATHER_BBOX_MIN_LON")
    weather_bbox_max_lon: float = Field(default=-69.8, alias="WEATHER_BBOX_MAX_LON")
    allowed_origins_raw: str = Field(
        default="http://localhost:3000",
        alias="ALLOWED_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=(API_ROOT / ".env", ".env"),
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins_raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
