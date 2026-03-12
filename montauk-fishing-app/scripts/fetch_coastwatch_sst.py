from __future__ import annotations

import argparse

from coastwatch_ingest.cli import add_common_arguments, run_ingestion
from coastwatch_ingest.config import SST_PRODUCT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch NOAA CoastWatch ERDDAP SST data for a date and bounding box."
    )
    add_common_arguments(parser)
    return parser


if __name__ == "__main__":
    run_ingestion(SST_PRODUCT, build_parser().parse_args())
