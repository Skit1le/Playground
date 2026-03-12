from fastapi import APIRouter

from app.api.deps import DbSession
from app.repositories import SpeciesConfigRepository
from app.scoring import build_species_config
from app.schemas import SpeciesConfig

router = APIRouter(prefix="/configs", tags=["configs"])


@router.get("/species", response_model=list[SpeciesConfig])
def list_species_configs(session: DbSession) -> list[SpeciesConfig]:
    repository = SpeciesConfigRepository(session)
    return [build_species_config(config) for config in repository.list_all()]
