from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable, Protocol

from app.ingested_products import load_processed_product


@dataclass(frozen=True)
class CurrentObservation:
    current_speed_kts: float
    current_break_index: float


class CurrentProvider(Protocol):
    def get_zone_current(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> CurrentObservation: ...


class CurrentDataUnavailableError(RuntimeError):
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


class ProcessedCurrentAdapter:
    def __init__(
        self,
        *,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        break_radius_nm: float = 18.0,
        load_product: Callable[[str, str, float, float, float, float], dict[str, Any]] = load_processed_product,
    ):
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.break_radius_nm = break_radius_nm
        self.load_product = load_product

    @lru_cache(maxsize=32)
    def _load_payload(self, target_date: str) -> dict[str, Any]:
        try:
            payload = self.load_product(
                "current",
                target_date,
                self.min_lat,
                self.max_lat,
                self.min_lon,
                self.max_lon,
            )
        except FileNotFoundError as exc:
            raise CurrentDataUnavailableError(f"No processed current payload found for {target_date}.") from exc

        grid = payload.get("grid")
        if not isinstance(grid, list) or not grid:
            raise CurrentDataUnavailableError(
                f"Processed current payload for {target_date} did not contain a usable grid."
            )
        return payload

    @lru_cache(maxsize=256)
    def get_zone_current(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> CurrentObservation:
        payload = self._load_payload(trip_date.isoformat())
        grid = payload["grid"]

        candidates: list[tuple[float, float]] = []
        for point in grid:
            try:
                point_lat = float(point["latitude"])
                point_lon = float(point["longitude"])
                point_value = float(point["value"])
            except (KeyError, TypeError, ValueError):
                continue
            distance_nm = _nautical_miles_between(latitude, longitude, point_lat, point_lon)
            candidates.append((distance_nm, point_value))

        if not candidates:
            raise CurrentDataUnavailableError(
                f"Processed current payload for {trip_date.isoformat()} had no valid points for zone '{zone_id}'."
            )

        candidates.sort(key=lambda item: item[0])
        nearest_distance_nm, nearest_speed_kts = candidates[0]
        window = [speed for distance_nm, speed in candidates[:12] if distance_nm <= self.break_radius_nm]
        if len(window) < 2:
            window = [speed for _, speed in candidates[:4]]

        reference_distance_nm = max(nearest_distance_nm, min(self.break_radius_nm, 1.0))
        if len(window) < 2:
            break_index = 0.0
        else:
            reference_distance_nm = max(reference_distance_nm, 1.0)
            break_index = min(1.0, round((max(window) - min(window)) / reference_distance_nm, 4))

        return CurrentObservation(
            current_speed_kts=round(nearest_speed_kts, 4),
            current_break_index=break_index,
        )
