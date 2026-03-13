import unittest
from datetime import date

from app.chlorophyll_provider import ChlorophyllDataUnavailableError, ChlorophyllPoint
from app.services.chlorophyll_map import ChlorophyllBreakMapService


class FakeChlorophyllProvider:
    def __init__(self, points: tuple[ChlorophyllPoint, ...] | Exception):
        self.points = points
        self.last_source_name = "live"
        self.last_dataset_id = "chlorophyll-test"
        self.last_cache_key = "2026-06-18|-72.4,39.8,-69.8,41.4"

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]:
        if isinstance(self.points, Exception):
            raise self.points
        return self.points


class ChlorophyllBreakMapServiceTestCase(unittest.TestCase):
    def test_get_chlorophyll_break_map_returns_polygon_cells(self) -> None:
        provider = FakeChlorophyllProvider(
            (
                ChlorophyllPoint(latitude=40.8, longitude=-72.2, chlorophyll_mg_m3=0.12),
                ChlorophyllPoint(latitude=40.8, longitude=-71.4, chlorophyll_mg_m3=0.22),
                ChlorophyllPoint(latitude=41.1, longitude=-72.2, chlorophyll_mg_m3=0.28),
                ChlorophyllPoint(latitude=41.1, longitude=-71.4, chlorophyll_mg_m3=0.36),
            )
        )
        service = ChlorophyllBreakMapService(provider, target_cells=64)

        response = service.get_chlorophyll_break_map(
            trip_date=date(2026, 6, 18),
            bbox=(-72.4, 39.8, -69.8, 41.4),
        )

        self.assertEqual(response.metadata.source, "live")
        self.assertEqual(response.metadata.dataset_id, "chlorophyll-test")
        self.assertGreater(response.metadata.point_count, 0)
        self.assertGreater(response.metadata.cell_count, 0)
        self.assertIsNotNone(response.metadata.break_intensity_range_mg_m3_per_nm)
        self.assertEqual(response.data.features[0].geometry.type, "Polygon")

    def test_get_chlorophyll_break_map_returns_empty_unavailable_payload_when_provider_fails(self) -> None:
        provider = FakeChlorophyllProvider(ChlorophyllDataUnavailableError("missing chlorophyll"))
        service = ChlorophyllBreakMapService(provider, target_cells=64)

        response = service.get_chlorophyll_break_map(
            trip_date=date(2026, 6, 18),
            bbox=(-72.4, 39.8, -69.8, 41.4),
        )

        self.assertEqual(response.metadata.source, "unavailable")
        self.assertEqual(response.metadata.dataset_id, "chlorophyll-test")
        self.assertEqual(response.metadata.point_count, 0)
        self.assertEqual(response.metadata.cell_count, 0)


if __name__ == "__main__":
    unittest.main()
