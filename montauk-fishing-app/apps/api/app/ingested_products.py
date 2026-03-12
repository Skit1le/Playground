from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed" / "coastwatch"


def processed_product_path(
    product: str,
    target_date: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> Path:
    return (
        PROCESSED_ROOT
        / product
        / target_date
        / f"{product}_{target_date}_{min_lat}_{max_lat}_{min_lon}_{max_lon}.json"
    )


def load_processed_product(
    product: str,
    target_date: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> dict[str, Any]:
    path = processed_product_path(product, target_date, min_lat, max_lat, min_lon, max_lon)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
