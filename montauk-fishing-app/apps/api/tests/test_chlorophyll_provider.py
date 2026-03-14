import unittest
from datetime import date
import socket
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError

from app.chlorophyll_provider import (
    CachedChlorophyllSnapshotAdapter,
    CachingChlorophyllProvider,
    ChlorophyllDataUnavailableError,
    ChlorophyllObservation,
    ChlorophyllPoint,
    FallbackChlorophyllProvider,
    LiveCoastwatchChlorophyllAdapter,
    MockChlorophyllAdapter,
    ProcessedCoastwatchChlorophyllAdapter,
)

TEST_TEMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TEMP_ROOT.mkdir(exist_ok=True)


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

    def close(self) -> None:
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


class FakeUrlOpenSequence:
    def __init__(self, responses: list[str | Exception]):
        self.responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, url: str, timeout: float):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("No fake responses left for urlopen")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeUrlResponse(response)


class FakeCompletedProcess:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunCommand:
    def __init__(self, responses: list[FakeCompletedProcess]):
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if not self.responses:
            raise AssertionError("No fake responses left for run_command")
        return self.responses.pop(0)


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
    def test_builds_live_query_with_time_suffix_and_extra_selectors(self) -> None:
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            variable_name="chlor_a",
            time_suffix="T12:00:00Z",
            extra_selectors="[(0.0)]",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=FakeUrlOpen("time,latitude,longitude,chlor_a\n"),
        )

        url = adapter._build_csv_url("nesdisVHNchlaDaily", "2026-03-11T12:00:00Z", (40.62, 41.18, -72.28, -71.02))

        self.assertIn("chlor_a[(2026-03-11T12:00:00Z)][(0.0)][(41.18):1:(40.62)][(-72.28):1:(-71.02)]", url)

    def test_get_zone_chlorophyll_uses_live_csv_payload(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,chlor_a",
                    "2026-06-18T12:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T12:00:00Z,40.92,-71.82,0.31",
                    "2026-06-18T12:00:00Z,40.98,-71.95,0.21",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
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
                    "time,latitude,longitude,chlor_a",
                    "2026-06-18T12:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T12:00:00Z,40.92,-71.82,0.31",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
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
                    "time,latitude,longitude,chlor_a",
                    "2026-06-18T12:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T12:00:00Z,40.20,-70.10,0.18",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
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
                    "time,latitude,longitude,chlor_a",
                    "2026-06-18T12:00:00Z,40.95,-71.88,0.26",
                    "2026-06-18T12:00:00Z,40.92,-71.82,0.31",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
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
        self.assertEqual(adapter.last_dataset_id, "nesdisVHNchlaDaily")

    def test_retries_latest_available_timestamp_when_requested_date_is_ahead_of_feed(self) -> None:
        first_error = HTTPError(
            url="https://example.com/first.csv",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=FakeUrlResponse(
                'Error { message="Query error: axis maximum=2026-03-09T12:00:00Z."; }'
            ),
        )
        url_open = FakeUrlOpenSequence(
            [
                first_error,
                "\n".join(
                    [
                        "time,latitude,longitude,chlor_a",
                        "2026-03-09T12:00:00Z,40.95,-71.88,0.26",
                        "2026-03-09T12:00:00Z,40.92,-71.82,0.31",
                    ]
                ),
            ]
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            variable_name="chlor_a",
            time_suffix="T12:00:00Z",
            extra_selectors="[(0.0)]",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        points = adapter.get_chlorophyll_points(date(2026, 3, 11))

        self.assertEqual(len(points), 2)
        self.assertEqual(adapter.last_resolved_timestamp, "2026-03-09T12:00:00Z")
        self.assertEqual(adapter.last_failure_reason, "")
        self.assertEqual(len(url_open.calls), 2)

    def test_falls_back_to_curl_when_socket_access_is_blocked(self) -> None:
        url_open = FakeUrlOpen(URLError("[WinError 10013] socket blocked"))
        run_command = FakeRunCommand(
            [
                FakeCompletedProcess(
                    returncode=0,
                    stdout="\n".join(
                        [
                            "time,latitude,longitude,chlor_a",
                            "2026-03-09T12:00:00Z,40.95,-71.88,0.26",
                            "2026-03-09T12:00:00Z,40.92,-71.82,0.31",
                            "__HTTP_STATUS__:200",
                        ]
                    ),
                )
            ]
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
            run_command=run_command,
        )

        points = adapter.get_chlorophyll_points(date(2026, 3, 11))

        self.assertEqual(len(points), 2)
        self.assertEqual(adapter.last_failure_reason, "")
        self.assertEqual(len(run_command.calls), 1)

    def test_retries_on_initial_timeout_then_succeeds_via_curl(self) -> None:
        url_open = FakeUrlOpen(TimeoutError("timed out"))
        run_command = FakeRunCommand(
            [
                FakeCompletedProcess(
                    returncode=0,
                    stdout="\n".join(
                        [
                            "time,latitude,longitude,chlor_a",
                            "2026-03-11T12:00:00Z,40.95,-71.88,0.26",
                            "2026-03-11T12:00:00Z,40.92,-71.82,0.31",
                            "__HTTP_STATUS__:200",
                        ]
                    ),
                )
            ]
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
            run_command=run_command,
        )

        points = adapter.get_chlorophyll_points(date(2026, 3, 11))

        self.assertEqual(len(points), 2)
        self.assertEqual(adapter.last_failure_reason, "")
        self.assertEqual(adapter.last_dataset_id, "nesdisVHNchlaDaily")

    def test_classifies_dns_failure_precisely(self) -> None:
        url_open = FakeUrlOpen(URLError(socket.gaierror("host lookup failed")))
        run_command = FakeRunCommand(
            [
                FakeCompletedProcess(
                    returncode=6,
                    stderr="curl: (6) Could not resolve host: coastwatch.pfeg.noaa.gov",
                ),
                FakeCompletedProcess(
                    returncode=6,
                    stderr="curl: (6) Could not resolve host: coastwatch.pfeg.noaa.gov",
                ),
            ]
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
            run_command=run_command,
        )

        with self.assertRaises(ChlorophyllDataUnavailableError):
            adapter.get_chlorophyll_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "dns_error")

    def test_classifies_network_block_precisely(self) -> None:
        url_open = FakeUrlOpen(URLError("[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions"))
        run_command = FakeRunCommand(
            [
                FakeCompletedProcess(
                    returncode=7,
                    stderr="curl: (7) Failed to connect to coastwatch.pfeg.noaa.gov port 443 after 120 ms: Could not connect to server",
                ),
                FakeCompletedProcess(
                    returncode=7,
                    stderr="curl: (7) Failed to connect to coastwatch.pfeg.noaa.gov port 443 after 120 ms: Could not connect to server",
                ),
            ]
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
            run_command=run_command,
        )

        with self.assertRaises(ChlorophyllDataUnavailableError):
            adapter.get_chlorophyll_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "network_blocked")

    def test_classifies_invalid_dataset_after_alias_attempts(self) -> None:
        url_open = FakeUrlOpenSequence(
            [
                HTTPError(url="https://example.com/a.csv", code=404, msg="Not Found", hdrs=None, fp=FakeUrlResponse("dataset missing")),
                HTTPError(url="https://example.com/b.csv", code=404, msg="Not Found", hdrs=None, fp=FakeUrlResponse("dataset missing")),
                HTTPError(url="https://example.com/c.csv", code=404, msg="Not Found", hdrs=None, fp=FakeUrlResponse("dataset missing")),
            ]
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
            alternate_dataset_ids=("anotherBadDataset",),
        )

        with self.assertRaises(ChlorophyllDataUnavailableError):
            adapter.get_chlorophyll_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "invalid_dataset")
        self.assertGreaterEqual(len(adapter.last_attempted_urls), 3)

    def test_skips_nan_values_in_live_csv_payload(self) -> None:
        url_open = FakeUrlOpen(
            "\n".join(
                [
                    "time,latitude,longitude,chlor_a",
                    "2026-06-18T12:00:00Z,40.95,-71.88,NaN",
                    "2026-06-18T12:00:00Z,40.92,-71.82,0.31",
                ]
            )
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="nesdisVHNchlaDaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
        )

        points = adapter.get_chlorophyll_points(date(2026, 6, 18))

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].chlorophyll_mg_m3, 0.31)


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
        url_open = FakeUrlOpen(URLError("generic socket failure"))
        run_command = FakeRunCommand(
            [
                FakeCompletedProcess(
                    returncode=7,
                    stderr="curl: (7) A generic connect failure occurred",
                )
            ]
        )
        adapter = LiveCoastwatchChlorophyllAdapter(
            dataset_id="noaacwCHLdaily",
            base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
            min_lat=39.8,
            max_lat=41.4,
            min_lon=-72.4,
            max_lon=-69.8,
            open_url=url_open,
            run_command=run_command,
        )

        with self.assertRaises(ChlorophyllDataUnavailableError):
            adapter.get_chlorophyll_points(date(2026, 6, 18))

        self.assertEqual(adapter.last_failure_reason, "connection_error")


class CachedChlorophyllSnapshotAdapterTestCase(unittest.TestCase):
    def test_reads_exact_cached_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
            )
            points = (
                ChlorophyllPoint(latitude=40.95, longitude=-71.88, chlorophyll_mg_m3=0.26),
                ChlorophyllPoint(latitude=40.92, longitude=-71.82, chlorophyll_mg_m3=0.31),
            )
            adapter.store_snapshot(
                requested_date="2026-06-18",
                bbox=(39.8, 41.4, -72.4, -69.8),
                points=points,
                dataset_id="live-dataset",
                resolved_timestamp="2026-06-18T12:00:00Z",
                upstream_host="coastwatch.pfeg.noaa.gov",
                attempted_urls=["https://coastwatch.pfeg.noaa.gov/example.csv"],
                provider_diagnostics={"attempt_number": 1},
                seed_source="live",
            )

            cached_points = adapter.get_chlorophyll_points(date(2026, 6, 18))

            self.assertEqual(cached_points, points)
            self.assertEqual(adapter.last_dataset_id, "live-dataset")
            self.assertEqual(adapter.last_provider_diagnostics["cache_kind"], "last_known_good")

    def test_falls_back_to_latest_cached_snapshot_for_newer_date(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
            )
            points = (ChlorophyllPoint(latitude=40.95, longitude=-71.88, chlorophyll_mg_m3=0.26),)
            adapter.store_snapshot(
                requested_date="2026-06-18",
                bbox=(39.8, 41.4, -72.4, -69.8),
                points=points,
                dataset_id="live-dataset",
                resolved_timestamp="2026-06-18T12:00:00Z",
                upstream_host="coastwatch.pfeg.noaa.gov",
                attempted_urls=[],
                provider_diagnostics={},
                seed_source="live",
            )

            cached_points = adapter.get_chlorophyll_points(date(2026, 6, 19))

            self.assertEqual(cached_points, points)
            self.assertEqual(adapter.last_dataset_id, "live-dataset")
            self.assertEqual(adapter.last_provider_diagnostics["cache_kind"], "last_known_good")

    def test_seeds_cache_from_processed_provider_when_empty(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            seed_provider = ProcessedCoastwatchChlorophyllAdapter(
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
                load_product=FakeProcessedProductLoader(make_payload()),
            )
            adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
                seed_provider=seed_provider,
            )

            cached_points = adapter.get_chlorophyll_points(date(2026, 6, 18))

            self.assertGreaterEqual(len(cached_points), 1)
            self.assertEqual(adapter.last_provider_diagnostics["cache_kind"], "seeded_from_processed")
            self.assertTrue(any(Path(temp_dir).rglob("*.json")))


class CachingChlorophyllProviderTestCase(unittest.TestCase):
    def test_stores_last_known_good_snapshot_after_live_success(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            url_open = FakeUrlOpen(
                "\n".join(
                    [
                        "time,latitude,longitude,chlor_a",
                        "2026-06-18T12:00:00Z,40.95,-71.88,0.26",
                        "2026-06-18T12:00:00Z,40.92,-71.82,0.31",
                    ]
                )
            )
            live_provider = LiveCoastwatchChlorophyllAdapter(
                dataset_id="nesdisVHNchlaDaily",
                base_url="https://coastwatch.pfeg.noaa.gov/erddap/griddap",
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
                open_url=url_open,
            )
            cache_adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
            )
            provider = CachingChlorophyllProvider(primary=live_provider, cache_adapter=cache_adapter)

            points = provider.get_chlorophyll_points(date(2026, 6, 18))

            self.assertEqual(len(points), 2)
            cached_points = cache_adapter.get_chlorophyll_points(date(2026, 6, 18))
            self.assertEqual(cached_points, points)

    def test_provider_chain_prefers_cached_real_before_mock(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            cache_adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
            )
            cache_adapter.store_snapshot(
                requested_date="2026-06-18",
                bbox=(39.8, 41.4, -72.4, -69.8),
                points=(ChlorophyllPoint(latitude=40.95, longitude=-71.88, chlorophyll_mg_m3=0.26),),
                dataset_id="cached-dataset",
                resolved_timestamp="2026-06-18T12:00:00Z",
                upstream_host="coastwatch.pfeg.noaa.gov",
                attempted_urls=["https://coastwatch.pfeg.noaa.gov/example.csv"],
                provider_diagnostics={},
                seed_source="live",
            )
            provider = FallbackChlorophyllProvider(
                primary=FakeChlorophyllProvider(
                    observation=ChlorophyllDataUnavailableError("network_blocked"),
                    points=ChlorophyllDataUnavailableError("network_blocked"),
                    source_name="live",
                ),
                fallback=FallbackChlorophyllProvider(
                    primary=cache_adapter,
                    fallback=MockChlorophyllAdapter(),
                ),
            )

            points = provider.get_chlorophyll_points(date(2026, 6, 18))

            self.assertEqual(len(points), 1)
            self.assertEqual(provider.last_source_name, "cached_real")
            self.assertEqual(provider.last_failure_reason, "network_blocked")


if __name__ == "__main__":
    unittest.main()
