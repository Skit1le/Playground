from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession
from app.config import get_settings
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.scoring import ZoneScoringService, build_ranked_zone
from app.schemas import RankedZone

router = APIRouter(tags=["zones"])
settings = get_settings()


@router.get("/zones", response_model=list[RankedZone])
def list_zones(
    session: DbSession,
    date_value: date = Query(alias="date"),
    species: str = Query(pattern="^(bluefin|yellowfin|mahi)$"),
) -> list[RankedZone]:
    species_repository = SpeciesConfigRepository(session)
    zone_repository = ZoneRepository(session)
    scoring_service = ZoneScoringService()

    config = species_repository.get_by_species(species)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scoring configuration found for species '{species}'.",
        )

    zones = zone_repository.list_for_species(species)
    ranked = [
        build_ranked_zone(zone, species, date_value, scoring_service.score_zone(zone, config, date_value))
        for zone in zones
    ]

    ranked.sort(key=lambda zone: zone.score, reverse=True)
    return ranked[: settings.default_zone_limit]
