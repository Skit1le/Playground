from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.date_params import parse_api_date
from app.api.deps import (
    ChlorophyllCacheServiceDep,
    HistoricalSnapshotServiceDep,
    TripOutcomeServiceDep,
)
from app.services.chlorophyll_cache import ChlorophyllCacheWarmRequest
from app.schemas import (
    ChlorophyllCacheInspectionResponse,
    ChlorophyllCacheWarmResponse,
    OutcomeBacktestReport,
    ZoneSnapshotCaptureResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _ensure_database_available(request: Request) -> None:
    if getattr(request.app.state, "database_status", "unknown") == "ok":
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Admin persistence/report endpoints require the database to be available.",
    )


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        min_lng_text, min_lat_text, max_lng_text, max_lat_text = value.split(",")
        bbox = (
            float(min_lng_text),
            float(min_lat_text),
            float(max_lng_text),
            float(max_lat_text),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be 'minLng,minLat,maxLng,maxLat'.",
        ) from exc
    min_lng, min_lat, max_lng, max_lat = bbox
    if min_lng >= max_lng or min_lat >= max_lat:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox must be ordered as minLng,minLat,maxLng,maxLat.",
        )
    return bbox


def _parse_dates(date_value: str | None, date_from: str | None, date_to: str | None) -> list[date]:
    if date_value:
        return [parse_api_date(date_value)]
    if not date_from or not date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either date or both date_from and date_to.",
        )
    start = parse_api_date(date_from)
    end = parse_api_date(date_to)
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_from must be on or before date_to.",
        )
    dates: list[date] = []
    current = start
    while current <= end:
        dates.append(current)
        current = current.fromordinal(current.toordinal() + 1)
    return dates


@router.post("/chlorophyll-cache/warm", response_model=ChlorophyllCacheWarmResponse)
def warm_chlorophyll_cache(
    chlorophyll_cache_service: ChlorophyllCacheServiceDep,
    date_value: str | None = Query(default=None, alias="date"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    bbox: list[str] = Query(..., description="Repeat bbox=minLng,minLat,maxLng,maxLat for multiple areas."),
    mode: str = Query(default="live", pattern="^(live|processed)$"),
) -> ChlorophyllCacheWarmResponse:
    requested_dates = _parse_dates(date_value, date_from, date_to)
    parsed_bboxes = tuple(_parse_bbox(value) for value in bbox)
    return chlorophyll_cache_service.warm_cache(
        ChlorophyllCacheWarmRequest(
            requested_dates=tuple(requested_dates),
            bboxes=parsed_bboxes,
            mode=mode,
        )
    )


@router.get("/chlorophyll-cache", response_model=ChlorophyllCacheInspectionResponse)
def inspect_chlorophyll_cache(
    chlorophyll_cache_service: ChlorophyllCacheServiceDep,
) -> ChlorophyllCacheInspectionResponse:
    return chlorophyll_cache_service.inspect_cache()


@router.post("/zone-score-snapshots/capture", response_model=ZoneSnapshotCaptureResponse)
def capture_zone_score_snapshots(
    request: Request,
    historical_snapshot_service: HistoricalSnapshotServiceDep,
    date_value: str = Query(alias="date"),
    species: str = Query(pattern="^(bluefin|yellowfin|mahi)$"),
    limit: int = Query(default=10, ge=1, le=100),
) -> ZoneSnapshotCaptureResponse:
    _ensure_database_available(request)
    trip_date = parse_api_date(date_value)
    return historical_snapshot_service.capture_snapshots(
        trip_date=trip_date,
        species=species,
        limit=limit,
    )


@router.get("/backtests/report", response_model=OutcomeBacktestReport)
def get_backtest_report(
    request: Request,
    historical_snapshot_service: HistoricalSnapshotServiceDep,
    trip_outcome_service: TripOutcomeServiceDep,
    species: str | None = Query(default=None, pattern="^(bluefin|yellowfin|mahi)$"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> OutcomeBacktestReport:
    _ensure_database_available(request)
    parsed_date_from: date | None = parse_api_date(date_from) if date_from else None
    parsed_date_to: date | None = parse_api_date(date_to) if date_to else None
    outcomes = trip_outcome_service.list_outcomes()
    if species:
        outcomes = [outcome for outcome in outcomes if outcome.target_species == species]
    if parsed_date_from:
        outcomes = [outcome for outcome in outcomes if outcome.date >= parsed_date_from]
    if parsed_date_to:
        outcomes = [outcome for outcome in outcomes if outcome.date <= parsed_date_to]
    return historical_snapshot_service.build_backtest_report(
        outcomes=outcomes,
        species=species,
        date_from=parsed_date_from,
        date_to=parsed_date_to,
    )
