from fastapi import APIRouter

from app.api.deps import DbSession
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.zone_ranking import ZoneRankingService
from app.schemas import SpeciesConfig

router = APIRouter(prefix="/configs", tags=["configs"])


@router.get("/species", response_model=list[SpeciesConfig])
def list_species_configs(session: DbSession) -> list[SpeciesConfig]:
    ranking_service = ZoneRankingService(
        zone_repository=ZoneRepository(session),
        species_config_repository=SpeciesConfigRepository(session),
    )
    return ranking_service.list_species_configs()
