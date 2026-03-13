import unittest
from datetime import date

from app.schemas import (
    HistoricalZoneScoreSnapshot,
    ScoreBreakdown,
    TripOutcomeRecord,
    WeightedScoreBreakdown,
)
from app.services.outcomes import OutcomeEvaluationService


def make_breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(
        temp_suitability=92.0,
        temp_gradient=74.0,
        temp_break_proximity=88.0,
        edge_alignment=63.0,
        structure_proximity=71.0,
        chlorophyll_suitability=79.0,
        chlorophyll_break_proximity=68.0,
        current_suitability=83.0,
        weather_fishability=77.0,
    )


def make_weighted_breakdown() -> WeightedScoreBreakdown:
    return WeightedScoreBreakdown(
        temp_suitability=20.0,
        temp_gradient=9.0,
        temp_break_proximity=5.4,
        edge_alignment=2.1,
        structure_proximity=10.0,
        chlorophyll_suitability=7.0,
        chlorophyll_break_proximity=3.1,
        current_suitability=8.4,
        weather_fishability=9.2,
    )


class OutcomeEvaluationServiceTestCase(unittest.TestCase):
    def test_build_backtest_report_matches_outcomes_to_snapshots(self) -> None:
        service = OutcomeEvaluationService()

        report = service.build_backtest_report(
            outcomes=[
                TripOutcomeRecord(
                    id="outcome-1",
                    date=date(2025, 9, 14),
                    target_species="yellowfin",
                    zone_id="hudson-edge-east",
                    catch_success=0.9,
                    catch_count=6,
                    vessel="North Star",
                ),
                TripOutcomeRecord(
                    id="outcome-2",
                    date=date(2025, 9, 14),
                    target_species="bluefin",
                    zone_id="no-match",
                    catch_success=0.2,
                    catch_count=0,
                    vessel="North Star",
                ),
            ],
            snapshots=[
                HistoricalZoneScoreSnapshot(
                    date=date(2025, 9, 14),
                    species="yellowfin",
                    zone_id="hudson-edge-east",
                    score=84.0,
                    score_breakdown=make_breakdown(),
                    weighted_score_breakdown=make_weighted_breakdown(),
                )
            ],
        )

        self.assertEqual(report.outcome_count, 2)
        self.assertEqual(report.compared_count, 1)
        self.assertAlmostEqual(report.mean_absolute_error or 0.0, 0.06, places=2)
        self.assertEqual(report.largest_gaps[0].zone_id, "hudson-edge-east")

    def test_build_backtest_report_returns_empty_when_no_matches_exist(self) -> None:
        service = OutcomeEvaluationService()

        report = service.build_backtest_report(
            outcomes=[
                TripOutcomeRecord(
                    id="outcome-1",
                    date=date(2025, 9, 14),
                    target_species="yellowfin",
                    zone_id="hudson-edge-east",
                    catch_success=0.9,
                    catch_count=6,
                    vessel="North Star",
                )
            ],
            snapshots=[],
        )

        self.assertEqual(report.compared_count, 0)
        self.assertIsNone(report.mean_absolute_error)
        self.assertEqual(report.largest_gaps, [])


if __name__ == "__main__":
    unittest.main()
