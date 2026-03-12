from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from coastwatch_ingest.config import ProductConfig
from coastwatch_ingest.erddap import BoundingBox, FetchRequest, ensure_directory


@dataclass(frozen=True)
class ProcessedGridPoint:
    latitude: float
    longitude: float
    value: float


def _first_matching_key(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for key in row:
        lowered = key.lower()
        if any(candidate in lowered for candidate in candidates):
            return key
    raise KeyError(f"Could not find a matching key for candidates: {candidates}")


def _rounded(value: float) -> float:
    return round(value, 4)


def build_processed_payload(
    product: ProductConfig,
    request: FetchRequest,
    raw_path: Path,
    source_url: str,
    rows: list[dict[str, str]],
) -> dict:
    if not rows:
        raise ValueError("No rows were returned from the ERDDAP request.")

    lat_key = _first_matching_key(rows[0], ("latitude", "lat"))
    lon_key = _first_matching_key(rows[0], ("longitude", "lon"))
    value_key = _first_matching_key(rows[0], tuple(candidate.lower() for candidate in product.value_column_candidates))

    points: list[ProcessedGridPoint] = []
    for row in rows:
        raw_value = row.get(value_key)
        if raw_value in (None, "", "NaN"):
            continue
        points.append(
            ProcessedGridPoint(
                latitude=float(row[lat_key]),
                longitude=float(row[lon_key]),
                value=float(raw_value),
            )
        )

    if not points:
        raise ValueError("No usable values were found in the ERDDAP response.")

    values = [point.value for point in points]
    return {
        "product": product.name,
        "variable_name": product.variable_name,
        "dataset_id": product.dataset_id,
        "source_url": source_url,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {
            "date": request.target_date.isoformat(),
            "bounding_box": asdict(request.bbox),
        },
        "raw_file": str(raw_path),
        "summary": {
            "count": len(points),
            "min": _rounded(min(values)),
            "max": _rounded(max(values)),
            "mean": _rounded(sum(values) / len(values)),
        },
        "grid": [asdict(point) for point in points],
    }


def processed_output_path(product: ProductConfig, request: FetchRequest) -> Path:
    ensure_directory(product.processed_root / request.target_date.isoformat())
    return (
        product.processed_root
        / request.target_date.isoformat()
        / (
            f"{product.name}_"
            f"{request.target_date.isoformat()}_"
            f"{request.bbox.min_lat}_{request.bbox.max_lat}_"
            f"{request.bbox.min_lon}_{request.bbox.max_lon}.json"
        )
    )


def write_processed_payload(product: ProductConfig, request: FetchRequest, payload: dict) -> Path:
    output_path = processed_output_path(product, request)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return output_path
