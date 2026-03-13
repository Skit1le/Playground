from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint, func
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
    depth_ft: Mapped[int] = mapped_column(Integer, nullable=False)


class TripOutcomeModel(Base):
    __tablename__ = "trip_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    target_species: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    catch_success: Mapped[float] = mapped_column(Float, nullable=False)
    catch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vessel: Mapped[str] = mapped_column(String(128), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class HistoricalZoneScoreSnapshotModel(Base):
    __tablename__ = "historical_zone_score_snapshots"
    __table_args__ = (
        UniqueConstraint("date", "species", "zone_id", name="uq_zone_score_snapshot_date_species_zone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    species: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    zone_name: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    score_weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    weighted_score_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    environmental_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
