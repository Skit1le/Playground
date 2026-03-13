from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from io import StringIO
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from app.ingested_products import load_processed_product
from app.seed_data import MOCK_ZONE_ENVIRONMENTAL_SIGNALS, ZONE_CATALOG

_MISSING_POINTS: tuple["SstPoint", ...] = ()


@dataclass(frozen=True)
class SstObservation:
    sea_surface_temp_f: float
    temp_gradient_f_per_nm: float


@dataclass(frozen=True)
class SstPoint:
    latitude: float
    longitude: float
    sea_surface_temp_f: float


class SstProvider(Protocol):
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation: ...

    def get_sst_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[SstPoint, ...]: ...


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


def _select_value_column(row: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        value = row.get(candidate)
        if value not in (None, ""):
            return value
    for key, value in row.items():
        lowered = key.lower()
        if lowered in {"latitude", "longitude", "time"}:
            continue
        if value not in (None, ""):
            return value
    return None


def _filter_points_to_bbox(
    points: tuple[SstPoint, ...],
    *,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
) -> tuple[SstPoint, ...]:
    if None in (min_lat, max_lat, min_lon, max_lon):
        return points
    return tuple(
        point
        for point in points
        if min_lat <= point.latitude <= max_lat and min_lon <= point.longitude <= max_lon
    )


def _build_observation_from_points(
    *,
    zone_id: str,
    latitude: float,
    longitude: float,
    points: tuple[SstPoint, ...],
    gradient_radius_nm: float,
    source_label: str,
    trip_date: date,
) -> SstObservation:
    if not points:
        raise SstDataUnavailableError(f"No {source_label} SST payload found for {trip_date.isoformat()}.")

    candidates: list[tuple[float, float]] = []
    for point in points:
        distance_nm = _nautical_miles_between(latitude, longitude, point.latitude, point.longitude)
        candidates.append((distance_nm, point.sea_surface_temp_f))

    if not candidates:
        raise SstDataUnavailableError(
            f"{source_label.capitalize()} SST payload for {trip_date.isoformat()} had no valid points for zone '{zone_id}'."
        )

    candidates.sort(key=lambda item: item[0])
    nearest_distance_nm, nearest_temp_f = candidates[0]
    gradient_window = [
        temp_f for distance_nm, temp_f in candidates[:12] if distance_nm <= gradient_radius_nm
    ]
    if len(gradient_window) < 2:
        gradient_window = [temp_f for _, temp_f in candidates[:4]]

    reference_distance_nm = max(nearest_distance_nm, min(gradient_radius_nm, 1.0))
    if len(gradient_window) < 2:
        gradient_f_per_nm = 0.0
    else:
        reference_distance_nm = max(reference_distance_nm, 1.0)
        gradient_f_per_nm = round((max(gradient_window) - min(gradient_window)) / reference_distance_nm, 3)

    return SstObservation(
        sea_surface_temp_f=nearest_temp_f,
        temp_gradient_f_per_nm=gradient_f_per_nm,
    )


class LiveCoastwatchSstAdapter:
    source_name = "live"

    def __init__(
        self,
        *,
        dataset_id: str,
        base_url: str,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        gradient_radius_nm: float = 18.0,
        variable_name: str = "sea_surface_temperature",
        value_column_candidates: tuple[str, ...] = (
            "sea_surface_temperature",
            "sst",
            "analysed_sst",
            "temperature",
        ),
        timeout_seconds: float = 2.0,
        open_url: Callable[..., Any] = urlopen,
    ):
        self.dataset_id = dataset_id
        self.base_url = base_url.rstrip("/")
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.gradient_radius_nm = gradient_radius_nm
        self.variable_name = variable_name
        self.value_column_candidates = value_column_candidates
        self.timeout_seconds = timeout_seconds
        self.open_url = open_url

    def _build_csv_url(self, target_date: str) -> str:
        query = (
            f"{self.variable_name}[({target_date}T00:00:00Z)]"
            f"[({self.max_lat}):1:({self.min_lat})]"
            f"[({self.min_lon}):1:({self.max_lon})]"
        )
        encoded_query = quote(query, safe="[]():,")
        return f"{self.base_url}/{self.dataset_id}.csv?{encoded_query}"

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str) -> tuple[SstPoint, ...]:
        if not self.dataset_id or self.dataset_id.startswith("CONFIGURE_"):
            return _MISSING_POINTS

        url = self._build_csv_url(target_date)
        try:
            with self.open_url(url, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return _MISSING_POINTS

        reader = csv.DictReader(StringIO(raw_text))
        points: list[SstPoint] = []
        for row in reader:
            try:
                point_lat = float(row["latitude"])
                point_lon = float(row["longitude"])
                value_text = _select_value_column(row, self.value_column_candidates)
                if value_text is None:
                    continue
                points.append(
                    SstPoint(
                        latitude=point_lat,
                        longitude=point_lon,
                        sea_surface_temp_f=_coastwatch_sst_to_fahrenheit(float(value_text)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(points)

    def get_sst_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[SstPoint, ...]:
        points = self._load_points(trip_date.isoformat())
        filtered = _filter_points_to_bbox(
            points,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        if not filtered:
            raise SstDataUnavailableError(f"No live SST payload found for {trip_date.isoformat()}.")
        return filtered

    @lru_cache(maxsize=256)
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation:
        return _build_observation_from_points(
            zone_id=zone_id,
            latitude=latitude,
            longitude=longitude,
            points=self._load_points(trip_date.isoformat()),
            gradient_radius_nm=self.gradient_radius_nm,
            source_label="live",
            trip_date=trip_date,
        )


class ProcessedCoastwatchSstAdapter:
    source_name = "processed"

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
    def _load_points(self, target_date: str) -> tuple[SstPoint, ...]:
        try:
            payload = self.load_product(
                "sst",
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

        points: list[SstPoint] = []
        for point in grid:
            try:
                points.append(
                    SstPoint(
                        latitude=float(point["latitude"]),
                        longitude=float(point["longitude"]),
                        sea_surface_temp_f=_coastwatch_sst_to_fahrenheit(float(point["value"])),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(points)

    def get_sst_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[SstPoint, ...]:
        points = self._load_points(trip_date.isoformat())
        filtered = _filter_points_to_bbox(
            points,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        if not filtered:
            raise SstDataUnavailableError(f"No processed SST payload found for {trip_date.isoformat()}.")
        return filtered

    @lru_cache(maxsize=256)
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation:
        return _build_observation_from_points(
            zone_id=zone_id,
            latitude=latitude,
            longitude=longitude,
            points=self._load_points(trip_date.isoformat()),
            gradient_radius_nm=self.gradient_radius_nm,
            source_label="processed",
            trip_date=trip_date,
        )


class MockSstAdapter:
    source_name = "mock_fallback"

    def __init__(
        self,
        *,
        zone_catalog: list[dict[str, Any]] | None = None,
        records: dict[str, dict[str, float]] | None = None,
    ):
        self.zone_catalog = zone_catalog or ZONE_CATALOG
        self.records = records or MOCK_ZONE_ENVIRONMENTAL_SIGNALS

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str) -> tuple[SstPoint, ...]:
        points: list[SstPoint] = []
        for zone in self.zone_catalog:
            signal_record = self.records.get(zone["id"])
            if signal_record is None:
                continue
            points.append(
                SstPoint(
                    latitude=float(zone["center_lat"]),
                    longitude=float(zone["center_lng"]),
                    sea_surface_temp_f=float(signal_record["sea_surface_temp_f"]),
                )
            )
        return tuple(points)

    def get_sst_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[SstPoint, ...]:
        points = self._load_points(trip_date.isoformat())
        filtered = _filter_points_to_bbox(
            points,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        if not filtered:
            raise SstDataUnavailableError(f"No mock SST payload found for {trip_date.isoformat()}.")
        return filtered

    @lru_cache(maxsize=256)
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation:
        points = self._load_points(trip_date.isoformat())
        if not points:
            raise SstDataUnavailableError(f"No mock SST payload found for {trip_date.isoformat()}.")
        signal_record = self.records.get(zone_id)
        if signal_record is None:
            raise SstDataUnavailableError(f"No mock SST payload found for zone '{zone_id}'.")
        return SstObservation(
            sea_surface_temp_f=float(signal_record["sea_surface_temp_f"]),
            temp_gradient_f_per_nm=float(signal_record["temp_gradient_f_per_nm"]),
        )


class FallbackSstProvider:
    def __init__(self, primary: SstProvider, fallback: SstProvider, timeout_seconds: float = 0.75):
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.last_source_name = "mock_fallback"
        self.source_name = getattr(primary, "source_name", "processed")

    def _resolve_fallback_source_name(self) -> str:
        return getattr(
            self.fallback,
            "last_source_name",
            getattr(self.fallback, "source_name", "mock_fallback"),
        )

    def _resolve_primary_source_name(self) -> str:
        return getattr(
            self.primary,
            "last_source_name",
            getattr(self.primary, "source_name", "processed"),
        )

    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation:
        try:
            observation = self.primary.get_zone_sst(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_primary_source_name()
            return observation
        except (SstDataUnavailableError, TimeoutError):
            observation = self.fallback.get_zone_sst(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_fallback_source_name()
            return observation
        except Exception:
            observation = self.fallback.get_zone_sst(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_fallback_source_name()
            return observation

    def get_sst_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[SstPoint, ...]:
        try:
            points = self.primary.get_sst_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
            self.last_source_name = self._resolve_primary_source_name()
            return points
        except (SstDataUnavailableError, TimeoutError):
            points = self.fallback.get_sst_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
            self.last_source_name = self._resolve_fallback_source_name()
            return points
        except Exception:
            points = self.fallback.get_sst_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
            self.last_source_name = self._resolve_fallback_source_name()
            return points
