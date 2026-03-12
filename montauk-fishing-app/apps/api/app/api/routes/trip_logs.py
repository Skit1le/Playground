from fastapi import APIRouter

from app.schemas import TripLog
from app.seed_data import TRIP_LOGS

router = APIRouter(tags=["trip-logs"])


@router.get("/trip-logs", response_model=list[TripLog])
def list_trip_logs() -> list[TripLog]:
    return [TripLog(**trip) for trip in TRIP_LOGS]
