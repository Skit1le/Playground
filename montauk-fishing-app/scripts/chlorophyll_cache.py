from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_APP_ROOT = REPO_ROOT / "apps" / "api"
if str(API_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(API_APP_ROOT))

from app.api.routes.admin import _parse_bbox, _parse_dates  # noqa: E402
from app.api.deps import get_chlorophyll_cache_service  # noqa: E402
from app.services.chlorophyll_cache import ChlorophyllCacheWarmRequest  # noqa: E402

PRESET_BBOXES = {
    "montauk": ("-72.28,40.62,-71.02,41.18",),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Warm or inspect cached chlorophyll snapshots.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    warm_parser = subparsers.add_parser("warm", help="Warm cached chlorophyll snapshots.")
    warm_parser.add_argument("--date", default=None)
    warm_parser.add_argument("--date-from", default=None)
    warm_parser.add_argument("--date-to", default=None)
    warm_parser.add_argument(
        "--bbox",
        action="append",
        default=[],
        help="Repeat minLng,minLat,maxLng,maxLat to warm multiple areas.",
    )
    warm_parser.add_argument(
        "--preset",
        choices=tuple(sorted(PRESET_BBOXES)),
        default=None,
        help="Use a named bbox preset instead of manually providing --bbox values.",
    )
    warm_parser.add_argument("--mode", choices=("live", "processed"), default="live")

    subparsers.add_parser("inspect", help="List cached chlorophyll snapshots.")
    return parser


def run_warm(args: argparse.Namespace) -> int:
    service = get_chlorophyll_cache_service()
    requested_dates = _parse_dates(args.date, args.date_from, args.date_to)
    bbox_inputs = list(args.bbox)
    if args.preset:
        bbox_inputs.extend(PRESET_BBOXES[args.preset])
    if not bbox_inputs:
        raise SystemExit("Provide at least one --bbox or use --preset montauk.")
    parsed_bboxes = tuple(_parse_bbox(value) for value in bbox_inputs)
    response = service.warm_cache(
        ChlorophyllCacheWarmRequest(
            requested_dates=tuple(requested_dates),
            bboxes=parsed_bboxes,
            mode=args.mode,
        )
    )
    print(f"Mode: {response.mode}")
    print(f"Warmed: {response.warmed_count}  Failed: {response.failed_count}")
    for result in response.results:
        bbox = ",".join(f"{value:.4f}" for value in result.bbox)
        if result.success:
            print(
                f"[OK] {result.requested_date.isoformat()} bbox={bbox} source={result.source} "
                f"dataset={result.dataset_id or '-'} points={result.point_count} cache={result.cache_path}"
            )
        else:
            print(
                f"[FAIL] {result.requested_date.isoformat()} bbox={bbox} source={result.source} "
                f"reason={result.failure_reason or 'unknown'}"
            )
    return 0 if response.failed_count == 0 else 1


def run_inspect() -> int:
    service = get_chlorophyll_cache_service()
    response = service.inspect_cache()
    print(f"Cache dir: {response.cache_dir}")
    print(f"Entries: {response.entry_count}")
    for entry in response.entries:
        bbox = ",".join(f"{value:.4f}" for value in entry.bbox)
        age = f"{entry.age_hours:.2f}h" if entry.age_hours is not None else "unknown"
        print(
            f"{entry.requested_date.isoformat()} source={entry.source} dataset={entry.dataset_id or '-'} "
            f"resolved={entry.resolved_timestamp or '-'} age={age} bbox={bbox} path={entry.cache_path}"
        )
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "warm":
        return run_warm(args)
    return run_inspect()


if __name__ == "__main__":
    raise SystemExit(main())
