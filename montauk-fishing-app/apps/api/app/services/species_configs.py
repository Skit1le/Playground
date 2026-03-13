from collections.abc import Callable

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.repositories import SpeciesConfigRepository
from app.fallback_repositories import InMemorySpeciesConfigRepository
from app.db_models import SpeciesScoringConfigModel
from app.schemas import SpeciesConfig
from app.services.zones import build_species_config


class SpeciesConfigService:
    def __init__(
        self,
        species_config_repository: SpeciesConfigRepository | InMemorySpeciesConfigRepository | None = None,
        *,
        session_factory: Callable[[], Session] | None = None,
        fallback_repository: InMemorySpeciesConfigRepository | None = None,
    ):
        self.species_config_repository = species_config_repository
        self.session_factory = session_factory
        self.fallback_repository = fallback_repository or InMemorySpeciesConfigRepository()

    def _list_config_models(self) -> list[SpeciesScoringConfigModel]:
        if self.session_factory is not None:
            try:
                with self.session_factory() as session:
                    return SpeciesConfigRepository(session).list_all()
            except OperationalError:
                return self.fallback_repository.list_all()

        repository = self.species_config_repository or self.fallback_repository
        return repository.list_all()

    def list_species_configs(self) -> list[SpeciesConfig]:
        configs = self._list_config_models()
        return [build_species_config(config) for config in configs]
