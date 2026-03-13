from __future__ import annotations

import csv
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
import logging

from app.ingested_products import load_processed_product
from app.seed_data import MOCK_ZONE_ENVIRONMENTAL_SIGNALS, ZONE_CATALOG

_MISSING_POINTS: tuple["SstPoint", ...] = ()
BBox: TypeAlias = tuple[float, float, float, float]
logger = logging.getLogger(__name__)


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


class UpstreamCoastwatchSstAdapter:
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
        self.configured_dataset_id = dataset_id
        self.last_dataset_id = dataset_id
        self.last_cache_key = ""
        self.last_failure_reason = ""
        self.last_exception_class = ""
        self.last_exception_message = ""

    def _request_params(self, target_date: str, bbox: BBox) -> dict[str, Any]:
        min_lat, max_lat, min_lon, max_lon = bbox
        query = (
            f"{self.variable_name}[({target_date}T00:00:00Z)]"
            f"[({max_lat}):1:({min_lat})]"
            f"[({min_lon}):1:({max_lon})]"
        )
        return {
            "dataset_id": self.dataset_id,
            "variable_name": self.variable_name,
            "target_date": target_date,
            "bbox": [min_lon, min_lat, max_lon, max_lat],
            "query": query,
        }

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
        query = self._request_params(target_date, bbox)["query"]
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

    def probe_upstream_request(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> dict[str, Any]:
        bbox = self._resolve_bbox(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
        target_date = trip_date.isoformat()
        request_params = self._request_params(target_date, bbox)
        url = self._build_csv_url(target_date, bbox)
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            self.last_failure_reason = "invalid_url"
            self.last_exception_class = "ValueError"
            self.last_exception_message = "Malformed upstream SST URL"
            return {
                "ok": False,
                "source": self.source_name,
                "failure_reason": self.last_failure_reason,
                "url": url,
                "params": request_params,
                "exception_class": self.last_exception_class,
                "exception_message": self.last_exception_message,
                "dataset_id": self.dataset_id,
            }

        points = self._load_points(target_date, bbox)
        return {
            "ok": bool(points),
            "source": self.source_name,
            "failure_reason": self.last_failure_reason or None,
            "url": url,
            "params": request_params,
            "exception_class": self.last_exception_class or None,
            "exception_message": self.last_exception_message or None,
            "dataset_id": self.dataset_id,
            "point_count": len(points),
        }

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str, bbox: BBox) -> tuple[SstPoint, ...]:
        if not self.dataset_id or self.dataset_id.startswith("CONFIGURE_"):
            self.last_failure_reason = "missing_dataset_id"
            self.last_exception_class = ""
            self.last_exception_message = ""
            return _MISSING_POINTS

        url = self._build_csv_url(target_date, bbox)
        request_params = self._request_params(target_date, bbox)
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            self.last_failure_reason = "invalid_url"
            self.last_exception_class = "ValueError"
            self.last_exception_message = "Malformed upstream SST URL"
            logger.warning(
                "Live SST request URL is invalid",
                extra={
                    "dataset_id": self.dataset_id,
                    "request_url": url,
                    "request_params": request_params,
                    "base_url": self.base_url,
                },
            )
            return _MISSING_POINTS
        try:
            with self.open_url(url, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except TimeoutError:
            self.last_failure_reason = "upstream_timeout"
            self.last_exception_class = "TimeoutError"
            self.last_exception_message = "The upstream SST request timed out."
            logger.warning(
                "Live SST fetch timed out",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "bbox": request_params["bbox"],
                    "base_url": self.base_url,
                    "request_url": url,
                    "request_params": request_params,
                },
            )
            return _MISSING_POINTS
        except HTTPError as exc:
            self.last_failure_reason = f"upstream_http_{exc.code}"
            self.last_exception_class = type(exc).__name__
            self.last_exception_message = str(exc)
            logger.warning(
                "Live SST fetch returned HTTP error",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "bbox": request_params["bbox"],
                    "base_url": self.base_url,
                    "status_code": exc.code,
                    "request_url": url,
                    "request_params": request_params,
                    "exception_class": type(exc).__name__,
                    "exception_message": str(exc),
                },
            )
            return _MISSING_POINTS
        except (URLError, OSError, ValueError, ssl.SSLError) as exc:
            self.last_failure_reason = self._classify_request_error(exc)
            self.last_exception_class = type(exc).__name__
            self.last_exception_message = str(exc)
            logger.warning(
                "Live SST fetch failed before parsing",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "bbox": request_params["bbox"],
                    "base_url": self.base_url,
                    "request_url": url,
                    "request_params": request_params,
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
            logger.warning(
                "Live SST response had no CSV headers",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "bbox": request_params["bbox"],
                    "request_url": url,
                    "request_params": request_params,
                },
            )
            return _MISSING_POINTS
        points: list[SstPoint] = []
        value_column_found = False
        for row in reader:
            try:
                point_lat = float(row["latitude"])
                point_lon = float(row["longitude"])
                value_text = _select_value_column(row, self.value_column_candidates)
                if value_text is None:
                    continue
                value_column_found = True
                points.append(
                    SstPoint(
                        latitude=point_lat,
                        longitude=point_lon,
                        sea_surface_temp_f=_coastwatch_sst_to_fahrenheit(float(value_text)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not value_column_found:
            self.last_failure_reason = "variable_not_found"
            self.last_exception_class = ""
            self.last_exception_message = ""
            logger.warning(
                "Live SST response did not contain the configured value column",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "bbox": request_params["bbox"],
                    "variable_name": self.variable_name,
                    "fieldnames": reader.fieldnames,
                    "request_url": url,
                    "request_params": request_params,
                },
            )
            return _MISSING_POINTS
        if not points:
            self.last_failure_reason = "bad_response_shape"
            self.last_exception_class = ""
            self.last_exception_message = ""
            logger.warning(
                "Live SST response was parsed but yielded no valid points",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": target_date,
                    "bbox": request_params["bbox"],
                    "variable_name": self.variable_name,
                    "request_url": url,
                    "request_params": request_params,
                },
            )
            return _MISSING_POINTS
        self.last_failure_reason = ""
        self.last_exception_class = ""
        self.last_exception_message = ""
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
                "Live SST dataset unavailable for request",
                extra={
                    "dataset_id": self.dataset_id,
                    "trip_date": trip_date.isoformat(),
                    "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
            raise SstDataUnavailableError(f"No live SST payload found for {trip_date.isoformat()}.")
        self.last_dataset_id = self.dataset_id
        self.last_cache_key = f"{trip_date.isoformat()}|{bbox[2]},{bbox[0]},{bbox[3]},{bbox[1]}"
        return points

    @lru_cache(maxsize=256)
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation:
        bbox = self._default_bbox()
        self.last_dataset_id = self.dataset_id
        self.last_cache_key = f"{trip_date.isoformat()}|{bbox[2]},{bbox[0]},{bbox[3]},{bbox[1]}"
        return _build_observation_from_points(
            zone_id=zone_id,
            latitude=latitude,
            longitude=longitude,
            points=self._load_points(trip_date.isoformat(), bbox),
            gradient_radius_nm=self.gradient_radius_nm,
            source_label="live",
            trip_date=trip_date,
        )


LiveCoastwatchSstAdapter = UpstreamCoastwatchSstAdapter


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
        self.configured_dataset_id = None
        self.last_dataset_id = None
        self.last_cache_key = ""

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
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"
        return filtered

    @lru_cache(maxsize=256)
    def get_zone_sst(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> SstObservation:
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|{self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"
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
        self.configured_dataset_id = None
        self.last_dataset_id = None
        self.last_cache_key = ""

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
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|mock"
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
        self.last_dataset_id = None
        self.last_cache_key = f"{trip_date.isoformat()}|mock"
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
        self.configured_dataset_id = getattr(primary, "configured_dataset_id", getattr(primary, "dataset_id", None))
        self.last_dataset_id: str | None = None
        self.last_cache_key = ""
        self.last_failure_reason = ""

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

    def _resolve_fallback_dataset_id(self) -> str | None:
        return getattr(self.fallback, "last_dataset_id", None)

    def _resolve_primary_dataset_id(self) -> str | None:
        return getattr(self.primary, "last_dataset_id", None)

    def _resolve_fallback_cache_key(self) -> str:
        return getattr(self.fallback, "last_cache_key", "")

    def _resolve_primary_cache_key(self) -> str:
        return getattr(self.primary, "last_cache_key", "")

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
            self.last_dataset_id = self._resolve_primary_dataset_id()
            self.last_cache_key = self._resolve_primary_cache_key()
            self.last_failure_reason = ""
            return observation
        except (SstDataUnavailableError, TimeoutError) as exc:
            self.last_failure_reason = getattr(self.primary, "last_failure_reason", "") or str(exc)
            logger.warning(
                "Primary SST provider failed for zone lookup; falling back",
                extra={
                    "zone_id": zone_id,
                    "trip_date": trip_date.isoformat(),
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
            observation = self.fallback.get_zone_sst(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_fallback_source_name()
            self.last_dataset_id = self._resolve_fallback_dataset_id()
            self.last_cache_key = self._resolve_fallback_cache_key()
            return observation
        except Exception as exc:
            self.last_failure_reason = getattr(self.primary, "last_failure_reason", "") or str(exc)
            logger.exception(
                "Primary SST provider raised unexpectedly for zone lookup; falling back",
                extra={
                    "zone_id": zone_id,
                    "trip_date": trip_date.isoformat(),
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
            observation = self.fallback.get_zone_sst(zone_id, latitude, longitude, trip_date)
            self.last_source_name = self._resolve_fallback_source_name()
            self.last_dataset_id = self._resolve_fallback_dataset_id()
            self.last_cache_key = self._resolve_fallback_cache_key()
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
            self.last_dataset_id = self._resolve_primary_dataset_id()
            self.last_cache_key = self._resolve_primary_cache_key()
            self.last_failure_reason = ""
            return points
        except (SstDataUnavailableError, TimeoutError) as exc:
            self.last_failure_reason = getattr(self.primary, "last_failure_reason", "") or str(exc)
            logger.warning(
                "Primary SST provider failed for map/grid lookup; falling back",
                extra={
                    "trip_date": trip_date.isoformat(),
                    "bbox": [min_lon, min_lat, max_lon, max_lat],
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
            points = self.fallback.get_sst_points(
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
                "Primary SST provider raised unexpectedly for map/grid lookup; falling back",
                extra={
                    "trip_date": trip_date.isoformat(),
                    "bbox": [min_lon, min_lat, max_lon, max_lat],
                    "primary_source": getattr(self.primary, "source_name", "unknown"),
                    "fallback_source": getattr(self.fallback, "source_name", "mock_fallback"),
                    "failure_reason": self.last_failure_reason or "unknown",
                },
            )
            points = self.fallback.get_sst_points(
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
