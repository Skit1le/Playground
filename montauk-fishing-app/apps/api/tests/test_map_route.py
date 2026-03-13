import unittest
from datetime import date

from app.api.routes.map import _parse_bbox, get_live_sst_debug, get_sst_map
from app.schemas import SstMapFeatureCollection, SstMapMetadata, SstMapResponse


class FakeSstMapService:
    def __init__(self, response: SstMapResponse):
        self.response = response
        self.calls: list[tuple[date, tuple[float, float, float, float]]] = []

    def get_sst_map(self, *, trip_date: date, bbox: tuple[float, float, float, float]) -> SstMapResponse:
        self.calls.append((trip_date, bbox))
        return self.response


class FakeLiveSstProvider:
    def __init__(self, response: dict[str, object | None]):
        self.response = response
        self.calls: list[tuple[date, float, float, float, float]] = []

    def probe_upstream_request(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> dict[str, object | None]:
        self.calls.append((trip_date, min_lat or 0.0, max_lat or 0.0, min_lon or 0.0, max_lon or 0.0))
        return self.response


class MapRouteTestCase(unittest.TestCase):
    def test_parse_bbox_accepts_expected_order(self) -> None:
        self.assertEqual(_parse_bbox("-72.4,39.8,-69.8,41.4"), (-72.4, 39.8, -69.8, 41.4))

    def test_get_sst_map_delegates_to_service(self) -> None:
        fake_service = FakeSstMapService(
            response=SstMapResponse(
                metadata=SstMapMetadata(
                    date=date(2026, 6, 18),
                    bbox=[-72.4, 39.8, -69.8, 41.4],
                    source="processed",
                    point_count=0,
                    cell_count=0,
                    temp_range_f=None,
                    break_intensity_range=None,
                ),
                data=SstMapFeatureCollection(features=[]),
            )
        )

        response = get_sst_map(
            sst_map_service=fake_service,
            date_value="2026-06-18",
            bbox="-72.4,39.8,-69.8,41.4",
        )

        self.assertEqual(response.metadata.source, "processed")
        self.assertEqual(fake_service.calls, [(date(2026, 6, 18), (-72.4, 39.8, -69.8, 41.4))])

    def test_get_sst_map_accepts_mm_dd_yyyy_dates(self) -> None:
        fake_service = FakeSstMapService(
            response=SstMapResponse(
                metadata=SstMapMetadata(
                    date=date(2026, 6, 18),
                    bbox=[-72.4, 39.8, -69.8, 41.4],
                    source="processed",
                    point_count=0,
                    cell_count=0,
                    temp_range_f=None,
                    break_intensity_range=None,
                ),
                data=SstMapFeatureCollection(features=[]),
            )
        )

        response = get_sst_map(
            sst_map_service=fake_service,
            date_value="06-18-2026",
            bbox="-72.4,39.8,-69.8,41.4",
        )

        self.assertEqual(response.metadata.source, "processed")
        self.assertEqual(fake_service.calls, [(date(2026, 6, 18), (-72.4, 39.8, -69.8, 41.4))])

    def test_get_sst_map_can_return_empty_fallback_payload(self) -> None:
        fake_service = FakeSstMapService(
            response=SstMapResponse(
                metadata=SstMapMetadata(
                    date=date(2026, 6, 18),
                    bbox=[-72.4, 39.8, -69.8, 41.4],
                    source="unavailable",
                    point_count=0,
                    cell_count=0,
                    temp_range_f=None,
                    break_intensity_range=None,
                ),
                data=SstMapFeatureCollection(features=[]),
            )
        )

        response = get_sst_map(
            sst_map_service=fake_service,
            date_value="06/18/2026",
            bbox="-72.4,39.8,-69.8,41.4",
        )

        self.assertEqual(response.metadata.source, "unavailable")
        self.assertEqual(response.data.features, [])

    def test_get_live_sst_debug_uses_same_bbox_and_date_parsing(self) -> None:
        fake_provider = FakeLiveSstProvider(
            response={
                "ok": False,
                "failure_reason": "connection_error",
                "url": "https://example.test",
                "status_code": None,
            }
        )

        response = get_live_sst_debug(
            live_sst_provider=fake_provider,
            date_value="06-18-2026",
            bbox="-72.4,39.8,-69.8,41.4",
        )

        self.assertEqual(response["failure_reason"], "connection_error")
        self.assertEqual(fake_provider.calls, [(date(2026, 6, 18), 39.8, 41.4, -72.4, -69.8)])


if __name__ == "__main__":
    unittest.main()
