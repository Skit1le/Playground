import unittest
from datetime import date

from app.sst_provider import ProcessedCoastwatchSstAdapter, SstDataUnavailableError


class FakeProcessedProductLoader:
    def __init__(self, payload: dict | Exception):
        self.payload = payload
        self.calls: list[str] = []

    def __call__(
        self,
        product: str,
        target_date: str,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
    ) -> dict:
        self.calls.append(target_date)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def make_payload() -> dict:
    return {
        "grid": [
            {"latitude": 40.95, "longitude": -71.88, "value": 19.0},
            {"latitude": 40.92, "longitude": -71.82, "value": 18.0},
            {"latitude": 40.98, "longitude": -71.95, "value": 20.5},
            {"latitude": 41.02, "longitude": -71.7, "value": 17.5},
        ]
    }


class ProcessedCoastwatchSstAdapterTestCase(unittest.TestCase):
    def test_get_zone_sst_uses_processed_payload(self) -> None:
        loader = FakeProcessedProductLoader(make_payload())
        adapter = ProcessedCoastwatchSstAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        observation = adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(observation.sea_surface_temp_f, 66.2)
        self.assertGreater(observation.temp_gradient_f_per_nm, 0)

    def test_get_zone_sst_caches_repeated_zone_date_requests(self) -> None:
        loader = FakeProcessedProductLoader(make_payload())
        adapter = ProcessedCoastwatchSstAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        first = adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        second = adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(first, second)
        self.assertEqual(loader.calls, ["2026-06-18"])

    def test_get_zone_sst_raises_when_processed_payload_is_missing(self) -> None:
        loader = FakeProcessedProductLoader(FileNotFoundError("missing"))
        adapter = ProcessedCoastwatchSstAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        with self.assertRaises(SstDataUnavailableError):
            adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        with self.assertRaises(SstDataUnavailableError):
            adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(loader.calls, ["2026-06-18"])


if __name__ == "__main__":
    unittest.main()
