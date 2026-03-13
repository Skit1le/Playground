from __future__ import annotations

import csv
import logging
import ssl
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from io import StringIO
from math import asin, cos, radians, sin, sqrt
from typing import Any, Callable, Protocol, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import urlopen

from app.ingested_products import load_processed_product
from app.seed_data import MOCK_ZONE_ENVIRONMENTAL_SIGNALS, ZONE_CATALOG

_MISSING_POINTS: tuple["ChlorophyllPoint", ...] = ()
BBox: TypeAlias = tuple[float, float, float, float]
logger = logging.getLogger(__name__)


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
        self.configured_dataset_id = dataset_id
        self.last_dataset_id = dataset_id
        self.last_cache_key = ""
        self.last_failure_reason = ""
        self.last_exception_class = ""
        self.last_exception_message = ""
        self.last_status_code: int | None = None

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

    def _classify_request_error(self, exc: Exception) -> str:
        if isinstance(exc, ValueError):
            return "invalid_url"
        if isinstance(exc, ssl.SSLError):
            return "ssl_error"
        if isinstance(exc, URLError):
            reason = exc.reason
            if isinstance(reason, ssl.SSLError):
                return "ssl_error"
            reason_text = str(reason).lower()
            if "proxy" in reason_text:
                return "proxy_error"
            if "ssl" in reason_text or "certificate" in reason_text:
                return "ssl_error"
            if "unknown url type" in reason_text or "no host given" in reason_text:
                return "invalid_url"
            return "connection_error"
        if isinstance(exc, OSError):
            message = str(exc).lower()
            if "ssl" in message or "certificate" in message:
                return "ssl_error"
            if "proxy" in message:
                return "proxy_error"
            return "connection_error"
        return "request_exception"

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str, bbox: BBox) -> tuple[ChlorophyllPoint, ...]:
        if not self.dataset_id or self.dataset_id.startswith("CONFIGURE_"):
            self.last_failure_reason = "missing_dataset_id"
            self.last_exception_class = ""
            self.last_exception_message = ""
            self.last_status_code = None
            return _MISSING_POINTS

        url = self._build_csv_url(target_date, bbox)
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            self.last_failure_reason = "invalid_url"
            self.last_exception_class = "ValueError"
            self.last_exception_message = "Malformed upstream chlorophyll URL"
            self.last_status_code = None
            logger.warning(
                "Live chlorophyll request URL is invalid",
                extra={
                    "dataset_id": self.dataset_id,
                    "variable_name": self.variable_name,
                    "timeout_seconds": self.timeout_seconds,
                    "request_url": url,
                    "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                    "base_url": self.base_url,
                },
            )
            return _MISSING_POINTS
        try:
            with self.open_url(url, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except TimeoutError:
            self.last_failure_reason = "timeout"
            self.last_exception_class = "TimeoutError"
            self.last_exception_message = "The upstream chlorophyll request timed out."
            self.last_status_code = None
            logger.warning(
                "Live chlorophyll fetch timed out",
                extra={
                    "dataset_id": self.dataset_id,
                    "variable_name": self.variable_name,
                    "trip_date": target_date,
                    "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                    "request_url": url,
                    "timeout_seconds": self.timeout_seconds,
                },
            )
            return _MISSING_POINTS
        except HTTPError as exc:
            self.last_failure_reason = f"upstream_http_{exc.code}"
            self.last_exception_class = type(exc).__name__
            self.last_exception_message = str(exc)
            self.last_status_code = exc.code
            logger.warning(
                "Live chlorophyll fetch returned HTTP error",
                extra={
                    "dataset_id": self.dataset_id,
                    "variable_name": self.variable_name,
                    "trip_date": target_date,
                    "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                    "status_code": exc.code,
                    "request_url": url,
                    "timeout_seconds": self.timeout_seconds,
                },
            )
            return _MISSING_POINTS
        except (URLError, OSError, ValueError, ssl.SSLError) as exc:
            self.last_failure_reason = self._classify_request_error(exc)
            self.last_exception_class = type(exc).__name__
            self.last_exception_message = str(exc)
            self.last_status_code = None
            logger.warning(
                "Live chlorophyll fetch failed before parsing",
                extra={
                    "dataset_id": self.dataset_id,
                    "variable_name": self.variable_name,
                    "trip_date": target_date,
                    "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                    "request_url": url,
                    "timeout_seconds": self.timeout_seconds,
                    "exception_class": type(exc).__name__,
                    "exception_message": str(exc),
                    "failure_reason": self.last_failure_reason,
                },
            )
            return _MISSING_POINTS

        reader = csv.DictReader(StringIO(raw_text))
        if not reader.fieldnames:
            self.last_failure_reason = "bad_response_shape"
            self.last_exception_class = ""
            self.last_exception_message = ""
            self.last_status_code = None
            logger.warning(
                "Live chlorophyll response had no CSV headers",
                extra={
                    "dataset_id": self.dataset_id,
                    "variable_name": self.variable_name,
                    "trip_date": target_date,
                    "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                    "request_url": url,
                },
            )
            return _MISSING_POINTS
        points: list[ChlorophyllPoint] = []
        value_column_found = False
        for row in reader:
            try:
                value_text = _select_value_column(row, self.value_column_candidates)
                if value_text is None:
                    continue
                value_column_found = True
                points.append(
                    ChlorophyllPoint(
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                        chlorophyll_mg_m3=float(value_text),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not value_column_found:
            self.last_failure_reason = "variable_not_found"
            self.last_exception_class = ""
            self.last_exception_message = ""
            self.last_status_code = None
            logger.warning(
                "Live chlorophyll response did not contain the configured value column",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "variable_name": self.variable_name,
                    "fieldnames": reader.fieldnames,
                    "request_url": url,
                },
            )
            return _MISSING_POINTS
        if not points:
            self.last_failure_reason = "bad_response_shape"
            self.last_exception_class = ""
            self.last_exception_message = ""
            self.last_status_code = None
            logger.warning(
                "Live chlorophyll response was parsed but yielded no valid points",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "variable_name": self.variable_name,
                    "request_url": url,
                },
            )
            return _MISSING_POINTS
        self.last_failure_reason = ""
        self.last_exception_class = ""
        self.last_exception_message = ""
        self.last_status_code = None
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
            logger.warning(
                "Live chlorophyll dataset unavailable for request",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": trip_date.isoformat(),
                    "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
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
        self.configured_dataset_id = None
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
        self.configured_dataset_id = None
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
        self.configured_dataset_id = getattr(primary, "configured_dataset_id", getattr(primary, "dataset_id", None))
        self.last_dataset_id: str | None = None
        self.last_cache_key = ""
        self.last_failure_reason = ""

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
            self.last_failure_reason = ""
            return observation
        except (ChlorophyllDataUnavailableError, TimeoutError) as exc:
            self.last_failure_reason = getattr(self.primary, "last_failure_reason", "") or str(exc)
            logger.warning(
                "Primary chlorophyll provider failed for zone lookup; falling back",
                extra={
                    "zone_id": zone_id,
                    "trip_date": trip_date.isoformat(),
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
            observation = self.fallback.get_zone_chlorophyll(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_fallback_source_name()
            self.last_dataset_id = self._resolve_fallback_dataset_id()
            self.last_cache_key = self._resolve_fallback_cache_key()
            return observation
        except Exception as exc:
            self.last_failure_reason = getattr(self.primary, "last_failure_reason", "") or str(exc)
            logger.exception(
                "Primary chlorophyll provider raised unexpectedly for zone lookup; falling back",
                extra={
                    "zone_id": zone_id,
                    "trip_date": trip_date.isoformat(),
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
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
            self.last_failure_reason = ""
            return points
        except (ChlorophyllDataUnavailableError, TimeoutError) as exc:
            self.last_failure_reason = getattr(self.primary, "last_failure_reason", "") or str(exc)
            logger.warning(
                "Primary chlorophyll provider failed for map/grid lookup; falling back",
                extra={
                    "trip_date": trip_date.isoformat(),
                    "bbox": [min_lon, min_lat, max_lon, max_lat],
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
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
        except Exception as exc:
            self.last_failure_reason = getattr(self.primary, "last_failure_reason", "") or str(exc)
            logger.exception(
                "Primary chlorophyll provider raised unexpectedly for map/grid lookup; falling back",
                extra={
                    "trip_date": trip_date.isoformat(),
                    "bbox": [min_lon, min_lat, max_lon, max_lat],
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
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
