import unittest
from datetime import date

from app.services.sst_map import SstMapService
from app.sst_provider import SstDataUnavailableError, SstObservation, SstPoint


class FakeSstProvider:
    def __init__(
        self,
        *,
        points: tuple[SstPoint, ...] | Exception,
        source_name: str = "processed",
    ):
        self.points = points
        self.source_name = source_name
        self.configured_dataset_id = "noaacwBLENDEDsstDaily" if source_name == "live" else None
        self.last_source_name = source_name
        self.last_dataset_id = "noaacwBLENDEDsstDaily" if source_name == "live" else None
        self.last_cache_key = "2026-06-18|-72.4,39.8,-69.8,41.4"
        self.last_failure_reason = ""

    def get_zone_sst(self, zone_id: str, latitude: float, longitude: float, trip_date: date) -> SstObservation:
        return SstObservation(sea_surface_temp_f=66.0, temp_gradient_f_per_nm=1.2)

    def get_sst_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[SstPoint, ...]:
        if isinstance(self.points, Exception):
            raise self.points
        return self.points


class SstMapServiceTestCase(unittest.TestCase):
    def test_get_sst_map_returns_geojson_features_and_metadata(self) -> None:
        service = SstMapService(
            sst_provider=FakeSstProvider(
                points=(
                    SstPoint(latitude=40.95, longitude=-71.88, sea_surface_temp_f=66.2),
                    SstPoint(latitude=40.98, longitude=-71.81, sea_surface_temp_f=67.1),
                ),
                source_name="live",
            )
        )

        response = service.get_sst_map(
            trip_date=date(2026, 6, 18),
            bbox=(-72.4, 39.8, -69.8, 41.4),
        )

        self.assertEqual(response.metadata.source, "live")
        self.assertEqual(response.metadata.dataset_id, "noaacwBLENDEDsstDaily")
        self.assertEqual(response.metadata.point_count, 2)
        self.assertGreater(response.metadata.cell_count, 0)
        self.assertEqual(response.metadata.temp_range_f, [66.2, 67.1])
        self.assertEqual(response.data.type, "FeatureCollection")
        self.assertEqual(response.data.features[0].geometry.type, "Polygon")
        self.assertGreaterEqual(response.data.features[0].properties.sea_surface_temp_f, 66.2)
        self.assertLessEqual(response.data.features[0].properties.sea_surface_temp_f, 67.1)

    def test_get_sst_map_returns_unavailable_state_when_provider_has_no_points(self) -> None:
        provider = FakeSstProvider(points=SstDataUnavailableError("missing"), source_name="live")
        provider.last_failure_reason = "upstream_request_failed"
        service = SstMapService(sst_provider=provider)

        response = service.get_sst_map(
            trip_date=date(2026, 6, 18),
            bbox=(-72.4, 39.8, -69.8, 41.4),
        )

        self.assertEqual(response.metadata.source, "unavailable")
        self.assertEqual(response.metadata.dataset_id, "noaacwBLENDEDsstDaily")
        self.assertEqual(response.metadata.point_count, 0)
        self.assertEqual(response.metadata.cell_count, 0)
        self.assertEqual(response.data.features, [])


if __name__ == "__main__":
    unittest.main()
