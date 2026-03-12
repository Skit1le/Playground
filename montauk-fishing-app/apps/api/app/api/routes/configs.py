from fastapi import APIRouter

from app.api.deps import ZonesServiceDep
from app.schemas import SpeciesConfig

router = APIRouter(prefix="/configs", tags=["configs"])


@router.get("/species", response_model=list[SpeciesConfig])
def list_species_configs(zones_service: ZonesServiceDep) -> list[SpeciesConfig]:
    return zones_service.list_species_configs()
