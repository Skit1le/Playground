from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession
from app.config import get_settings
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.schemas import RankedZone
from app.zone_ranking import SpeciesConfigNotFoundError, ZoneRankingService

router = APIRouter(tags=["zones"])
settings = get_settings()


@router.get("/zones", response_model=list[RankedZone])
def list_zones(
    session: DbSession,
    date_value: date = Query(alias="date"),
    species: str = Query(pattern="^(bluefin|yellowfin|mahi)$"),
) -> list[RankedZone]:
    ranking_service = ZoneRankingService(
        zone_repository=ZoneRepository(session),
        species_config_repository=SpeciesConfigRepository(session),
    )

    try:
        return ranking_service.rank_zones(
            species=species,
            trip_date=date_value,
            limit=settings.default_zone_limit,
        )
    except SpeciesConfigNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
