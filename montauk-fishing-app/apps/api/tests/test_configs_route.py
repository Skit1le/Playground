import unittest
from types import SimpleNamespace

from app.api.routes.configs import list_species_configs
from app.fallback_repositories import InMemorySpeciesConfigRepository
from app.schemas import SpeciesConfig, WeightedScoreConfig
from app.services.species_configs import SpeciesConfigService


class FakeSpeciesConfigService:
    def __init__(self, response: list[SpeciesConfig] | None = None):
        self.response = response or []
        self.calls = 0

    def list_species_configs(self) -> list[SpeciesConfig]:
        self.calls += 1
        return self.response


def make_species_config() -> SpeciesConfig:
    return SpeciesConfig(
        species="bluefin",
        label="Bluefin Tuna",
        season_window="May-November",
        notes="Seeded local-dev fallback config",
        preferred_temp_f=[58.0, 66.0],
        ideal_chlorophyll_mg_m3=[0.22, 0.42],
        ideal_current_kts=[1.1, 2.0],
        weights=WeightedScoreConfig(
            temp_suitability=0.24,
            temp_gradient=0.16,
            structure_proximity=0.18,
            chlorophyll_suitability=0.11,
            current_suitability=0.13,
            weather_fishability=0.18,
        ),
    )


class ConfigsRouteTestCase(unittest.TestCase):
    def test_list_species_configs_delegates_to_service(self) -> None:
        fake_service = FakeSpeciesConfigService(response=[make_species_config()])
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status="unavailable")))

        response = list_species_configs(request=request, species_config_service=fake_service)

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0].species, "bluefin")
        self.assertEqual(fake_service.calls, 1)

    def test_species_config_service_returns_seeded_configs_in_degraded_local_mode(self) -> None:
        service = SpeciesConfigService(species_config_repository=InMemorySpeciesConfigRepository())

        response = service.list_species_configs()

        self.assertGreaterEqual(len(response), 1)
        self.assertEqual(response[0].species, "bluefin")


if __name__ == "__main__":
    unittest.main()
