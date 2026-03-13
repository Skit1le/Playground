import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.routes.admin import capture_zone_score_snapshots, get_backtest_report
from app.schemas import (
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


if __name__ == "__main__":
    unittest.main()
