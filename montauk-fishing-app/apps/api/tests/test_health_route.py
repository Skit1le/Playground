import unittest
from unittest.mock import patch

from app.api.routes.health import healthcheck


class HealthRouteTestCase(unittest.TestCase):
    def test_healthcheck_reports_ok_when_database_is_available(self) -> None:
        with patch("app.api.routes.health.database_is_available", return_value=True):
            response = healthcheck()

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.database, "ok")

    def test_healthcheck_reports_unavailable_when_database_is_down(self) -> None:
        with patch("app.api.routes.health.database_is_available", return_value=False):
            response = healthcheck()

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.database, "unavailable")


if __name__ == "__main__":
    unittest.main()
