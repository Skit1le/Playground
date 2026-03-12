from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SpeciesScoringConfigModel(Base):
    __tablename__ = "species_scoring_configs"

    species: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    season_window: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_temp_min_f: Mapped[float] = mapped_column(Float, nullable=False)
    preferred_temp_max_f: Mapped[float] = mapped_column(Float, nullable=False)
    ideal_chlorophyll_min: Mapped[float] = mapped_column(Float, nullable=False)
    ideal_chlorophyll_max: Mapped[float] = mapped_column(Float, nullable=False)
    ideal_current_min_kts: Mapped[float] = mapped_column(Float, nullable=False)
    ideal_current_max_kts: Mapped[float] = mapped_column(Float, nullable=False)
    temp_suitability_weight: Mapped[float] = mapped_column(Float, nullable=False)
    temp_gradient_weight: Mapped[float] = mapped_column(Float, nullable=False)
    structure_proximity_weight: Mapped[float] = mapped_column(Float, nullable=False)
    chlorophyll_suitability_weight: Mapped[float] = mapped_column(Float, nullable=False)
    current_suitability_weight: Mapped[float] = mapped_column(Float, nullable=False)
    weather_fishability_weight: Mapped[float] = mapped_column(Float, nullable=False)


class ZoneModel(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    species: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False)
    distance_nm: Mapped[int] = mapped_column(Integer, nullable=False)
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    center_lng: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    sea_surface_temp_f: Mapped[float] = mapped_column(Float, nullable=False)
    temp_gradient_f_per_nm: Mapped[float] = mapped_column(Float, nullable=False)
    structure_distance_nm: Mapped[float] = mapped_column(Float, nullable=False)
    chlorophyll_mg_m3: Mapped[float] = mapped_column(Float, nullable=False)
    current_speed_kts: Mapped[float] = mapped_column(Float, nullable=False)
    current_break_index: Mapped[float] = mapped_column(Float, nullable=False)
    weather_risk_index: Mapped[float] = mapped_column(Float, nullable=False)
    depth_ft: Mapped[int] = mapped_column(Integer, nullable=False)
