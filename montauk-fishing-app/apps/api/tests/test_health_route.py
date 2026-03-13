import unittest
from types import SimpleNamespace

from app.api.routes.health import healthcheck


def make_request(database_status: str):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status=database_status)))


class HealthRouteTestCase(unittest.TestCase):
    def test_healthcheck_reports_ok_when_database_started_successfully(self) -> None:
        response = healthcheck(make_request("ok"))

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.database, "ok")

    def test_healthcheck_reports_unavailable_when_running_in_degraded_local_mode(self) -> None:
        response = healthcheck(make_request("unavailable"))

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.database, "unavailable")

    def test_healthcheck_reports_unknown_before_startup_sets_database_status(self) -> None:
        response = healthcheck(make_request("unknown"))

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.database, "unknown")


if __name__ == "__main__":
    unittest.main()
