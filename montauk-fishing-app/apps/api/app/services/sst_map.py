from __future__ import annotations

from datetime import date
from functools import lru_cache
from math import sqrt
import logging

from app.schemas import (
    SstMapFeature,
    SstMapFeatureCollection,
    SstMapFeatureProperties,
    SstMapMetadata,
    SstMapPolygonGeometry,
    SstMapResponse,
)
from app.sst_provider import SstDataUnavailableError, SstPoint, SstProvider

logger = logging.getLogger(__name__)


def _round_coordinate(value: float) -> float:
    return round(value, 5)


def _estimate_grid_dimensions(
    bbox: tuple[float, float, float, float],
    *,
    target_cells: int = 126,
) -> tuple[int, int]:
    min_lng, min_lat, max_lng, max_lat = bbox
    lng_span = max(max_lng - min_lng, 0.01)
    lat_span = max(max_lat - min_lat, 0.01)
    aspect_ratio = max(lng_span / lat_span, 0.35)
    columns = max(6, round(sqrt(target_cells * aspect_ratio)))
    rows = max(5, round(target_cells / columns))
    return columns, rows


def _estimate_cell_temperature(
    center_lng: float,
    center_lat: float,
    *,
    points: tuple[SstPoint, ...],
) -> float:
    weighted_points: list[tuple[float, float]] = []
    for point in points:
        distance = sqrt((point.longitude - center_lng) ** 2 + (point.latitude - center_lat) ** 2)
        if distance <= 1e-6:
            return round(point.sea_surface_temp_f, 1)
        weighted_points.append((distance, point.sea_surface_temp_f))

    weighted_points.sort(key=lambda item: item[0])
    nearest_points = weighted_points[: min(6, len(weighted_points))]
    total_weight = 0.0
    total_temp = 0.0
    for distance, temperature in nearest_points:
        weight = 1 / (distance**2)
        total_weight += weight
        total_temp += temperature * weight
    if total_weight == 0:
        return round(nearest_points[0][1], 1)
    return round(total_temp / total_weight, 1)


@lru_cache(maxsize=96)
def _build_sst_cell_features(
    points: tuple[SstPoint, ...],
    bbox: tuple[float, float, float, float],
) -> tuple[SstMapFeature, ...]:
    if not points:
        return ()

    min_lng, min_lat, max_lng, max_lat = bbox
    columns, rows = _estimate_grid_dimensions(bbox)
    cell_width = (max_lng - min_lng) / columns
    cell_height = (max_lat - min_lat) / rows

    features: list[SstMapFeature] = []
    for row_index in range(rows):
        for column_index in range(columns):
            west = min_lng + (column_index * cell_width)
            east = west + cell_width
            south = min_lat + (row_index * cell_height)
            north = south + cell_height
            center_lng = west + (cell_width / 2)
            center_lat = south + (cell_height / 2)
            temperature = _estimate_cell_temperature(center_lng, center_lat, points=points)
            features.append(
                SstMapFeature(
                    geometry=SstMapPolygonGeometry(
                        coordinates=[
                            [
                                [_round_coordinate(west), _round_coordinate(south)],
                                [_round_coordinate(east), _round_coordinate(south)],
                                [_round_coordinate(east), _round_coordinate(north)],
                                [_round_coordinate(west), _round_coordinate(north)],
                                [_round_coordinate(west), _round_coordinate(south)],
                            ]
                        ]
                    ),
                    properties=SstMapFeatureProperties(sea_surface_temp_f=temperature),
                )
            )
    return tuple(features)


class SstMapService:
    def __init__(self, sst_provider: SstProvider):
        self.sst_provider = sst_provider

    def get_sst_map(
        self,
        *,
        trip_date: date,
        bbox: tuple[float, float, float, float],
    ) -> SstMapResponse:
        min_lng, min_lat, max_lng, max_lat = bbox
        try:
            points = self.sst_provider.get_sst_points(
                trip_date,
                min_lat=min_lat,
                max_lat=max_lat,
                min_lon=min_lng,
                max_lon=max_lng,
            )
            source = getattr(
                self.sst_provider,
                "last_source_name",
                getattr(self.sst_provider, "source_name", "unknown"),
            )
            dataset_id = getattr(
                self.sst_provider,
                "last_dataset_id",
                getattr(self.sst_provider, "configured_dataset_id", None),
            )
            cache_key = getattr(self.sst_provider, "last_cache_key", "")
        except (SstDataUnavailableError, Exception):
            points = ()
            source = "unavailable"
            dataset_id = getattr(self.sst_provider, "configured_dataset_id", None)
            cache_key = ""
            failure_reason = getattr(self.sst_provider, "last_failure_reason", "")
        else:
            failure_reason = getattr(self.sst_provider, "last_failure_reason", "")

        temps = [point.sea_surface_temp_f for point in points]
        temp_range = [round(min(temps), 1), round(max(temps), 1)] if temps else None
        features = list(_build_sst_cell_features(points, bbox))
        logger.info(
            "Resolved /map/sst dataset",
            extra={
                "trip_date": trip_date.isoformat(),
                "bbox": [min_lng, min_lat, max_lng, max_lat],
                "source": source,
                "dataset_id": dataset_id,
                "cache_key": cache_key,
                "failure_reason": failure_reason,
                "point_count": len(points),
                "cell_count": len(features),
            },
        )

        return SstMapResponse(
            metadata=SstMapMetadata(
                date=trip_date,
                bbox=[min_lng, min_lat, max_lng, max_lat],
                source=source,
                dataset_id=dataset_id,
                point_count=len(points),
                cell_count=len(features),
                temp_range_f=temp_range,
            ),
            data=SstMapFeatureCollection(features=features),
        )
