from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable, Protocol

from app.ingested_products import load_processed_product


@dataclass(frozen=True)
class SstObservation:
    sea_surface_temp_f: float
    temp_gradient_f_per_nm: float


class SstProvider(Protocol):
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation: ...


class SstDataUnavailableError(RuntimeError):
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


def _coastwatch_sst_to_fahrenheit(value: float) -> float:
    # CoastWatch SST products are typically Celsius. If a future dataset is already Fahrenheit,
    # this heuristic avoids double-converting obviously Fahrenheit-like values.
    if value <= 45:
        return round((value * 9 / 5) + 32, 3)
    return round(value, 3)


class ProcessedCoastwatchSstAdapter:
    def __init__(
        self,
        *,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        gradient_radius_nm: float = 18.0,
        load_product: Callable[[str, str, float, float, float, float], dict[str, Any]] = load_processed_product,
    ):
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.gradient_radius_nm = gradient_radius_nm
        self.load_product = load_product

    @lru_cache(maxsize=32)
    def _load_payload(self, target_date: str) -> dict[str, Any]:
        try:
            payload = self.load_product(
                "sst",
                target_date,
                self.min_lat,
                self.max_lat,
                self.min_lon,
                self.max_lon,
            )
        except FileNotFoundError as exc:
            raise SstDataUnavailableError(f"No processed SST payload found for {target_date}.") from exc

        grid = payload.get("grid")
        if not isinstance(grid, list) or not grid:
            raise SstDataUnavailableError(f"Processed SST payload for {target_date} did not contain a usable grid.")
        return payload

    @lru_cache(maxsize=256)
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation:
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
            candidates.append((distance_nm, _coastwatch_sst_to_fahrenheit(point_value)))

        if not candidates:
            raise SstDataUnavailableError(
                f"Processed SST payload for {trip_date.isoformat()} had no valid points for zone '{zone_id}'."
            )

        candidates.sort(key=lambda item: item[0])
        nearest_distance_nm, nearest_temp_f = candidates[0]

        gradient_window = [
            temp_f for distance_nm, temp_f in candidates[:12] if distance_nm <= self.gradient_radius_nm
        ]
        if len(gradient_window) < 2:
            gradient_window = [temp_f for _, temp_f in candidates[:4]]

        reference_distance_nm = max(nearest_distance_nm, min(self.gradient_radius_nm, 1.0))
        if len(gradient_window) < 2:
            gradient_f_per_nm = 0.0
        else:
            reference_distance_nm = max(reference_distance_nm, 1.0)
            gradient_f_per_nm = round((max(gradient_window) - min(gradient_window)) / reference_distance_nm, 3)

        return SstObservation(
            sea_surface_temp_f=nearest_temp_f,
            temp_gradient_f_per_nm=gradient_f_per_nm,
        )
