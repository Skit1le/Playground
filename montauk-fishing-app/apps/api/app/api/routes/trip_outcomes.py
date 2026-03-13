from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import TripOutcomeServiceDep
from app.schemas import TripOutcomeCreate, TripOutcomeRecord, TripOutcomeUpdate
from app.services.trip_outcomes import TripOutcomeNotFoundError

router = APIRouter(prefix="/trip-outcomes", tags=["trip-outcomes"])


def _ensure_database_available(request: Request) -> None:
    if getattr(request.app.state, "database_status", "unknown") == "ok":
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Trip outcome persistence requires the database to be available.",
    )


@router.get("", response_model=list[TripOutcomeRecord])
def list_trip_outcomes(
    request: Request,
    trip_outcome_service: TripOutcomeServiceDep,
) -> list[TripOutcomeRecord]:
    _ensure_database_available(request)
    return trip_outcome_service.list_outcomes()


@router.post("", response_model=TripOutcomeRecord, status_code=status.HTTP_201_CREATED)
def create_trip_outcome(
    payload: TripOutcomeCreate,
    request: Request,
    trip_outcome_service: TripOutcomeServiceDep,
) -> TripOutcomeRecord:
    _ensure_database_available(request)
    return trip_outcome_service.create_outcome(payload)


@router.put("/{outcome_id}", response_model=TripOutcomeRecord)
def update_trip_outcome(
    outcome_id: int,
    payload: TripOutcomeUpdate,
    request: Request,
    trip_outcome_service: TripOutcomeServiceDep,
) -> TripOutcomeRecord:
    _ensure_database_available(request)
    try:
        return trip_outcome_service.update_outcome(outcome_id, payload)
    except TripOutcomeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{outcome_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip_outcome(
    outcome_id: int,
    request: Request,
    trip_outcome_service: TripOutcomeServiceDep,
) -> Response:
    _ensure_database_available(request)
    try:
        trip_outcome_service.delete_outcome(outcome_id)
    except TripOutcomeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
