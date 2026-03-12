from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable, Protocol

from app.ingested_products import load_processed_product

_MISSING_POINTS: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True)
class StructureObservation:
    structure_distance_nm: float


class StructureProvider(Protocol):
    def get_zone_structure(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> StructureObservation: ...


class StructureDataUnavailableError(RuntimeError):
    pass


def _nautical_miles_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_nm = 3440.065
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    haversine = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    return 2 * radius_nm * asin(sqrt(haversine))


class ProcessedStructureAdapter:
    def __init__(
        self,
        *,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        load_product: Callable[[str, str, float, float, float, float], dict[str, Any]] = load_processed_product,
    ):
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.load_product = load_product

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str) -> tuple[tuple[float, float, float], ...]:
        try:
            payload = self.load_product(
                "structure",
                target_date,
                self.min_lat,
                self.max_lat,
                self.min_lon,
                self.max_lon,
            )
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return _MISSING_POINTS

        grid = payload.get("grid")
        if not isinstance(grid, list) or not grid:
            return _MISSING_POINTS

        points: list[tuple[float, float, float]] = []
        for point in grid:
            try:
                points.append((float(point["latitude"]), float(point["longitude"]), float(point["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(points)

    @lru_cache(maxsize=256)
    def get_zone_structure(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> StructureObservation:
        points = self._load_points(trip_date.isoformat())
        if not points:
            raise StructureDataUnavailableError(f"No processed structure payload found for {trip_date.isoformat()}.")

        candidates: list[float] = []
        for point_lat, point_lon, point_value in points:
            if point_value <= 0:
                continue
            candidates.append(_nautical_miles_between(latitude, longitude, point_lat, point_lon))

        if not candidates:
            raise StructureDataUnavailableError(
                f"Processed structure payload for {trip_date.isoformat()} had no valid points for zone '{zone_id}'."
            )

        return StructureObservation(structure_distance_nm=round(min(candidates), 4))
