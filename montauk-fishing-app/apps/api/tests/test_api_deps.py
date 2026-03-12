import unittest
from unittest.mock import Mock

from sqlalchemy.exc import OperationalError

from app.api.deps import get_zones_service
from app.fallback_repositories import InMemorySpeciesConfigRepository, InMemoryZoneRepository
from app.repositories import SpeciesConfigRepository, ZoneRepository


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


if __name__ == "__main__":
    unittest.main()
