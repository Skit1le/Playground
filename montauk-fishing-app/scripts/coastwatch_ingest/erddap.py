from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlretrieve

from coastwatch_ingest.config import ProductConfig


@dataclass(frozen=True)
class BoundingBox:
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


@dataclass(frozen=True)
class FetchRequest:
    product: ProductConfig
    target_date: date
    bbox: BoundingBox


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_griddap_csv_url(request: FetchRequest) -> str:
    product = request.product
    variable = product.variable_name
    time_value = request.target_date.isoformat()

    # Configure the dataset ID in `scripts/coastwatch_ingest/config.py`.
    dataset_id = product.dataset_id
    if dataset_id.startswith("CONFIGURE_"):
        raise ValueError(
            f"{product.name} dataset ID has not been configured. "
            "Set the NOAA CoastWatch ERDDAP dataset ID in scripts/coastwatch_ingest/config.py."
        )

    # Configure the base URL in `scripts/coastwatch_ingest/config.py` if you need
    # to use a different ERDDAP host or request path.
    query = (
        f"{variable}[({time_value}T00:00:00Z)]"
        f"[({request.bbox.max_lat}):1:({request.bbox.min_lat})]"
        f"[({request.bbox.min_lon}):1:({request.bbox.max_lon})]"
    )
    encoded_query = quote(query, safe="[]():,")
    return f"{product.base_url}/{dataset_id}.csv?{encoded_query}"


def raw_output_path(request: FetchRequest) -> Path:
    ensure_directory(request.product.raw_root / request.target_date.isoformat())
    return (
        request.product.raw_root
        / request.target_date.isoformat()
        / (
            f"{request.product.name}_"
            f"{request.target_date.isoformat()}_"
            f"{request.bbox.min_lat}_{request.bbox.max_lat}_"
            f"{request.bbox.min_lon}_{request.bbox.max_lon}.csv"
        )
    )


def download_csv(request: FetchRequest) -> tuple[Path, str]:
    output_path = raw_output_path(request)
    url = build_griddap_csv_url(request)
    urlretrieve(url, output_path)
    return output_path, url


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)
