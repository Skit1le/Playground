from __future__ import annotations

from dataclasses import dataclass

from app.schemas import HistoricalZoneScoreSnapshot, OutcomeBacktestReport, OutcomeCalibrationGap, TripOutcomeRecord


@dataclass(frozen=True)
class TripOutcomeLinkCandidate:
    outcome: TripOutcomeRecord
    snapshot: HistoricalZoneScoreSnapshot


class OutcomeEvaluationService:
    def build_backtest_report(
        self,
        *,
        outcomes: list[TripOutcomeRecord],
        snapshots: list[HistoricalZoneScoreSnapshot],
    ) -> OutcomeBacktestReport:
        snapshot_index = {(snapshot.date, snapshot.species, snapshot.zone_id): snapshot for snapshot in snapshots}
        comparisons: list[OutcomeCalibrationGap] = []
        for outcome in outcomes:
            if outcome.zone_id is None:
                continue
            snapshot = snapshot_index.get((outcome.date, outcome.target_species, outcome.zone_id))
            if snapshot is None:
                continue
            predicted_score = round(snapshot.score / 100, 4)
            comparisons.append(
                OutcomeCalibrationGap(
                    zone_id=snapshot.zone_id,
                    species=snapshot.species,
                    predicted_score=predicted_score,
                    actual_success=outcome.catch_success,
                    score_error=round(predicted_score - outcome.catch_success, 4),
                )
            )

        if not comparisons:
            return OutcomeBacktestReport(
                outcome_count=len(outcomes),
                compared_count=0,
                mean_absolute_error=None,
                largest_gaps=[],
            )

        mean_absolute_error = round(
            sum(abs(gap.score_error) for gap in comparisons) / len(comparisons),
            4,
        )
        largest_gaps = sorted(comparisons, key=lambda gap: abs(gap.score_error), reverse=True)[:5]
        return OutcomeBacktestReport(
            outcome_count=len(outcomes),
            compared_count=len(comparisons),
            mean_absolute_error=mean_absolute_error,
            largest_gaps=largest_gaps,
        )
