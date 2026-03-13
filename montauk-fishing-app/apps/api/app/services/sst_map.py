from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from math import cos, radians, sqrt
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


@dataclass(frozen=True)
class SstCellSignal:
    west: float
    south: float
    east: float
    north: float
    center_lng: float
    center_lat: float
    sea_surface_temp_f: float
    break_intensity_f_per_nm: float


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


def _nm_per_degree_lon(latitude: float) -> float:
    return max(cos(radians(latitude)) * 60.0, 0.01)


def _compute_break_intensity_grid(
    temperatures: tuple[tuple[float, ...], ...],
    *,
    mean_latitude: float,
    cell_width_degrees: float,
    cell_height_degrees: float,
) -> tuple[tuple[float, ...], ...]:
    rows = len(temperatures)
    columns = len(temperatures[0]) if rows else 0
    if rows == 0 or columns == 0:
        return ()

    dx_nm = max(cell_width_degrees * _nm_per_degree_lon(mean_latitude), 0.01)
    dy_nm = max(cell_height_degrees * 60.0, 0.01)

    gradient_rows: list[tuple[float, ...]] = []
    for row_index in range(rows):
        gradient_row: list[float] = []
        for column_index in range(columns):
            left_index = max(column_index - 1, 0)
            right_index = min(column_index + 1, columns - 1)
            south_index = max(row_index - 1, 0)
            north_index = min(row_index + 1, rows - 1)

            delta_x_cells = max(right_index - left_index, 1)
            delta_y_cells = max(north_index - south_index, 1)

            d_temp_dx = (
                temperatures[row_index][right_index] - temperatures[row_index][left_index]
            ) / (delta_x_cells * dx_nm)
            d_temp_dy = (
                temperatures[north_index][column_index] - temperatures[south_index][column_index]
            ) / (delta_y_cells * dy_nm)
            gradient_row.append(round(sqrt((d_temp_dx**2) + (d_temp_dy**2)), 4))
        gradient_rows.append(tuple(gradient_row))
    return tuple(gradient_rows)


def nearest_strong_break_distance_nm(
    *,
    latitude: float,
    longitude: float,
    cells: tuple[SstCellSignal, ...],
    minimum_break_intensity_f_per_nm: float,
) -> float | None:
    strong_breaks = [
        sqrt(((cell.center_lng - longitude) * _nm_per_degree_lon(latitude)) ** 2 + ((cell.center_lat - latitude) * 60.0) ** 2)
        for cell in cells
        if cell.break_intensity_f_per_nm >= minimum_break_intensity_f_per_nm
    ]
    if not strong_breaks:
        return None
    return round(min(strong_breaks), 3)


@lru_cache(maxsize=96)
def build_sst_cell_signals(
    points: tuple[SstPoint, ...],
    bbox: tuple[float, float, float, float],
    target_cells: int,
) -> tuple[SstCellSignal, ...]:
    if not points:
        return ()

    min_lng, min_lat, max_lng, max_lat = bbox
    columns, rows = _estimate_grid_dimensions(bbox, target_cells=target_cells)
    cell_width = (max_lng - min_lng) / columns
    cell_height = (max_lat - min_lat) / rows
    temperatures: list[tuple[float, ...]] = []
    for row_index in range(rows):
        row_temperatures: list[float] = []
        for column_index in range(columns):
            west = min_lng + (column_index * cell_width)
            south = min_lat + (row_index * cell_height)
            center_lng = west + (cell_width / 2)
            center_lat = south + (cell_height / 2)
            row_temperatures.append(_estimate_cell_temperature(center_lng, center_lat, points=points))
        temperatures.append(tuple(row_temperatures))

    break_intensities = _compute_break_intensity_grid(
        tuple(temperatures),
        mean_latitude=(min_lat + max_lat) / 2,
        cell_width_degrees=cell_width,
        cell_height_degrees=cell_height,
    )

    cells: list[SstCellSignal] = []
    for row_index in range(rows):
        for column_index in range(columns):
            west = min_lng + (column_index * cell_width)
            east = west + cell_width
            south = min_lat + (row_index * cell_height)
            north = south + cell_height
            center_lng = west + (cell_width / 2)
            center_lat = south + (cell_height / 2)
            cells.append(
                SstCellSignal(
                    west=_round_coordinate(west),
                    south=_round_coordinate(south),
                    east=_round_coordinate(east),
                    north=_round_coordinate(north),
                    center_lng=_round_coordinate(center_lng),
                    center_lat=_round_coordinate(center_lat),
                    sea_surface_temp_f=temperatures[row_index][column_index],
                    break_intensity_f_per_nm=break_intensities[row_index][column_index],
                )
            )
    return tuple(cells)


def _build_feature_collection(cells: tuple[SstCellSignal, ...]) -> tuple[SstMapFeature, ...]:
    features: list[SstMapFeature] = []
    for cell in cells:
        features.append(
            SstMapFeature(
                geometry=SstMapPolygonGeometry(
                    coordinates=[
                        [
                            [cell.west, cell.south],
                            [cell.east, cell.south],
                            [cell.east, cell.north],
                            [cell.west, cell.north],
                            [cell.west, cell.south],
                        ]
                    ]
                ),
                properties=SstMapFeatureProperties(
                    sea_surface_temp_f=cell.sea_surface_temp_f,
                    break_intensity_f_per_nm=cell.break_intensity_f_per_nm,
                ),
            )
        )
    return tuple(features)


class SstMapService:
    def __init__(self, sst_provider: SstProvider, target_cells: int = 480):
        self.sst_provider = sst_provider
        self.target_cells = target_cells

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
        cells = build_sst_cell_signals(points, bbox, self.target_cells)
        features = list(_build_feature_collection(cells))
        columns, rows = _estimate_grid_dimensions(bbox, target_cells=self.target_cells)
        break_intensities = [cell.break_intensity_f_per_nm for cell in cells]
        break_range = (
            [round(min(break_intensities), 4), round(max(break_intensities), 4)] if break_intensities else None
        )
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
                "break_intensity_range": break_range,
                "grid_resolution": [columns, rows],
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
                break_intensity_range=break_range,
                grid_resolution=[columns, rows] if features else None,
            ),
            data=SstMapFeatureCollection(features=features),
        )
