import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.routes.admin import (
    capture_zone_score_snapshots,
    get_backtest_report,
    inspect_chlorophyll_cache,
    warm_chlorophyll_cache,
)
from app.schemas import (
    ChlorophyllCacheInspectionResponse,
    ChlorophyllCacheWarmResponse,
    ChlorophyllCacheWarmResult,
    OutcomeBacktestReport,
    OutcomeCalibrationGap,
    TripOutcomeRecord,
    ZoneSnapshotCaptureResponse,
    HistoricalZoneScoreSnapshotRecord,
    ScoreBreakdown,
    WeightedScoreBreakdown,
    WeightedScoreConfig,
)


def make_breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(
        temp_suitability=90.0,
        temp_gradient=66.0,
        temp_break_proximity=88.0,
        edge_alignment=74.0,
        structure_proximity=62.0,
        chlorophyll_suitability=80.0,
        chlorophyll_break_proximity=71.0,
        current_suitability=82.0,
        weather_fishability=78.0,
    )


def make_weights() -> WeightedScoreConfig:
    return WeightedScoreConfig(
        temp_suitability=0.2,
        temp_gradient=0.14,
        temp_break_proximity=0.06,
        edge_alignment=0.03,
        structure_proximity=0.16,
        chlorophyll_suitability=0.1,
        chlorophyll_break_proximity=0.04,
        current_suitability=0.11,
        weather_fishability=0.16,
    )


def make_weighted_breakdown() -> WeightedScoreBreakdown:
    return WeightedScoreBreakdown(
        temp_suitability=18.0,
        temp_gradient=9.2,
        temp_break_proximity=5.3,
        edge_alignment=2.2,
        structure_proximity=9.9,
        chlorophyll_suitability=8.0,
        chlorophyll_break_proximity=2.8,
        current_suitability=9.0,
        weather_fishability=12.5,
    )


class FakeHistoricalSnapshotService:
    def capture_snapshots(self, *, trip_date: date, species: str, limit: int) -> ZoneSnapshotCaptureResponse:
        return ZoneSnapshotCaptureResponse(
            trip_date=trip_date,
            species=species,
            captured_count=1,
            snapshots=[
                HistoricalZoneScoreSnapshotRecord(
                    id=1,
                    date=trip_date,
                    species=species,
                    zone_id="hudson-edge-east",
                    zone_name="Hudson Edge East",
                    score=86.9,
                    score_breakdown=make_breakdown(),
                    score_weights=make_weights(),
                    weighted_score_breakdown=make_weighted_breakdown(),
                    environmental_snapshot={"sea_surface_temp_f": 68.8},
                    recorded_at=datetime.now(timezone.utc),
                )
            ],
        )

    def build_backtest_report(self, *, outcomes, species, date_from, date_to) -> OutcomeBacktestReport:
        return OutcomeBacktestReport(
            outcome_count=len(outcomes),
            compared_count=1,
            mean_absolute_error=0.08,
            largest_gaps=[
                OutcomeCalibrationGap(
                    zone_id="hudson-edge-east",
                    species=species or "yellowfin",
                    predicted_score=0.86,
                    actual_success=0.78,
                    score_error=0.08,
                )
            ],
        )


class FakeTripOutcomeService:
    def list_outcomes(self) -> list[TripOutcomeRecord]:
        return [
            TripOutcomeRecord(
                id="1",
                date=date(2025, 9, 14),
                target_species="yellowfin",
                zone_id="hudson-edge-east",
                catch_success=0.78,
                catch_count=4,
                vessel="North Star",
                notes="Good edge bite.",
            )
        ]


class FakeChlorophyllCacheService:
    def warm_cache(self, request) -> ChlorophyllCacheWarmResponse:
        return ChlorophyllCacheWarmResponse(
            requested_dates=list(request.requested_dates),
            bboxes=[list(bbox) for bbox in request.bboxes],
            mode=request.mode,
            warmed_count=1,
            failed_count=0,
            results=[
                ChlorophyllCacheWarmResult(
                    requested_date=request.requested_dates[0],
                    bbox=list(request.bboxes[0]),
                    success=True,
                    source="live",
                    dataset_id="live-dataset",
                    cache_key="cache-key",
                    cache_path="D:/cache/example.json",
                    resolved_timestamp="2025-09-14T12:00:00Z",
                    point_count=24,
                )
            ],
        )

    def inspect_cache(self) -> ChlorophyllCacheInspectionResponse:
        return ChlorophyllCacheInspectionResponse(
            cache_dir="D:/cache",
            entry_count=1,
            entries=[],
        )


class AdminRouteTestCase(unittest.TestCase):
    def test_capture_zone_score_snapshots_delegates_to_service(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status="ok")))
        response = capture_zone_score_snapshots(
            request=request,
            historical_snapshot_service=FakeHistoricalSnapshotService(),
            date_value="2025-09-14",
            species="yellowfin",
            limit=12,
        )

        self.assertEqual(response.captured_count, 1)
        self.assertEqual(response.species, "yellowfin")

    def test_admin_routes_require_database(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status="unavailable")))
        with self.assertRaises(HTTPException) as context:
            capture_zone_score_snapshots(
                request=request,
                historical_snapshot_service=FakeHistoricalSnapshotService(),
                date_value="2025-09-14",
                species="yellowfin",
                limit=12,
            )

        self.assertEqual(context.exception.status_code, 503)

    def test_get_backtest_report_filters_and_returns_report(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status="ok")))
        response = get_backtest_report(
            request=request,
            historical_snapshot_service=FakeHistoricalSnapshotService(),
            trip_outcome_service=FakeTripOutcomeService(),
            species="yellowfin",
            date_from="2025-09-01",
            date_to="2025-09-30",
        )

        self.assertEqual(response.outcome_count, 1)
        self.assertEqual(response.compared_count, 1)

    def test_warm_chlorophyll_cache_delegates_to_service(self) -> None:
        response = warm_chlorophyll_cache(
            chlorophyll_cache_service=FakeChlorophyllCacheService(),
            date_value="2025-09-14",
            date_from=None,
            date_to=None,
            bbox=["-72.4,39.8,-69.8,41.4"],
            mode="live",
        )

        self.assertEqual(response.warmed_count, 1)
        self.assertEqual(response.mode, "live")

    def test_inspect_chlorophyll_cache_returns_entries(self) -> None:
        response = inspect_chlorophyll_cache(
            chlorophyll_cache_service=FakeChlorophyllCacheService(),
        )

        self.assertEqual(response.cache_dir, "D:/cache")
        self.assertEqual(response.entry_count, 1)


if __name__ == "__main__":
    unittest.main()
