import unittest
from datetime import date
from urllib.error import URLError

from app.chlorophyll_provider import (
    ChlorophyllDataUnavailableError,
    ChlorophyllObservation,
    ChlorophyllPoint,
    FallbackChlorophyllProvider,
    LiveCoastwatchChlorophyllAdapter,
    MockChlorophyllAdapter,
    ProcessedCoastwatchChlorophyllAdapter,
)


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


class FakeUrlResponse:
    def __init__(self, text: str):
        self.text = text

    def read(self) -> bytes:
        return self.text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeUrlOpen:
    def __init__(self, text: str | Exception):
        self.text = text
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float):
        self.calls.append(url)
        if isinstance(self.text, Exception):
            raise self.text
        return FakeUrlResponse(self.text)


def make_payload() -> dict:
    return {
        "grid": [
            {"latitude": 40.95, "longitude": -71.88, "value": 0.26},
            {"latitude": 40.92, "longitude": -71.82, "value": 0.31},
            {"latitude": 40.98, "longitude": -71.95, "value": 0.21},
            {"latitude": 41.02, "longitude": -71.7, "value": 0.18},
        ]
    }


class ProcessedCoastwatchChlorophyllAdapterTestCase(unittest.TestCase):
    def test_get_zone_chlorophyll_uses_processed_payload(self) -> None:
        loader = FakeProcessedProductLoader(make_payload())
        adapter = ProcessedCoastwatchChlorophyllAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        observation = adapter.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(observation.chlorophyll_mg_m3, 0.26)

    def test_get_zone_chlorophyll_caches_repeated_zone_date_requests(self) -> None:
        loader = FakeProcessedProductLoader(make_payload())
        adapter = ProcessedCoastwatchChlorophyllAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        first = adapter.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        second = adapter.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(first, second)
        self.assertEqual(loader.calls, ["2026-06-18"])

    def test_get_zone_chlorophyll_raises_when_processed_payload_is_missing(self) -> None:
        loader = FakeProcessedProductLoader(FileNotFoundError("missing"))
        adapter = ProcessedCoastwatchChlorophyllAdapter(
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            load_product=loader,
        )

        with self.assertRaises(ChlorophyllDataUnavailableError):
            adapter.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        with self.assertRaises(ChlorophyllDataUnavailableError):
            adapter.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(loader.calls, ["2026-06-18"])


class LiveCoastwatchChlorophyllAdapterTestCase(unittest.TestCase):
    def test_get_zone_chlorophyll_uses_live_csv_payload(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,chlorophyll",
                    "2026-06-18T00:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T00:00:00Z,40.92,-71.82,0.31",
                    "2026-06-18T00:00:00Z,40.98,-71.95,0.21",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="noaacwCHLdaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        observation = adapter.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(observation.chlorophyll_mg_m3, 0.26)

    def test_get_chlorophyll_points_caches_one_live_fetch_per_date_and_bbox(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,chlorophyll",
                    "2026-06-18T00:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T00:00:00Z,40.92,-71.82,0.31",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="noaacwCHLdaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        first = adapter.get_chlorophyll_points(
            date(2026, 6, 18),
            min_lat=40.8,
            max_lat=41.1,
            min_lon=-72.0,
            max_lon=-71.5,
        )
        second = adapter.get_chlorophyll_points(
            date(2026, 6, 18),
            min_lat=40.8,
            max_lat=41.1,
            min_lon=-72.0,
            max_lon=-71.5,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(url_open.calls), 1)

    def test_get_chlorophyll_points_returns_filtered_live_grid_points(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,chlorophyll",
                    "2026-06-18T00:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T00:00:00Z,40.20,-70.10,0.18",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="noaacwCHLdaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        points = adapter.get_chlorophyll_points(
            date(2026, 6, 18),
            min_lat=40.8,
            max_lat=41.1,
            min_lon=-72.0,
            max_lon=-71.5,
        )

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].chlorophyll_mg_m3, 0.26)

    def test_zone_lookup_and_point_lookup_share_same_live_dataset_cache_for_default_bbox(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,chlorophyll",
                    "2026-06-18T00:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T00:00:00Z,40.92,-71.82,0.31",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="noaacwCHLdaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        adapter.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        points = adapter.get_chlorophyll_points(
            date(2026, 6, 18),
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
        )

        self.assertEqual(len(points), 2)
        self.assertEqual(len(url_open.calls), 1)
        self.assertEqual(adapter.last_dataset_id, "noaacwCHLdaily")


class FakeChlorophyllProvider:
    def __init__(
        self,
        *,
        observation: ChlorophyllObservation | Exception,
        points: tuple[ChlorophyllPoint, ...] | Exception,
        source_name: str,
    ):
        self.observation = observation
        self.points = points
        self.source_name = source_name

    def get_zone_chlorophyll(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> ChlorophyllObservation:
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation

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


class FallbackChlorophyllProviderTestCase(unittest.TestCase):
    def test_get_zone_chlorophyll_falls_back_from_live_to_processed(self) -> None:
        provider = FallbackChlorophyllProvider(
            primary=FakeChlorophyllProvider(
                observation=ChlorophyllDataUnavailableError("live missing"),
                points=ChlorophyllDataUnavailableError("live missing"),
                source_name="live",
            ),
            fallback=FakeChlorophyllProvider(
                observation=ChlorophyllObservation(chlorophyll_mg_m3=0.26),
                points=(ChlorophyllPoint(latitude=40.95, longitude=-71.88, chlorophyll_mg_m3=0.26),),
                source_name="processed",
            ),
        )

        observation = provider.get_zone_chlorophyll("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(observation.chlorophyll_mg_m3, 0.26)
        self.assertEqual(provider.last_source_name, "processed")

    def test_get_chlorophyll_points_falls_back_from_processed_to_mock(self) -> None:
        provider = FallbackChlorophyllProvider(
            primary=FakeChlorophyllProvider(
                observation=ChlorophyllDataUnavailableError("processed missing"),
                points=ChlorophyllDataUnavailableError("processed missing"),
                source_name="processed",
            ),
            fallback=MockChlorophyllAdapter(),
        )

        points = provider.get_chlorophyll_points(date(2026, 6, 18))

        self.assertGreaterEqual(len(points), 1)
        self.assertEqual(provider.last_source_name, "mock_fallback")

    def test_get_chlorophyll_points_preserves_primary_failure_reason_when_falling_back(self) -> None:
        provider = FallbackChlorophyllProvider(
            primary=FakeChlorophyllProvider(
                observation=ChlorophyllDataUnavailableError("live missing"),
                points=ChlorophyllDataUnavailableError("live missing"),
                source_name="live",
            ),
            fallback=MockChlorophyllAdapter(),
        )

        provider.get_chlorophyll_points(date(2026, 6, 18))

        self.assertEqual(provider.last_source_name, "mock_fallback")
        self.assertEqual(provider.last_failure_reason, "live missing")

    def test_live_chlorophyll_adapter_classifies_connection_failure(self) -> None:
        url_open = FakeUrlOpen(URLError("socket blocked"))
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="noaacwCHLdaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        with self.assertRaises(ChlorophyllDataUnavailableError):
            adapter.get_chlorophyll_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "connection_error")


if __name__ == "__main__":
    unittest.main()
