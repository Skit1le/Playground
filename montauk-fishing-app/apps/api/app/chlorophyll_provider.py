from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from io import StringIO
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable, Protocol, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from app.ingested_products import load_processed_product
from app.seed_data import MOCK_ZONE_ENVIRONMENTAL_SIGNALS, ZONE_CATALOG

_MISSING_POINTS: tuple["ChlorophyllPoint", ...] = ()
BBox: TypeAlias = tuple[float, float, float, float]


@dataclass(frozen=True)
class ChlorophyllObservation:
    chlorophyll_mg_m3: float


@dataclass(frozen=True)
class ChlorophyllPoint:
    latitude: float
    longitude: float
    chlorophyll_mg_m3: float


class ChlorophyllProvider(Protocol):
    def get_zone_chlorophyll(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> ChlorophyllObservation: ...

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]: ...


class ChlorophyllDataUnavailableError(RuntimeError):
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


def _normalize_bbox(
    *,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> BBox:
    return (
        round(min_lat, 4),
        round(max_lat, 4),
        round(min_lon, 4),
        round(max_lon, 4),
    )


def _filter_points_to_bbox(
    points: tuple[ChlorophyllPoint, ...],
    *,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
) -> tuple[ChlorophyllPoint, ...]:
    if None in (min_lat, max_lat, min_lon, max_lon):
        return points
    return tuple(
        point
        for point in points
        if min_lat <= point.latitude <= max_lat and min_lon <= point.longitude <= max_lon
    )


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


def _build_observation_from_points(
    *,
    zone_id: str,
    latitude: float,
    longitude: float,
    points: tuple[ChlorophyllPoint, ...],
    source_label: str,
    trip_date: date,
) -> ChlorophyllObservation:
    if not points:
        raise ChlorophyllDataUnavailableError(
            f"No {source_label} chlorophyll payload found for {trip_date.isoformat()}."
        )

    candidates: list[tuple[float, float]] = []
    for point in points:
        distance_nm = _nautical_miles_between(latitude, longitude, point.latitude, point.longitude)
        candidates.append((distance_nm, point.chlorophyll_mg_m3))

    if not candidates:
        raise ChlorophyllDataUnavailableError(
            f"{source_label.capitalize()} chlorophyll payload for {trip_date.isoformat()} had no valid points for zone '{zone_id}'."
        )

    candidates.sort(key=lambda item: item[0])
    return ChlorophyllObservation(chlorophyll_mg_m3=round(candidates[0][1], 4))


class UpstreamCoastwatchChlorophyllAdapter:
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
        variable_name: str = "chlorophyll",
        value_column_candidates: tuple[str, ...] = (
            "chlorophyll",
            "chlorophyll_concentration",
            "chlor_a",
            "value",
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
        self.variable_name = variable_name
        self.value_column_candidates = value_column_candidates
        self.timeout_seconds = timeout_seconds
        self.open_url = open_url
        self.last_dataset_id = dataset_id
        self.last_cache_key = ""

    def _default_bbox(self) -> BBox:
        return _normalize_bbox(
            min_lat=self.min_lat,
            max_lat=self.max_lat,
            min_lon=self.min_lon,
            max_lon=self.max_lon,
        )

    def _resolve_bbox(
        self,
        *,
        min_lat: float | None,
        max_lat: float | None,
        min_lon: float | None,
        max_lon: float | None,
    ) -> BBox:
        return _normalize_bbox(
            min_lat=self.min_lat if min_lat is None else min_lat,
            max_lat=self.max_lat if max_lat is None else max_lat,
            min_lon=self.min_lon if min_lon is None else min_lon,
            max_lon=self.max_lon if max_lon is None else max_lon,
        )

    def _build_csv_url(self, target_date: str, bbox: BBox) -> str:
        min_lat, max_lat, min_lon, max_lon = bbox
        query = (
            f"{self.variable_name}[({target_date}T00:00:00Z)]"
            f"[({max_lat}):1:({min_lat})]"
            f"[({min_lon}):1:({max_lon})]"
        )
        encoded_query = quote(query, safe="[]():,")
        return f"{self.base_url}/{self.dataset_id}.csv?{encoded_query}"

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str, bbox: BBox) -> tuple[ChlorophyllPoint, ...]:
        if not self.dataset_id or self.dataset_id.startswith("CONFIGURE_"):
            return _MISSING_POINTS

        url = self._build_csv_url(target_date, bbox)
        try:
            with self.open_url(url, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return _MISSING_POINTS

        reader = csv.DictReader(StringIO(raw_text))
        points: list[ChlorophyllPoint] = []
        for row in reader:
            try:
                value_text = _select_value_column(row, self.value_column_candidates)
                if value_text is None:
                    continue
                points.append(
                    ChlorophyllPoint(
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                        chlorophyll_mg_m3=float(value_text),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(points)

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]:
        bbox = self._resolve_bbox(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        points = _filter_points_to_bbox(
            self._load_points(trip_date.isoformat(), bbox),
            min_lat=bbox[0],
            max_lat=bbox[1],
            min_lon=bbox[2],
            max_lon=bbox[3],
        )
        if not points:
            raise ChlorophyllDataUnavailableError(
                f"No live chlorophyll payload found for {trip_date.isoformat()}."
            )
        self.last_dataset_id = self.dataset_id
        self.last_cache_key = f"{trip_date.isoformat()}|{bbox[2]},{bbox[0]},{bbox[3]},{bbox[1]}"
        return points

    @lru_cache(maxsize=256)
    def get_zone_chlorophyll(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> ChlorophyllObservation:
        bbox = self._default_bbox()
        self.last_dataset_id = self.dataset_id
        self.last_cache_key = f"{trip_date.isoformat()}|{bbox[2]},{bbox[0]},{bbox[3]},{bbox[1]}"
        return _build_observation_from_points(
            zone_id=zone_id,
            latitude=latitude,
            longitude=longitude,
            points=self._load_points(trip_date.isoformat(), bbox),
            source_label="live",
            trip_date=trip_date,
        )


LiveCoastwatchChlorophyllAdapter = UpstreamCoastwatchChlorophyllAdapter


class ProcessedCoastwatchChlorophyllAdapter:
    source_name = "processed"

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
        self.last_dataset_id = None
        self.last_cache_key = ""

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str) -> tuple[ChlorophyllPoint, ...]:
        try:
            payload = self.load_product(
                "chlorophyll",
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

        points: list[ChlorophyllPoint] = []
        for point in grid:
            try:
                points.append(
                    ChlorophyllPoint(
                        latitude=float(point["latitude"]),
                        longitude=float(point["longitude"]),
                        chlorophyll_mg_m3=float(point["value"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(points)

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]:
        points = _filter_points_to_bbox(
            self._load_points(trip_date.isoformat()),
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        if not points:
            raise ChlorophyllDataUnavailableError(
                f"No processed chlorophyll payload found for {trip_date.isoformat()}."
            )
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"
        return points

    @lru_cache(maxsize=256)
    def get_zone_chlorophyll(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> ChlorophyllObservation:
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"
        return _build_observation_from_points(
            zone_id=zone_id,
            latitude=latitude,
            longitude=longitude,
            points=self._load_points(trip_date.isoformat()),
            source_label="processed",
            trip_date=trip_date,
        )


class MockChlorophyllAdapter:
    source_name = "mock_fallback"

    def __init__(
        self,
        *,
        zone_catalog: list[dict[str, Any]] | None = None,
        records: dict[str, dict[str, float]] | None = None,
    ):
        self.zone_catalog = zone_catalog or ZONE_CATALOG
        self.records = records or MOCK_ZONE_ENVIRONMENTAL_SIGNALS
        self.last_dataset_id = None
        self.last_cache_key = ""

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str) -> tuple[ChlorophyllPoint, ...]:
        points: list[ChlorophyllPoint] = []
        for zone in self.zone_catalog:
            signal_record = self.records.get(zone["id"])
            if signal_record is None:
                continue
            points.append(
                ChlorophyllPoint(
                    latitude=float(zone["center_lat"]),
                    longitude=float(zone["center_lng"]),
                    chlorophyll_mg_m3=float(signal_record["chlorophyll_mg_m3"]),
                )
            )
        return tuple(points)

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]:
        points = _filter_points_to_bbox(
            self._load_points(trip_date.isoformat()),
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        if not points:
            raise ChlorophyllDataUnavailableError(
                f"No mock chlorophyll payload found for {trip_date.isoformat()}."
            )
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|mock"
        return points

    @lru_cache(maxsize=256)
    def get_zone_chlorophyll(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> ChlorophyllObservation:
        signal_record = self.records.get(zone_id)
        if signal_record is None:
            raise ChlorophyllDataUnavailableError(f"No mock chlorophyll payload found for zone '{zone_id}'.")
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|mock"
        return ChlorophyllObservation(chlorophyll_mg_m3=float(signal_record["chlorophyll_mg_m3"]))


class FallbackChlorophyllProvider:
    def __init__(self, primary: ChlorophyllProvider, fallback: ChlorophyllProvider):
        self.primary = primary
        self.fallback = fallback
        self.last_source_name = "mock_fallback"
        self.source_name = getattr(primary, "source_name", "processed")
        self.last_dataset_id: str | None = None
        self.last_cache_key = ""

    def _resolve_primary_source_name(self) -> str:
        return getattr(self.primary, "last_source_name", getattr(self.primary, "source_name", "processed"))

    def _resolve_fallback_source_name(self) -> str:
        return getattr(self.fallback, "last_source_name", getattr(self.fallback, "source_name", "mock_fallback"))

    def _resolve_primary_dataset_id(self) -> str | None:
        return getattr(self.primary, "last_dataset_id", None)

    def _resolve_fallback_dataset_id(self) -> str | None:
        return getattr(self.fallback, "last_dataset_id", None)

    def _resolve_primary_cache_key(self) -> str:
        return getattr(self.primary, "last_cache_key", "")

    def _resolve_fallback_cache_key(self) -> str:
        return getattr(self.fallback, "last_cache_key", "")

    def get_zone_chlorophyll(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> ChlorophyllObservation:
        try:
            observation = self.primary.get_zone_chlorophyll(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_primary_source_name()
            self.last_dataset_id = self._resolve_primary_dataset_id()
            self.last_cache_key = self._resolve_primary_cache_key()
            return observation
        except Exception:
            observation = self.fallback.get_zone_chlorophyll(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_fallback_source_name()
            self.last_dataset_id = self._resolve_fallback_dataset_id()
            self.last_cache_key = self._resolve_fallback_cache_key()
            return observation

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]:
        try:
            points = self.primary.get_chlorophyll_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
            self.last_source_name = self._resolve_primary_source_name()
            self.last_dataset_id = self._resolve_primary_dataset_id()
            self.last_cache_key = self._resolve_primary_cache_key()
            return points
        except Exception:
            points = self.fallback.get_chlorophyll_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lon,
                max_lon=max_lon,
            )
            self.last_source_name = self._resolve_fallback_source_name()
            self.last_dataset_id = self._resolve_fallback_dataset_id()
            self.last_cache_key = self._resolve_fallback_cache_key()
            return points
