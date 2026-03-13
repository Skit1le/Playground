import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy.exc import OperationalError

from app.api.deps import get_zones_service
from app.api.species_config_deps import get_species_config_service
from app.fallback_repositories import InMemorySpeciesConfigRepository, InMemoryZoneRepository
from app.repositories import SpeciesConfigRepository, ZoneRepository
from app.services.species_configs import SpeciesConfigService


def make_request(database_status: str):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status=database_status)))


class BrokenSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalars(self, _statement):
        raise OperationalError("SELECT species configs", {}, Exception("db down"))


class ApiDepsTestCase(unittest.TestCase):
    def test_get_zones_service_uses_database_repositories_when_session_is_healthy(self) -> None:
        session = Mock()

        service = get_zones_service(session)

        self.assertIsInstance(service.zone_repository, ZoneRepository)
        self.assertIsInstance(service.species_config_repository, SpeciesConfigRepository)
        session.execute.assert_called_once()

    def test_get_zones_service_falls_back_to_in_memory_repositories_when_database_is_unavailable(self) -> None:
        session = Mock()
        session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("db down"))

        service = get_zones_service(session)

        self.assertIsInstance(service.zone_repository, InMemoryZoneRepository)
        self.assertIsInstance(service.species_config_repository, InMemorySpeciesConfigRepository)

    def test_get_species_config_service_falls_back_to_in_memory_repository_when_database_is_unavailable(self) -> None:
        service = get_species_config_service(make_request("unavailable"))

        self.assertIsInstance(service.species_config_repository, InMemorySpeciesConfigRepository)

    def test_get_species_config_service_lists_seeded_configs_when_database_is_unavailable(self) -> None:
        service = get_species_config_service(make_request("unavailable"))
        configs = service.list_species_configs()

        self.assertGreaterEqual(len(configs), 1)
        self.assertEqual(configs[0].species, "bluefin")
        self.assertIsNotNone(configs[0].temp_break_config)
        self.assertIsNotNone(configs[0].chlorophyll_break_config)

    def test_species_config_service_falls_back_to_seeded_configs_when_database_session_fails(self) -> None:
        service = SpeciesConfigService(
            session_factory=BrokenSession,
            fallback_repository=InMemorySpeciesConfigRepository(),
        )

        configs = service.list_species_configs()

        self.assertGreaterEqual(len(configs), 1)
        self.assertEqual(configs[0].species, "bluefin")

    def test_get_species_config_service_does_not_depend_on_environmental_provider_setup(self) -> None:
        with patch("app.api.deps.get_environmental_input_provider", side_effect=AssertionError("should not be called")):
            service = get_species_config_service(make_request("unavailable"))

        configs = service.list_species_configs()

        self.assertGreaterEqual(len(configs), 1)
        self.assertEqual(configs[0].species, "bluefin")


if __name__ == "__main__":
    unittest.main()
