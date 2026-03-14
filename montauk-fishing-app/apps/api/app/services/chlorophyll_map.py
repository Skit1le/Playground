from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from math import sqrt
import logging

from app.chlorophyll_provider import (
    ChlorophyllDataUnavailableError,
    ChlorophyllPoint,
    ChlorophyllProvider,
)
from app.schemas import (
    ChlorophyllBreakMapFeature,
    ChlorophyllBreakMapFeatureCollection,
    ChlorophyllBreakMapFeatureProperties,
    ChlorophyllBreakMapMetadata,
    ChlorophyllBreakMapPolygonGeometry,
    ChlorophyllBreakMapResponse,
)
from app.services.chlorophyll_edges import ChlorophyllCellSignal, build_chlorophyll_cell_signals

logger = logging.getLogger(__name__)


def _resolve_source_status(source: str) -> str:
    if source == "live":
        return "live"
    if source == "processed":
        return "cached"
    if source == "mock":
        return "seed"
    if source == "unavailable":
        return "unavailable"
    return "fallback"


def _build_warning_messages(*, source: str, failure_reason: str) -> list[str]:
    if source == "processed":
        return ["Showing cached chlorophyll data while live satellite chlorophyll is unavailable."]
    if source == "mock_fallback":
        if failure_reason in {"parse_error", "empty_dataset"}:
            return ["Showing a local chlorophyll estimate because the live satellite feed had no usable values for this request."]
        if failure_reason in {"network_blocked", "dns_error", "proxy_error", "tls_error", "timeout", "refused_connection"}:
            return ["Showing a local chlorophyll estimate because the live satellite feed could not be reached from this machine."]
        if failure_reason == "invalid_dataset":
            return ["Showing a local chlorophyll estimate because the configured live chlorophyll dataset could not be resolved upstream."]
        return ["Showing a local chlorophyll estimate while live satellite chlorophyll is unavailable."]
    if source == "unavailable":
        if failure_reason:
            return [f"Chlorophyll data unavailable for this request ({failure_reason})."]
        return ["Chlorophyll data unavailable for this request."]
    return []


def _round_coordinate(value: float) -> float:
    return round(value, 5)


def _estimate_grid_dimensions(
    bbox: tuple[float, float, float, float],
    *,
    target_cells: int,
) -> tuple[int, int]:
    min_lng, min_lat, max_lng, max_lat = bbox
    lng_span = max(max_lng - min_lng, 0.01)
    lat_span = max(max_lat - min_lat, 0.01)
    aspect_ratio = max(lng_span / lat_span, 0.35)
    columns = max(6, round(sqrt(target_cells * aspect_ratio)))
    rows = max(5, round(target_cells / columns))
    return columns, rows


@dataclass(frozen=True)
class _ChlCellGeometry:
    west: float
    south: float
    east: float
    north: float


@lru_cache(maxsize=96)
def _build_cell_geometries(
    bbox: tuple[float, float, float, float],
    target_cells: int,
) -> tuple[_ChlCellGeometry, ...]:
    min_lng, min_lat, max_lng, max_lat = bbox
    columns, rows = _estimate_grid_dimensions(bbox, target_cells=target_cells)
    cell_width = (max_lng - min_lng) / columns
    cell_height = (max_lat - min_lat) / rows
    geometries: list[_ChlCellGeometry] = []
    for row_index in range(rows):
        for column_index in range(columns):
            west = min_lng + (column_index * cell_width)
            east = west + cell_width
            south = min_lat + (row_index * cell_height)
            north = south + cell_height
            geometries.append(
                _ChlCellGeometry(
                    west=_round_coordinate(west),
                    south=_round_coordinate(south),
                    east=_round_coordinate(east),
                    north=_round_coordinate(north),
                )
            )
    return tuple(geometries)


def _build_features(
    cells: tuple[ChlorophyllCellSignal, ...],
    bbox: tuple[float, float, float, float],
    target_cells: int,
) -> tuple[ChlorophyllBreakMapFeature, ...]:
    geometries = _build_cell_geometries(bbox, target_cells)
    features: list[ChlorophyllBreakMapFeature] = []
    for geometry, cell in zip(geometries, cells):
        features.append(
            ChlorophyllBreakMapFeature(
                geometry=ChlorophyllBreakMapPolygonGeometry(
                    coordinates=[
                        [
                            [geometry.west, geometry.south],
                            [geometry.east, geometry.south],
                            [geometry.east, geometry.north],
                            [geometry.west, geometry.north],
                            [geometry.west, geometry.south],
                        ]
                    ]
                ),
                properties=ChlorophyllBreakMapFeatureProperties(
                    chlorophyll_mg_m3=cell.chlorophyll_mg_m3,
                    break_intensity_mg_m3_per_nm=cell.break_intensity_mg_m3_per_nm,
                ),
            )
        )
    return tuple(features)


class ChlorophyllBreakMapService:
    def __init__(
        self,
        chlorophyll_provider: ChlorophyllProvider,
        target_cells: int = 720,
        *,
        reference_bbox: tuple[float, float, float, float] | None = None,
        minimum_target_cells: int = 180,
    ):
        self.chlorophyll_provider = chlorophyll_provider
        self.target_cells = target_cells
        self.reference_bbox = reference_bbox
        self.minimum_target_cells = minimum_target_cells

    def _resolve_target_cells(self, bbox: tuple[float, float, float, float]) -> int:
        if not self.reference_bbox:
            return self.target_cells
        min_lng, min_lat, max_lng, max_lat = bbox
        request_area = max((max_lng - min_lng) * (max_lat - min_lat), 0.01)
        ref_min_lng, ref_min_lat, ref_max_lng, ref_max_lat = self.reference_bbox
        reference_area = max((ref_max_lng - ref_min_lng) * (ref_max_lat - ref_min_lat), 0.01)
        area_ratio = max(request_area / reference_area, 1.0)
        scaled_target_cells = round(self.target_cells / area_ratio)
        return max(self.minimum_target_cells, min(self.target_cells, scaled_target_cells))

    def get_chlorophyll_break_map(
        self,
        *,
        trip_date: date,
        bbox: tuple[float, float, float, float],
    ) -> ChlorophyllBreakMapResponse:
        min_lng, min_lat, max_lng, max_lat = bbox
        effective_target_cells = self._resolve_target_cells(bbox)
        try:
            points = self.chlorophyll_provider.get_chlorophyll_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lng,
                max_lon=max_lng,
            )
            source = getattr(
                self.chlorophyll_provider,
                "last_source_name",
                getattr(self.chlorophyll_provider, "source_name", "unknown"),
            )
            dataset_id = getattr(
                self.chlorophyll_provider,
                "last_dataset_id",
                getattr(self.chlorophyll_provider, "configured_dataset_id", None),
            )
            cache_key = getattr(self.chlorophyll_provider, "last_cache_key", "")
            failure_reason = getattr(self.chlorophyll_provider, "last_failure_reason", "")
            resolved_data_timestamp = getattr(self.chlorophyll_provider, "last_resolved_timestamp", "") or trip_date.isoformat()
        except (ChlorophyllDataUnavailableError, Exception):
            points = ()
            source = "unavailable"
            dataset_id = getattr(
                self.chlorophyll_provider,
                "last_dataset_id",
                getattr(self.chlorophyll_provider, "configured_dataset_id", None),
            )
            cache_key = ""
            failure_reason = getattr(self.chlorophyll_provider, "last_failure_reason", "")
            resolved_data_timestamp = getattr(self.chlorophyll_provider, "last_resolved_timestamp", "") or trip_date.isoformat()

        cells = build_chlorophyll_cell_signals(points, bbox, effective_target_cells)
        features = list(_build_features(cells, bbox, effective_target_cells))
        values = [point.chlorophyll_mg_m3 for point in points]
        chlorophyll_range = [round(min(values), 4), round(max(values), 4)] if values else None
        break_values = [cell.break_intensity_mg_m3_per_nm for cell in cells]
        break_range = [round(min(break_values), 5), round(max(break_values), 5)] if break_values else None
        columns, rows = _estimate_grid_dimensions(bbox, target_cells=effective_target_cells)

        logger.info(
            "Resolved /map/chlorophyll-breaks dataset",
            extra={
                "trip_date": trip_date.isoformat(),
                "bbox": [min_lng, min_lat, max_lng, max_lat],
                "source": source,
                "dataset_id": dataset_id,
                "cache_key": cache_key,
                "failure_reason": failure_reason,
                "point_count": len(points),
                "cell_count": len(features),
                "target_cells": effective_target_cells,
                "grid_resolution": [columns, rows],
            },
        )

        return ChlorophyllBreakMapResponse(
            metadata=ChlorophyllBreakMapMetadata(
                date=trip_date,
                bbox=[min_lng, min_lat, max_lng, max_lat],
                source=source,
                source_status=_resolve_source_status(source),
                live_data_available=source == "live",
                fallback_used=source in {"processed", "mock_fallback"},
                provider_name=type(self.chlorophyll_provider).__name__,
                dataset_id=dataset_id,
                upstream_host=getattr(self.chlorophyll_provider, "last_upstream_host", None),
                attempted_urls=list(getattr(self.chlorophyll_provider, "last_attempted_urls", []) or []),
                provider_diagnostics=getattr(self.chlorophyll_provider, "last_provider_diagnostics", {}) or {},
                requested_date=trip_date,
                resolved_timestamp=resolved_data_timestamp,
                resolved_data_timestamp=resolved_data_timestamp,
                point_count=len(points),
                cell_count=len(features),
                chlorophyll_range_mg_m3=chlorophyll_range,
                break_intensity_range_mg_m3_per_nm=break_range,
                grid_resolution=[columns, rows] if features else None,
                failure_reason=failure_reason or None,
                warning_messages=_build_warning_messages(source=source, failure_reason=failure_reason),
            ),
            data=ChlorophyllBreakMapFeatureCollection(features=features),
        )
