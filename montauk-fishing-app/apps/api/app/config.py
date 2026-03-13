from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "Montauk Fishing API"
    api_env: str = "development"
    database_url: str = "postgresql://montauk:montauk@localhost:5432/montauk"
    database_connect_timeout_seconds: int = Field(default=1, alias="DATABASE_CONNECT_TIMEOUT_SECONDS")
    default_zone_limit: int = 10
    database_required_on_startup: bool = Field(default=False, alias="DATABASE_REQUIRED_ON_STARTUP")
    database_startup_max_attempts: int = Field(default=3, alias="DATABASE_STARTUP_MAX_ATTEMPTS")
    database_startup_delay_seconds: int = Field(default=1, alias="DATABASE_STARTUP_DELAY_SECONDS")
    processed_lookup_timeout_seconds: float = Field(default=0.75, alias="PROCESSED_LOOKUP_TIMEOUT_SECONDS")
    live_sst_enabled: bool = Field(default=False, alias="LIVE_SST_ENABLED")
    live_sst_timeout_seconds: float = Field(default=2.0, alias="LIVE_SST_TIMEOUT_SECONDS")
    live_sst_base_url: str = Field(
        default="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
        alias="LIVE_SST_BASE_URL",
    )
    live_sst_dataset_id: str = Field(
        default="CONFIGURE_NOAA_COASTWATCH_SST_DATASET_ID",
        alias="LIVE_SST_DATASET_ID",
    )
    live_sst_variable_name: str = Field(
        default="sea_surface_temperature",
        alias="LIVE_SST_VARIABLE_NAME",
    )
    live_sst_time_suffix: str = Field(default="T12:00:00Z", alias="LIVE_SST_TIME_SUFFIX")
    live_sst_extra_selectors: str = Field(default="", alias="LIVE_SST_EXTRA_SELECTORS")
    live_sst_longitude_mode: str = Field(default="signed", alias="LIVE_SST_LONGITUDE_MODE")
    sst_bbox_min_lat: float = Field(default=39.8, alias="SST_BBOX_MIN_LAT")
    sst_bbox_max_lat: float = Field(default=41.4, alias="SST_BBOX_MAX_LAT")
    sst_bbox_min_lon: float = Field(default=-72.4, alias="SST_BBOX_MIN_LON")
    sst_bbox_max_lon: float = Field(default=-69.8, alias="SST_BBOX_MAX_LON")
    sst_gradient_radius_nm: float = Field(default=18.0, alias="SST_GRADIENT_RADIUS_NM")
    chlorophyll_bbox_min_lat: float = Field(default=39.8, alias="CHLOROPHYLL_BBOX_MIN_LAT")
    chlorophyll_bbox_max_lat: float = Field(default=41.4, alias="CHLOROPHYLL_BBOX_MAX_LAT")
    chlorophyll_bbox_min_lon: float = Field(default=-72.4, alias="CHLOROPHYLL_BBOX_MIN_LON")
    chlorophyll_bbox_max_lon: float = Field(default=-69.8, alias="CHLOROPHYLL_BBOX_MAX_LON")
    live_chlorophyll_enabled: bool = Field(default=False, alias="LIVE_CHLOROPHYLL_ENABLED")
    live_chlorophyll_timeout_seconds: float = Field(default=2.0, alias="LIVE_CHLOROPHYLL_TIMEOUT_SECONDS")
    live_chlorophyll_base_url: str = Field(
        default="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
        alias="LIVE_CHLOROPHYLL_BASE_URL",
    )
    live_chlorophyll_dataset_id: str = Field(
        default="CONFIGURE_NOAA_COASTWATCH_CHLOROPHYLL_DATASET_ID",
        alias="LIVE_CHLOROPHYLL_DATASET_ID",
    )
    live_chlorophyll_variable_name: str = Field(
        default="chlorophyll",
        alias="LIVE_CHLOROPHYLL_VARIABLE_NAME",
    )
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
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001",
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
