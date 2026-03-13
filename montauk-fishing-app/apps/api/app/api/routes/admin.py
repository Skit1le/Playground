from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.date_params import parse_api_date
from app.api.deps import HistoricalSnapshotServiceDep, TripOutcomeServiceDep
from app.schemas import OutcomeBacktestReport, ZoneSnapshotCaptureResponse

router = APIRouter(prefix="/admin", tags=["admin"])


def _ensure_database_available(request: Request) -> None:
    if getattr(request.app.state, "database_status", "unknown") == "ok":
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Admin persistence/report endpoints require the database to be available.",
    )


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
