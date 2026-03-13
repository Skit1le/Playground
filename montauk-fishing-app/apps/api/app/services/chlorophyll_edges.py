from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import cos, radians, sqrt

from app.chlorophyll_provider import ChlorophyllPoint


@dataclass(frozen=True)
class ChlorophyllCellSignal:
    center_lng: float
    center_lat: float
    chlorophyll_mg_m3: float
    break_intensity_mg_m3_per_nm: float


def _nm_per_degree_lon(latitude: float) -> float:
    return max(cos(radians(latitude)) * 60.0, 0.01)


def _estimate_grid_dimensions(
    bbox: tuple[float, float, float, float],
    *,
    target_cells: int,
) -> tuple[int, int]:
    min_lng, min_lat, max_lng, max_lat = bbox
    lng_span = max(max_lng - min_lng, 0.01)
    lat_span = max(max_lat - min_lat, 0.01)
    aspect_ratio = max(lng_span / lat_span, 0.35)
    columns = max(6, round((target_cells * aspect_ratio) ** 0.5))
    rows = max(5, round(target_cells / columns))
    return columns, rows


def _estimate_cell_chlorophyll(
    center_lng: float,
    center_lat: float,
    *,
    points: tuple[ChlorophyllPoint, ...],
) -> float:
    weighted_points: list[tuple[float, float]] = []
    for point in points:
        distance = sqrt((point.longitude - center_lng) ** 2 + (point.latitude - center_lat) ** 2)
        if distance <= 1e-6:
            return round(point.chlorophyll_mg_m3, 4)
        weighted_points.append((distance, point.chlorophyll_mg_m3))

    weighted_points.sort(key=lambda item: item[0])
    nearest_points = weighted_points[: min(6, len(weighted_points))]
    total_weight = 0.0
    total_value = 0.0
    for distance, value in nearest_points:
        weight = 1 / (distance**2)
        total_weight += weight
        total_value += value * weight
    if total_weight == 0:
        return round(nearest_points[0][1], 4)
    return round(total_value / total_weight, 4)


def _compute_break_intensity_grid(
    values: tuple[tuple[float, ...], ...],
    *,
    mean_latitude: float,
    cell_width_degrees: float,
    cell_height_degrees: float,
) -> tuple[tuple[float, ...], ...]:
    rows = len(values)
    columns = len(values[0]) if rows else 0
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
            d_value_dx = (values[row_index][right_index] - values[row_index][left_index]) / (delta_x_cells * dx_nm)
            d_value_dy = (values[north_index][column_index] - values[south_index][column_index]) / (
                delta_y_cells * dy_nm
            )
            gradient_row.append(round(sqrt((d_value_dx**2) + (d_value_dy**2)), 5))
        gradient_rows.append(tuple(gradient_row))
    return tuple(gradient_rows)


@lru_cache(maxsize=96)
def build_chlorophyll_cell_signals(
    points: tuple[ChlorophyllPoint, ...],
    bbox: tuple[float, float, float, float],
    target_cells: int,
) -> tuple[ChlorophyllCellSignal, ...]:
    if not points:
        return ()

    min_lng, min_lat, max_lng, max_lat = bbox
    columns, rows = _estimate_grid_dimensions(bbox, target_cells=target_cells)
    cell_width = (max_lng - min_lng) / columns
    cell_height = (max_lat - min_lat) / rows

    values: list[tuple[float, ...]] = []
    for row_index in range(rows):
        row_values: list[float] = []
        for column_index in range(columns):
            west = min_lng + (column_index * cell_width)
            south = min_lat + (row_index * cell_height)
            center_lng = west + (cell_width / 2)
            center_lat = south + (cell_height / 2)
            row_values.append(_estimate_cell_chlorophyll(center_lng, center_lat, points=points))
        values.append(tuple(row_values))

    break_intensities = _compute_break_intensity_grid(
        tuple(values),
        mean_latitude=(min_lat + max_lat) / 2,
        cell_width_degrees=cell_width,
        cell_height_degrees=cell_height,
    )

    cells: list[ChlorophyllCellSignal] = []
    for row_index in range(rows):
        for column_index in range(columns):
            center_lng = min_lng + (column_index * cell_width) + (cell_width / 2)
            center_lat = min_lat + (row_index * cell_height) + (cell_height / 2)
            cells.append(
                ChlorophyllCellSignal(
                    center_lng=round(center_lng, 5),
                    center_lat=round(center_lat, 5),
                    chlorophyll_mg_m3=values[row_index][column_index],
                    break_intensity_mg_m3_per_nm=break_intensities[row_index][column_index],
                )
            )
    return tuple(cells)


def nearest_strong_chlorophyll_break_distance_nm(
    *,
    latitude: float,
    longitude: float,
    cells: tuple[ChlorophyllCellSignal, ...],
    minimum_break_intensity_mg_m3_per_nm: float,
) -> float | None:
    strong_breaks = [
        sqrt(((cell.center_lng - longitude) * _nm_per_degree_lon(latitude)) ** 2 + ((cell.center_lat - latitude) * 60.0) ** 2)
        for cell in cells
        if cell.break_intensity_mg_m3_per_nm >= minimum_break_intensity_mg_m3_per_nm
    ]
    if not strong_breaks:
        return None
    return round(min(strong_breaks), 3)
