from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.seed_data import SPECIES_SCORING_CONFIGS, ZONE_CATALOG


class InMemorySpeciesConfigRepository:
    def __init__(self) -> None:
        self._configs = [SpeciesScoringConfigModel(**config) for config in SPECIES_SCORING_CONFIGS]

    def list_all(self) -> list[SpeciesScoringConfigModel]:
        return sorted(self._configs, key=lambda config: config.label)

    def get_by_species(self, species: str) -> SpeciesScoringConfigModel | None:
        return next((config for config in self._configs if config.species == species), None)


class InMemoryZoneRepository:
    def __init__(self) -> None:
        self._zones = [ZoneModel(**zone) for zone in ZONE_CATALOG]

    def list_all(self) -> list[ZoneModel]:
        return sorted(self._zones, key=lambda zone: zone.distance_nm)

    def list_for_species(self, species: str) -> list[ZoneModel]:
        return [zone for zone in self.list_all() if species in zone.species]
