from __future__ import annotations

import csv
import errno
import logging
import math
import re
import socket
import ssl
import subprocess
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
_AXIS_MAXIMUM_TIMESTAMP_PATTERN = re.compile(r"axis maximum=([0-9T:\-]+Z)")
_KNOWN_DATASET_ALIASES: dict[str, tuple[str, ...]] = {
    "nesdisVHNchlaDaily": ("noaacwNPPVIIRSchlaDaily",),
}


@dataclass(frozen=True)
class ChlorophyllObservation:
    chlorophyll_mg_m3: float


@dataclass(frozen=True)
class ChlorophyllPoint:
    latitude: float
    longitude: float
    chlorophyll_mg_m3: float


@dataclass(frozen=True)
class _FetchResult:
    status_code: int
    body: str


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
        variable_name: str = "chlor_a",
        time_suffix: str = "T12:00:00Z",
        extra_selectors: str = "[(0.0)]",
        value_column_candidates: tuple[str, ...] = (
            "chlorophyll_concentration",
            "chlor_a",
            "chlorophyll",
            "value",
        ),
        timeout_seconds: float = 2.0,
        retry_attempts: int = 2,
        open_url: Callable[..., Any] = urlopen,
        curl_binary: str = "curl.exe",
        run_command: Callable[..., Any] = subprocess.run,
        alternate_dataset_ids: tuple[str, ...] = (),
    ):
        self.dataset_id = dataset_id
        self.base_url = base_url.rstrip("/")
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.variable_name = variable_name
        self.time_suffix = time_suffix
        self.extra_selectors = extra_selectors
        self.value_column_candidates = value_column_candidates
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.open_url = open_url
        self.curl_binary = curl_binary
        self.run_command = run_command
        self.alternate_dataset_ids = alternate_dataset_ids
        self.configured_dataset_id = dataset_id
        self.last_dataset_id = dataset_id
        self.last_cache_key = ""
        self.last_failure_reason = ""
        self.last_exception_class = ""
        self.last_exception_message = ""
        self.last_status_code: int | None = None
        self.last_resolved_timestamp = ""
        self.last_upstream_host = urlparse(self.base_url).netloc
        self.last_attempted_urls: list[str] = []
        self.last_provider_diagnostics: dict[str, str | int | float | bool | None] = {}

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

    def _candidate_dataset_ids(self) -> tuple[str, ...]:
        configured = self.dataset_id.strip()
        aliases = _KNOWN_DATASET_ALIASES.get(configured, ())
        ordered = [configured, *self.alternate_dataset_ids, *aliases]
        unique: list[str] = []
        for dataset_id in ordered:
            if dataset_id and dataset_id not in unique:
                unique.append(dataset_id)
        return tuple(unique)

    def _build_csv_url(self, dataset_id: str, target_timestamp: str, bbox: BBox) -> str:
        min_lat, max_lat, min_lon, max_lon = bbox
        query = (
            f"{self.variable_name}[({target_timestamp})]"
            f"{self.extra_selectors}"
            f"[({max_lat}):1:({min_lat})]"
            f"[({min_lon}):1:({max_lon})]"
        )
        encoded_query = quote(query, safe="[]():,")
        return f"{self.base_url}/{dataset_id}.csv?{encoded_query}"

    def _target_timestamp(self, target_date: str) -> str:
        if "T" in target_date:
            return target_date
        return f"{target_date}{self.time_suffix}"

    def _extract_axis_maximum_timestamp(self, error_text: str) -> str | None:
        match = _AXIS_MAXIMUM_TIMESTAMP_PATTERN.search(error_text)
        if not match:
            return None
        return match.group(1)

    def _fetch_with_curl(self, url: str) -> _FetchResult:
        sentinel = "__HTTP_STATUS__:"
        timeout_seconds = max(1, int(math.ceil(self.timeout_seconds)))
        completed = self.run_command(
            [
                self.curl_binary,
                "--globoff",
                "--silent",
                "--show-error",
                "--location",
                "--retry",
                str(max(0, self.retry_attempts - 1)),
                "--retry-all-errors",
                "--retry-delay",
                "1",
                "--connect-timeout",
                str(timeout_seconds),
                "--max-time",
                str(timeout_seconds),
                "--user-agent",
                "MontaukFishingApp/1.0 (+chlorophyll-provider)",
                "--write-out",
                f"\n{sentinel}%{{http_code}}",
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise OSError(
                completed.stderr.strip() or f"{self.curl_binary} exited with code {completed.returncode}"
            )

        stdout = completed.stdout
        marker_index = stdout.rfind(sentinel)
        if marker_index < 0:
            raise ValueError("curl response did not include an HTTP status marker")

        body = stdout[:marker_index].rstrip("\r\n")
        status_text = stdout[marker_index + len(sentinel) :].strip()
        if not status_text.isdigit():
            raise ValueError("curl response did not include a numeric HTTP status")
        return _FetchResult(status_code=int(status_text), body=body)

    def _fetch(self, url: str) -> _FetchResult:
        try:
            with self.open_url(url, timeout=self.timeout_seconds) as response:
                return _FetchResult(status_code=200, body=response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                error_body = ""
            return _FetchResult(status_code=exc.code, body=error_body)
        except TimeoutError:
            return self._fetch_with_curl(url)
        except (URLError, OSError, ValueError, ssl.SSLError) as exc:
            failure_reason = self._classify_request_error(exc)
            if failure_reason in {
                "network_blocked",
                "dns_error",
                "tls_error",
                "proxy_error",
                "timeout",
                "refused_connection",
                "connection_error",
            }:
                return self._fetch_with_curl(url)
            raise

    def _classify_request_error(self, exc: Exception) -> str:
        if isinstance(exc, ValueError):
            return "invalid_url"
        if isinstance(exc, ssl.SSLError):
            return "tls_error"
        if isinstance(exc, TimeoutError):
            return "timeout"
        if isinstance(exc, URLError):
            reason = exc.reason
            if isinstance(reason, socket.gaierror):
                return "dns_error"
            if isinstance(reason, TimeoutError):
                return "timeout"
            if isinstance(reason, ConnectionRefusedError):
                return "refused_connection"
            if isinstance(reason, ssl.SSLError):
                return "tls_error"
            reason_text = str(reason).lower()
            if "proxy" in reason_text:
                return "proxy_error"
            if "ssl" in reason_text or "certificate" in reason_text:
                return "tls_error"
            if "unknown url type" in reason_text or "no host given" in reason_text:
                return "invalid_url"
            if "timed out" in reason_text:
                return "timeout"
            if "refused" in reason_text:
                return "refused_connection"
            if (
                "forbidden by its access permissions" in reason_text
                or "network is unreachable" in reason_text
                or "10013" in reason_text
                or "socket blocked" in reason_text
            ):
                return "network_blocked"
            return "connection_error"
        if isinstance(exc, OSError):
            message = str(exc).lower()
            if getattr(exc, "errno", None) in {errno.ECONNREFUSED}:
                return "refused_connection"
            if getattr(exc, "errno", None) in {errno.ENETUNREACH, errno.EHOSTUNREACH}:
                return "network_blocked"
            if "ssl" in message or "certificate" in message:
                return "tls_error"
            if "proxy" in message:
                return "proxy_error"
            if "timed out" in message:
                return "timeout"
            if "refused" in message:
                return "refused_connection"
            if "could not resolve host" in message or "name or service not known" in message:
                return "dns_error"
            if (
                "failed to connect" in message
                or "access permissions" in message
                or "network is unreachable" in message
                or "10013" in message
                or "socket blocked" in message
            ):
                return "network_blocked"
            return "connection_error"
        return "request_exception"

    def _set_failure_state(
        self,
        *,
        failure_reason: str,
        exception_class: str = "",
        exception_message: str = "",
        status_code: int | None = None,
        diagnostics: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.last_failure_reason = failure_reason
        self.last_exception_class = exception_class
        self.last_exception_message = exception_message
        self.last_status_code = status_code
        self.last_provider_diagnostics = diagnostics or {}

    def _reset_request_diagnostics(self) -> None:
        self.last_attempted_urls = []
        self.last_provider_diagnostics = {}
        self.last_exception_class = ""
        self.last_exception_message = ""
        self.last_status_code = None
        self.last_dataset_id = None
        self.last_resolved_timestamp = ""

    def _build_diagnostics(
        self,
        *,
        dataset_id: str,
        request_url: str,
        status_code: int | None = None,
        attempt_number: int = 1,
        target_timestamp: str,
    ) -> dict[str, str | int | float | bool | None]:
        return {
            "configured_dataset_id": self.configured_dataset_id,
            "resolved_dataset_id": dataset_id,
            "upstream_host": self.last_upstream_host,
            "request_url": request_url,
            "attempt_number": attempt_number,
            "retry_attempts": self.retry_attempts,
            "timeout_seconds": self.timeout_seconds,
            "target_timestamp": target_timestamp,
            "status_code": status_code,
        }

    def _parse_csv_points(
        self,
        raw_text: str,
        *,
        dataset_id: str,
        target_timestamp: str,
        bbox: BBox,
        url: str,
    ) -> tuple[ChlorophyllPoint, ...]:
        reader = csv.DictReader(StringIO(raw_text))
        if not reader.fieldnames:
            self._set_failure_state(
                failure_reason="parse_error",
                diagnostics=self._build_diagnostics(
                    dataset_id=dataset_id,
                    request_url=url,
                    target_timestamp=target_timestamp,
                ),
            )
            logger.warning(
                "Live chlorophyll response had no CSV headers",
                extra={
                    "dataset_id": dataset_id,
                    "variable_name": self.variable_name,
                    "trip_date": target_timestamp,
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
                latitude = float(row["latitude"])
                longitude = float(row["longitude"])
                value = float(value_text)
                if not math.isfinite(latitude) or not math.isfinite(longitude) or not math.isfinite(value):
                    continue
                points.append(
                    ChlorophyllPoint(
                        latitude=latitude,
                        longitude=longitude,
                        chlorophyll_mg_m3=value,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not value_column_found:
            self._set_failure_state(
                failure_reason="parse_error",
                diagnostics=self._build_diagnostics(
                    dataset_id=dataset_id,
                    request_url=url,
                    target_timestamp=target_timestamp,
                ),
            )
            logger.warning(
                "Live chlorophyll response did not contain the configured value column",
                extra={
                    "dataset_id": dataset_id,
                    "trip_date": target_timestamp,
                    "variable_name": self.variable_name,
                    "fieldnames": reader.fieldnames,
                    "request_url": url,
                },
            )
            return _MISSING_POINTS
        if not points:
            self._set_failure_state(
                failure_reason="empty_dataset",
                diagnostics=self._build_diagnostics(
                    dataset_id=dataset_id,
                    request_url=url,
                    target_timestamp=target_timestamp,
                ),
            )
            logger.warning(
                "Live chlorophyll response was parsed but yielded no valid points",
                extra={
                    "dataset_id": dataset_id,
                    "trip_date": target_timestamp,
                    "variable_name": self.variable_name,
                    "request_url": url,
                },
            )
            return _MISSING_POINTS
        self._set_failure_state(
            failure_reason="",
            diagnostics=self._build_diagnostics(
                dataset_id=dataset_id,
                request_url=url,
                target_timestamp=target_timestamp,
            ),
        )
        self.last_resolved_timestamp = target_timestamp
        self.last_dataset_id = dataset_id
        return tuple(points)

    @lru_cache(maxsize=32)
    def _load_points(self, target_date: str, bbox: BBox) -> tuple[ChlorophyllPoint, ...]:
        self._reset_request_diagnostics()
        if not self.dataset_id or self.dataset_id.startswith("CONFIGURE_"):
            self._set_failure_state(failure_reason="missing_dataset_id")
            return _MISSING_POINTS

        target_timestamp = self._target_timestamp(target_date)
        for attempt_number, dataset_id in enumerate(self._candidate_dataset_ids(), start=1):
            url = self._build_csv_url(dataset_id, target_timestamp, bbox)
            self.last_attempted_urls.append(url)
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                self._set_failure_state(
                    failure_reason="invalid_url",
                    exception_class="ValueError",
                    exception_message="Malformed upstream chlorophyll URL",
                    diagnostics=self._build_diagnostics(
                        dataset_id=dataset_id,
                        request_url=url,
                        attempt_number=attempt_number,
                        target_timestamp=target_timestamp,
                    ),
                )
                continue
            try:
                fetch_result = self._fetch(url)
            except TimeoutError:
                self._set_failure_state(
                    failure_reason="timeout",
                    exception_class="TimeoutError",
                    exception_message="The upstream chlorophyll request timed out.",
                    diagnostics=self._build_diagnostics(
                        dataset_id=dataset_id,
                        request_url=url,
                        attempt_number=attempt_number,
                        target_timestamp=target_timestamp,
                    ),
                )
                continue
            except (URLError, OSError, ValueError, ssl.SSLError) as exc:
                failure_reason = self._classify_request_error(exc)
                self._set_failure_state(
                    failure_reason=failure_reason,
                    exception_class=type(exc).__name__,
                    exception_message=str(exc),
                    diagnostics=self._build_diagnostics(
                        dataset_id=dataset_id,
                        request_url=url,
                        attempt_number=attempt_number,
                        target_timestamp=target_timestamp,
                    ),
                )
                logger.warning(
                    "Live chlorophyll fetch failed before parsing",
                    extra={
                        "dataset_id": dataset_id,
                        "variable_name": self.variable_name,
                        "trip_date": target_date,
                        "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                        "request_url": url,
                        "timeout_seconds": self.timeout_seconds,
                        "exception_class": type(exc).__name__,
                        "exception_message": str(exc),
                        "failure_reason": failure_reason,
                        "attempt_number": attempt_number,
                    },
                )
                continue

            if fetch_result.status_code >= 400:
                error_body = fetch_result.body
                fallback_timestamp = self._extract_axis_maximum_timestamp(error_body)
                if fetch_result.status_code == 404 and fallback_timestamp and fallback_timestamp != target_timestamp:
                    retry_url = self._build_csv_url(dataset_id, fallback_timestamp, bbox)
                    self.last_attempted_urls.append(retry_url)
                    try:
                        retry_result = self._fetch(retry_url)
                    except TimeoutError:
                        self._set_failure_state(
                            failure_reason="timeout",
                            exception_class="TimeoutError",
                            exception_message="The upstream chlorophyll request timed out.",
                            diagnostics=self._build_diagnostics(
                                dataset_id=dataset_id,
                                request_url=retry_url,
                                attempt_number=attempt_number,
                                target_timestamp=fallback_timestamp,
                            ),
                        )
                        continue
                    except (URLError, OSError, ValueError, ssl.SSLError) as retry_exc:
                        failure_reason = self._classify_request_error(retry_exc)
                        self._set_failure_state(
                            failure_reason=failure_reason,
                            exception_class=type(retry_exc).__name__,
                            exception_message=str(retry_exc),
                            diagnostics=self._build_diagnostics(
                                dataset_id=dataset_id,
                                request_url=retry_url,
                                attempt_number=attempt_number,
                                target_timestamp=fallback_timestamp,
                            ),
                        )
                        continue
                    if retry_result.status_code >= 400:
                        failure_reason = "upstream_5xx" if retry_result.status_code >= 500 else "upstream_4xx"
                        self._set_failure_state(
                            failure_reason=failure_reason,
                            exception_class="HTTPError",
                            exception_message=f"HTTP Error {retry_result.status_code}",
                            status_code=retry_result.status_code,
                            diagnostics=self._build_diagnostics(
                                dataset_id=dataset_id,
                                request_url=retry_url,
                                status_code=retry_result.status_code,
                                attempt_number=attempt_number,
                                target_timestamp=fallback_timestamp,
                            ),
                        )
                        continue
                    return self._parse_csv_points(
                        retry_result.body,
                        dataset_id=dataset_id,
                        target_timestamp=fallback_timestamp,
                        bbox=bbox,
                        url=retry_url,
                    )
                if fetch_result.status_code == 404:
                    failure_reason = "invalid_dataset"
                elif fetch_result.status_code >= 500:
                    failure_reason = "upstream_5xx"
                else:
                    failure_reason = "upstream_4xx"
                self._set_failure_state(
                    failure_reason=failure_reason,
                    exception_class="HTTPError",
                    exception_message=f"HTTP Error {fetch_result.status_code}",
                    status_code=fetch_result.status_code,
                    diagnostics=self._build_diagnostics(
                        dataset_id=dataset_id,
                        request_url=url,
                        status_code=fetch_result.status_code,
                        attempt_number=attempt_number,
                        target_timestamp=target_timestamp,
                    ),
                )
                logger.warning(
                    "Live chlorophyll fetch returned HTTP error",
                    extra={
                        "dataset_id": dataset_id,
                        "variable_name": self.variable_name,
                        "trip_date": target_date,
                        "bbox": [bbox[2], bbox[0], bbox[3], bbox[1]],
                        "status_code": fetch_result.status_code,
                        "request_url": url,
                        "timeout_seconds": self.timeout_seconds,
                        "error_body": error_body,
                        "failure_reason": failure_reason,
                        "attempt_number": attempt_number,
                    },
                )
                continue

            return self._parse_csv_points(
                fetch_result.body,
                dataset_id=dataset_id,
                target_timestamp=target_timestamp,
                bbox=bbox,
                url=url,
            )

        return _MISSING_POINTS

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
        self.last_resolved_timestamp = ""
        self.last_upstream_host = getattr(primary, "last_upstream_host", None)
        self.last_attempted_urls: list[str] = []
        self.last_provider_diagnostics: dict[str, str | int | float | bool | None] = {}

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

    def _resolve_primary_resolved_timestamp(self) -> str:
        return getattr(self.primary, "last_resolved_timestamp", "")

    def _resolve_fallback_resolved_timestamp(self) -> str:
        return getattr(self.fallback, "last_resolved_timestamp", "")

    def _resolve_primary_upstream_host(self) -> str | None:
        return getattr(self.primary, "last_upstream_host", None)

    def _resolve_primary_attempted_urls(self) -> list[str]:
        return list(getattr(self.primary, "last_attempted_urls", []) or [])

    def _resolve_primary_provider_diagnostics(self) -> dict[str, str | int | float | bool | None]:
        return dict(getattr(self.primary, "last_provider_diagnostics", {}) or {})

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
            self.last_resolved_timestamp = self._resolve_primary_resolved_timestamp()
            self.last_upstream_host = self._resolve_primary_upstream_host()
            self.last_attempted_urls = self._resolve_primary_attempted_urls()
            self.last_provider_diagnostics = self._resolve_primary_provider_diagnostics()
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
            self.last_resolved_timestamp = self._resolve_fallback_resolved_timestamp()
            self.last_upstream_host = self._resolve_primary_upstream_host()
            self.last_attempted_urls = self._resolve_primary_attempted_urls()
            self.last_provider_diagnostics = self._resolve_primary_provider_diagnostics()
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
            self.last_resolved_timestamp = self._resolve_fallback_resolved_timestamp()
            self.last_upstream_host = self._resolve_primary_upstream_host()
            self.last_attempted_urls = self._resolve_primary_attempted_urls()
            self.last_provider_diagnostics = self._resolve_primary_provider_diagnostics()
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
            self.last_resolved_timestamp = self._resolve_primary_resolved_timestamp()
            self.last_upstream_host = self._resolve_primary_upstream_host()
            self.last_attempted_urls = self._resolve_primary_attempted_urls()
            self.last_provider_diagnostics = self._resolve_primary_provider_diagnostics()
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
            self.last_resolved_timestamp = self._resolve_fallback_resolved_timestamp()
            self.last_upstream_host = self._resolve_primary_upstream_host()
            self.last_attempted_urls = self._resolve_primary_attempted_urls()
            self.last_provider_diagnostics = self._resolve_primary_provider_diagnostics()
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
            self.last_resolved_timestamp = self._resolve_fallback_resolved_timestamp()
            self.last_upstream_host = self._resolve_primary_upstream_host()
            self.last_attempted_urls = self._resolve_primary_attempted_urls()
            self.last_provider_diagnostics = self._resolve_primary_provider_diagnostics()
            return points
