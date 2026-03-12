from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import ZonesServiceDep
from app.config import get_settings
from app.schemas import RankedZone
from app.services.zones import SpeciesConfigNotFoundError

router = APIRouter(tags=["zones"])
settings = get_settings()


@router.get("/zones", response_model=list[RankedZone])
def list_zones(
    zones_service: ZonesServiceDep,
    date_value: date = Query(alias="date"),
    species: str = Query(pattern="^(bluefin|yellowfin|mahi)$"),
) -> list[RankedZone]:
    try:
        return zones_service.list_ranked_zones(
            species=species,
            trip_date=date_value,
            limit=settings.default_zone_limit,
        )
    except SpeciesConfigNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
