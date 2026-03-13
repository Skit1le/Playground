import ssl
import unittest
from datetime import date
from urllib.error import HTTPError, URLError

from app.sst_provider import (
    FallbackSstProvider,
    LiveCoastwatchSstAdapter,
    MockSstAdapter,
    ProcessedCoastwatchSstAdapter,
    SstDataUnavailableError,
    SstObservation,
    SstPoint,
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


class LiveCoastwatchSstAdapterTestCase(unittest.TestCase):
    def test_build_csv_url_uses_expected_erddap_query(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="ncdcOisst21NrtAgg",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            variable_name="sst",
            time_suffix="T12:00:00Z",
            extra_selectors="[(0.0)]",
            longitude_mode="0_360",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(""),
        )

        url = adapter._build_csv_url("2026-06-18", (39.8, 41.4, -72.4, -69.8))

        self.assertEqual(
            url,
            "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21NrtAgg.csv?"
            "sst[(2026-06-18T12:00:00Z)][(0.0)][(41.4):1:(39.8)][(287.6):1:(290.2)]",
        )

    def test_get_zone_sst_uses_live_csv_payload(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,sea_surface_temperature",
                    "2026-06-18T00:00:00Z,40.95,-71.88,19.0",
                    "2026-06-18T00:00:00Z,40.92,-71.82,18.0",
                    "2026-06-18T00:00:00Z,40.98,-71.95,20.5",
                ]
            )
        )
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        observation = adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(observation.sea_surface_temp_f, 66.2)
        self.assertGreater(observation.temp_gradient_f_per_nm, 0)

    def test_get_zone_sst_caches_one_live_fetch_per_date(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,sea_surface_temperature",
                    "2026-06-18T00:00:00Z,40.95,-71.88,19.0",
                    "2026-06-18T00:00:00Z,40.92,-71.82,18.0",
                ]
            )
        )
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        first = adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        second = adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(first, second)
        self.assertEqual(len(url_open.calls), 1)

    def test_get_sst_points_caches_one_live_fetch_per_date_and_bbox(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,sea_surface_temperature",
                    "2026-06-18T00:00:00Z,40.95,-71.88,19.0",
                    "2026-06-18T00:00:00Z,40.92,-71.82,18.0",
                ]
            )
        )
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        first = adapter.get_sst_points(
            date(2026, 6, 18),
            min_lat=40.8,
            max_lat=41.1,
            min_lon=-72.0,
            max_lon=-71.5,
        )
        second = adapter.get_sst_points(
            date(2026, 6, 18),
            min_lat=40.8,
            max_lat=41.1,
            min_lon=-72.0,
            max_lon=-71.5,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(url_open.calls), 1)

    def test_get_sst_points_returns_filtered_live_grid_points(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,sea_surface_temperature",
                    "2026-06-18T00:00:00Z,40.95,-71.88,19.0",
                    "2026-06-18T00:00:00Z,40.20,-70.10,18.0",
                ]
            )
        )
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        points = adapter.get_sst_points(
            date(2026, 6, 18),
            min_lat=40.8,
            max_lat=41.1,
            min_lon=-72.0,
            max_lon=-71.5,
        )

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].sea_surface_temp_f, 66.2)

    def test_zone_lookup_and_map_lookup_share_same_live_dataset_cache_for_default_bbox(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,sea_surface_temperature",
                    "2026-06-18T00:00:00Z,40.95,-71.88,19.0",
                    "2026-06-18T00:00:00Z,40.92,-71.82,18.0",
                ]
            )
        )
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        adapter.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))
        points = adapter.get_sst_points(
            date(2026, 6, 18),
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
        )

        self.assertEqual(len(points), 2)
        self.assertEqual(len(url_open.calls), 1)
        self.assertEqual(adapter.last_dataset_id, "noaacwBLENDEDsstDaily")

    def test_live_probe_reports_invalid_url(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="://bad-url",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(""),
        )

        result = adapter.probe_upstream_request(date(2026, 6, 18))

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_reason"], "invalid_url")
        self.assertEqual(result["exception_class"], "ValueError")

    def test_get_sst_points_classifies_ssl_error(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(ssl.SSLError("certificate verify failed")),
        )

        with self.assertRaises(SstDataUnavailableError):
            adapter.get_sst_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "ssl_error")

    def test_get_sst_points_classifies_connection_error(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(URLError("connection refused")),
        )

        with self.assertRaises(SstDataUnavailableError):
            adapter.get_sst_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "connection_error")

    def test_get_sst_points_classifies_proxy_error(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(URLError("proxy tunnel failed")),
        )

        with self.assertRaises(SstDataUnavailableError):
            adapter.get_sst_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "proxy_error")

    def test_get_sst_points_classifies_timeout(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(TimeoutError("timed out")),
        )

        with self.assertRaises(SstDataUnavailableError):
            adapter.get_sst_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "timeout")
        self.assertEqual(adapter.last_exception_class, "TimeoutError")

    def test_probe_returns_http_status_code_when_upstream_rejects_request(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(HTTPError("https://example.com", 404, "not found", None, None)),
        )

        result = adapter.probe_upstream_request(date(2026, 6, 18))

        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_reason"], "upstream_http_404")
        self.assertEqual(result["status_code"], 404)

    def test_get_sst_points_classifies_missing_csv_headers_as_bad_response_shape(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(""),
        )

        with self.assertRaises(SstDataUnavailableError):
            adapter.get_sst_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "bad_response_shape")

    def test_get_sst_points_normalizes_0_360_longitudes_back_to_signed_output(self) -> None:
        adapter = LiveCoastwatchSstAdapter(
            dataset_id="ncdcOisst21NrtAgg",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            variable_name="sst",
            time_suffix="T12:00:00Z",
            extra_selectors="[(0.0)]",
            longitude_mode="0_360",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(
                "\n".join(
                    [
                        "time,zlev,latitude,longitude,sst",
                        "2026-06-18T12:00:00Z,0.0,40.95,288.12,19.0",
                    ]
                )
            ),
        )

        points = adapter.get_sst_points(date(2026, 6, 18))

        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0].longitude, -71.88, places=2)


class FakeSstProvider:
    def __init__(
        self,
        *,
        observation: SstObservation | Exception,
        points: tuple[SstPoint, ...] | Exception,
        source_name: str,
    ):
        self.observation = observation
        self.points = points
        self.source_name = source_name

    def get_zone_sst(self, zone_id: str, latitude: float, longitude: float, trip_date: date) -> SstObservation:
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation

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


class FallbackSstProviderTestCase(unittest.TestCase):
    def test_get_sst_points_falls_back_from_live_to_processed(self) -> None:
        provider = FallbackSstProvider(
            primary=FakeSstProvider(
                observation=SstDataUnavailableError("live missing"),
                points=SstDataUnavailableError("live missing"),
                source_name="live",
            ),
            fallback=FakeSstProvider(
                observation=SstObservation(sea_surface_temp_f=66.4, temp_gradient_f_per_nm=1.2),
                points=(SstPoint(latitude=40.95, longitude=-71.88, sea_surface_temp_f=66.4),),
                source_name="processed",
            ),
        )

        points = provider.get_sst_points(date(2026, 6, 18))

        self.assertEqual(len(points), 1)
        self.assertEqual(provider.last_source_name, "processed")

    def test_get_sst_points_falls_back_from_processed_to_mock(self) -> None:
        provider = FallbackSstProvider(
            primary=FakeSstProvider(
                observation=SstDataUnavailableError("processed missing"),
                points=SstDataUnavailableError("processed missing"),
                source_name="processed",
            ),
            fallback=MockSstAdapter(),
        )

        points = provider.get_sst_points(date(2026, 6, 18))

        self.assertGreaterEqual(len(points), 1)
        self.assertEqual(provider.last_source_name, "mock_fallback")

    def test_get_zone_sst_falls_back_from_live_to_processed(self) -> None:
        provider = FallbackSstProvider(
            primary=FakeSstProvider(
                observation=SstDataUnavailableError("live missing"),
                points=SstDataUnavailableError("live missing"),
                source_name="live",
            ),
            fallback=FakeSstProvider(
                observation=SstObservation(sea_surface_temp_f=66.4, temp_gradient_f_per_nm=1.2),
                points=(SstPoint(latitude=40.95, longitude=-71.88, sea_surface_temp_f=66.4),),
                source_name="processed",
            ),
        )

        observation = provider.get_zone_sst("prime-edge", 40.95, -71.88, date(2026, 6, 18))

        self.assertEqual(observation.sea_surface_temp_f, 66.4)
        self.assertEqual(provider.last_source_name, "processed")

    def test_get_sst_points_preserves_live_ssl_failure_reason_when_falling_back(self) -> None:
        live_adapter = LiveCoastwatchSstAdapter(
            dataset_id="noaacwBLENDEDsstDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen(ssl.SSLError("certificate verify failed")),
        )
        provider = FallbackSstProvider(
            primary=live_adapter,
            fallback=MockSstAdapter(),
        )

        points = provider.get_sst_points(date(2026, 6, 18))

        self.assertGreaterEqual(len(points), 1)
        self.assertEqual(provider.last_source_name, "mock_fallback")
        self.assertEqual(provider.last_failure_reason, "ssl_error")


if __name__ == "__main__":
    unittest.main()
