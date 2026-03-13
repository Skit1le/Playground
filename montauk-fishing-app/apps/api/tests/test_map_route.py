import unittest
from datetime import date

from app.api.routes.map import _parse_bbox, get_sst_map
from app.schemas import SstMapFeatureCollection, SstMapMetadata, SstMapResponse


class FakeSstMapService:
    def __init__(self, response: SstMapResponse):
        self.response = response
        self.calls: list[tuple[date, tuple[float, float, float, float]]] = []

    def get_sst_map(self, *, trip_date: date, bbox: tuple[float, float, float, float]) -> SstMapResponse:
        self.calls.append((trip_date, bbox))
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
                    temp_range_f=None,
                ),
                data=SstMapFeatureCollection(features=[]),
            )
        )

        response = get_sst_map(
            sst_map_service=fake_service,
            date_value=date(2026, 6, 18),
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
                    temp_range_f=None,
                ),
                data=SstMapFeatureCollection(features=[]),
            )
        )

        response = get_sst_map(
            sst_map_service=fake_service,
            date_value=date(2026, 6, 18),
            bbox="-72.4,39.8,-69.8,41.4",
        )

        self.assertEqual(response.metadata.source, "unavailable")
        self.assertEqual(response.data.features, [])


if __name__ == "__main__":
    unittest.main()
