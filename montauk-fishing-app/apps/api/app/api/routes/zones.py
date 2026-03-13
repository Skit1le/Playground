from fastapi import APIRouter, HTTPException, Query, status

from app.api.date_params import parse_api_date
from app.api.deps import ZonesServiceDep
from app.config import get_settings
from app.schemas import RankedZone
from app.services.zones import SpeciesConfigNotFoundError

router = APIRouter(tags=["zones"])
settings = get_settings()


@router.get("/zones", response_model=list[RankedZone])
def list_zones(
    zones_service: ZonesServiceDep,
    date_value: str = Query(
        alias="date",
        description="Trip date. Preferred format: YYYY-MM-DD. MM-DD-YYYY and MM/DD/YYYY are also accepted.",
    ),
    species: str = Query(pattern="^(bluefin|yellowfin|mahi)$"),
) -> list[RankedZone]:
    trip_date = parse_api_date(date_value)
    try:
        return zones_service.list_ranked_zones(
            species=species,
            trip_date=trip_date,
            limit=settings.default_zone_limit,
        )
    except SpeciesConfigNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
