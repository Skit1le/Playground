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
        self.last_failure_reason = ""
        self.last_resolved_timestamp = "2026-06-18T12:00:00Z"
        self.last_upstream_host = "coastwatch.pfeg.noaa.gov"
        self.last_attempted_urls = ["https://coastwatch.pfeg.noaa.gov/example.csv"]
        self.last_provider_diagnostics = {"attempt_number": 1}
        self.calls: list[tuple[date, float | None, float | None, float | None, float | None]] = []

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]:
        self.calls.append((trip_date, min_lat, max_lat, min_lon, max_lon))
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
        self.assertEqual(response.metadata.source_status, "live")
        self.assertFalse(response.metadata.fallback_used)
        self.assertEqual(response.metadata.dataset_id, "chlorophyll-test")
        self.assertEqual(response.metadata.resolved_data_timestamp, "2026-06-18T12:00:00Z")
        self.assertEqual(response.metadata.upstream_host, "coastwatch.pfeg.noaa.gov")
        self.assertEqual(response.metadata.attempted_urls[0], "https://coastwatch.pfeg.noaa.gov/example.csv")
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
        self.assertEqual(response.metadata.source_status, "unavailable")
        self.assertFalse(response.metadata.live_data_available)
        self.assertEqual(response.metadata.dataset_id, "chlorophyll-test")
        self.assertEqual(response.metadata.point_count, 0)
        self.assertEqual(response.metadata.cell_count, 0)

    def test_get_chlorophyll_break_map_surfaces_fallback_metadata(self) -> None:
        provider = FakeChlorophyllProvider(
            (
                ChlorophyllPoint(latitude=40.9, longitude=-71.9, chlorophyll_mg_m3=0.25),
                ChlorophyllPoint(latitude=41.0, longitude=-71.8, chlorophyll_mg_m3=0.31),
            )
        )
        provider.last_source_name = "mock_fallback"
        provider.last_dataset_id = "configured-live-dataset"
        provider.last_failure_reason = "timeout"
        service = ChlorophyllBreakMapService(provider, target_cells=36)

        response = service.get_chlorophyll_break_map(
            trip_date=date(2026, 6, 18),
            bbox=(-72.2, 40.7, -71.4, 41.1),
        )

        self.assertEqual(response.metadata.source_status, "fallback")
        self.assertTrue(response.metadata.fallback_used)
        self.assertEqual(response.metadata.failure_reason, "timeout")
        self.assertEqual(response.metadata.upstream_host, "coastwatch.pfeg.noaa.gov")
        self.assertGreater(len(response.metadata.warning_messages), 0)
        self.assertEqual(
            response.metadata.warning_messages[0],
            "Showing a local chlorophyll estimate because the live satellite feed could not be reached from this machine.",
        )

    def test_get_chlorophyll_break_map_uses_request_date_and_bbox(self) -> None:
        provider = FakeChlorophyllProvider(
            (
                ChlorophyllPoint(latitude=40.9, longitude=-71.9, chlorophyll_mg_m3=0.25),
                ChlorophyllPoint(latitude=41.0, longitude=-71.8, chlorophyll_mg_m3=0.31),
            )
        )
        service = ChlorophyllBreakMapService(provider, target_cells=36)

        first = service.get_chlorophyll_break_map(
            trip_date=date(2026, 6, 18),
            bbox=(-72.2, 40.7, -71.4, 41.1),
        )
        second = service.get_chlorophyll_break_map(
            trip_date=date(2026, 6, 19),
            bbox=(-72.0, 40.8, -71.6, 41.0),
        )

        self.assertEqual(
            provider.calls,
            [
                (date(2026, 6, 18), 40.7, 41.1, -72.2, -71.4),
                (date(2026, 6, 19), 40.8, 41.0, -72.0, -71.6),
            ],
        )
        self.assertEqual(first.metadata.bbox, [-72.2, 40.7, -71.4, 41.1])
        self.assertEqual(second.metadata.bbox, [-72.0, 40.8, -71.6, 41.0])
        self.assertEqual(first.metadata.date.isoformat(), "2026-06-18")
        self.assertEqual(second.metadata.date.isoformat(), "2026-06-19")

    def test_get_chlorophyll_break_map_reduces_target_density_for_large_bbox(self) -> None:
        provider = FakeChlorophyllProvider(
            (
                ChlorophyllPoint(latitude=40.9, longitude=-71.9, chlorophyll_mg_m3=0.25),
                ChlorophyllPoint(latitude=41.0, longitude=-71.8, chlorophyll_mg_m3=0.31),
            )
        )
        service = ChlorophyllBreakMapService(
            provider,
            target_cells=720,
            reference_bbox=(-72.4, 39.8, -69.8, 41.4),
            minimum_target_cells=180,
        )

        default_bbox_response = service.get_chlorophyll_break_map(
            trip_date=date(2026, 6, 18),
            bbox=(-72.4, 39.8, -69.8, 41.4),
        )
        wide_bbox_response = service.get_chlorophyll_break_map(
            trip_date=date(2026, 6, 18),
            bbox=(-73.0254, 39.9498, -68.3174, 42.0897),
        )

        self.assertLess(wide_bbox_response.metadata.cell_count, default_bbox_response.metadata.cell_count)


if __name__ == "__main__":
    unittest.main()
