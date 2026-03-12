import unittest
from datetime import date

from app.structure_provider import ProcessedStructureAdapter, StructureDataUnavailableError


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
            {"latitude": 40.95, "longitude": -71.88, "value": 1},
            {"latitude": 40.92, "longitude": -71.82, "value": 1},
            {"latitude": 40.98, "longitude": -71.95, "value": 1},
            {"latitude": 41.02, "longitude": -71.7, "value": 1},
        ]
    }


class ProcessedStructureAdapterTestCase(unittest.TestCase):
    def test_get_zone_structure_uses_processed_payload(self) -> None:
        loader = FakeProcessedProductLoader(make_payload())
        adapter = ProcessedStructureAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        observation = adapter.get_zone_structure("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(observation.structure_distance_nm, 0.0)

    def test_get_zone_structure_caches_repeated_zone_date_requests(self) -> None:
        loader = FakeProcessedProductLoader(make_payload())
        adapter = ProcessedStructureAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        first = adapter.get_zone_structure("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        second = adapter.get_zone_structure("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(first, second)
        self.assertEqual(loader.calls, ["2026-06-18"])

    def test_get_zone_structure_raises_when_processed_payload_is_missing(self) -> None:
        loader = FakeProcessedProductLoader(FileNotFoundError("missing"))
        adapter = ProcessedStructureAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        with self.assertRaises(StructureDataUnavailableError):
            adapter.get_zone_structure("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        with self.assertRaises(StructureDataUnavailableError):
            adapter.get_zone_structure("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(loader.calls, ["2026-06-18"])


if __name__ == "__main__":
    unittest.main()
