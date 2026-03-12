from __future__ import annotations

import argparse
from datetime import date

from coastwatch_ingest.erddap import BoundingBox, FetchRequest, download_csv, read_csv_rows
from coastwatch_ingest.processing import build_processed_payload, write_processed_payload


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", required=True, help="Target date in YYYY-MM-DD format.")
    parser.add_argument("--min-lat", required=True, type=float, help="Minimum latitude.")
    parser.add_argument("--max-lat", required=True, type=float, help="Maximum latitude.")
    parser.add_argument("--min-lon", required=True, type=float, help="Minimum longitude.")
    parser.add_argument("--max-lon", required=True, type=float, help="Maximum longitude.")


def run_ingestion(product, args: argparse.Namespace) -> None:
    request = FetchRequest(
        product=product,
        target_date=date.fromisoformat(args.date),
        bbox=BoundingBox(
            min_lat=args.min_lat,
            max_lat=args.max_lat,
            min_lon=args.min_lon,
            max_lon=args.max_lon,
        ),
    )
    raw_path, source_url = download_csv(request)
    rows = read_csv_rows(raw_path)
    payload = build_processed_payload(product, request, raw_path, source_url, rows)
    processed_path = write_processed_payload(product, request, payload)

    print(f"Downloaded raw data to: {raw_path}")
    print(f"Wrote processed output to: {processed_path}")
    print(f"ERDDAP source URL: {source_url}")
