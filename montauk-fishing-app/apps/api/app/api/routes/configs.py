import logging
from time import perf_counter

from fastapi import APIRouter, Request

from app.api.species_config_deps import SpeciesConfigServiceDep
from app.schemas import SpeciesConfig

router = APIRouter(prefix="/configs", tags=["configs"])
logger = logging.getLogger(__name__)


@router.get("/species", response_model=list[SpeciesConfig])
def list_species_configs(request: Request, species_config_service: SpeciesConfigServiceDep) -> list[SpeciesConfig]:
    started_at = perf_counter()
    database_status = getattr(request.app.state, "database_status", "unknown")
    logger.info(
        "Handling /configs/species request",
        extra={"database_status": database_status},
    )
    configs = species_config_service.list_species_configs()
    logger.info(
        "Completed /configs/species request",
        extra={
            "database_status": database_status,
            "config_count": len(configs),
            "elapsed_ms": round((perf_counter() - started_at) * 1000, 1),
        },
    )
    return configs
