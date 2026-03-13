from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.db_models import HistoricalZoneScoreSnapshotModel
from app.repositories import HistoricalZoneScoreSnapshotRepository
from app.schemas import (
    HistoricalZoneScoreSnapshot,
    HistoricalZoneScoreSnapshotRecord,
    OutcomeBacktestReport,
    OutcomeCalibrationGap,
    TripOutcomeRecord,
    RankedZone,
    ZoneSnapshotCaptureResponse,
)
from app.services.zones import ZonesService


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


def build_snapshot_record(model: HistoricalZoneScoreSnapshotModel) -> HistoricalZoneScoreSnapshotRecord:
    return HistoricalZoneScoreSnapshotRecord(
        id=model.id,
        date=model.date,
        species=model.species,
        zone_id=model.zone_id,
        zone_name=model.zone_name,
        score=model.score,
        score_breakdown=model.score_breakdown,
        score_weights=model.score_weights,
        weighted_score_breakdown=model.weighted_score_breakdown,
        environmental_snapshot=model.environmental_snapshot,
        recorded_at=model.recorded_at,
    )


class HistoricalSnapshotService:
    def __init__(
        self,
        repository: HistoricalZoneScoreSnapshotRepository,
        zones_service: ZonesService,
        evaluation_service: OutcomeEvaluationService | None = None,
    ):
        self.repository = repository
        self.zones_service = zones_service
        self.evaluation_service = evaluation_service or OutcomeEvaluationService()

    def capture_snapshots(
        self,
        *,
        trip_date: date,
        species: str,
        limit: int,
    ) -> ZoneSnapshotCaptureResponse:
        ranked_zones = self.zones_service.list_ranked_zones(species=species, trip_date=trip_date, limit=limit)
        snapshot_models = [_build_snapshot_model(zone) for zone in ranked_zones]
        persisted = self.repository.replace_for_date_species(
            trip_date=trip_date,
            species=species,
            snapshots=snapshot_models,
        )
        return ZoneSnapshotCaptureResponse(
            trip_date=trip_date,
            species=species,
            captured_count=len(persisted),
            snapshots=[build_snapshot_record(model) for model in persisted],
        )

    def list_snapshot_records(
        self,
        *,
        species: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[HistoricalZoneScoreSnapshotRecord]:
        return [
            build_snapshot_record(model)
            for model in self.repository.list_all(species=species, date_from=date_from, date_to=date_to)
        ]

    def list_snapshot_inputs(
        self,
        *,
        species: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[HistoricalZoneScoreSnapshot]:
        return [
            HistoricalZoneScoreSnapshot(
                date=model.date,
                species=model.species,
                zone_id=model.zone_id,
                score=model.score,
                score_breakdown=model.score_breakdown,
                score_weights=model.score_weights,
                weighted_score_breakdown=model.weighted_score_breakdown,
            )
            for model in self.repository.list_all(species=species, date_from=date_from, date_to=date_to)
        ]

    def build_backtest_report(
        self,
        *,
        outcomes: list[TripOutcomeRecord],
        species: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> OutcomeBacktestReport:
        snapshots = self.list_snapshot_inputs(species=species, date_from=date_from, date_to=date_to)
        return self.evaluation_service.build_backtest_report(outcomes=outcomes, snapshots=snapshots)


def _build_snapshot_model(zone: RankedZone) -> HistoricalZoneScoreSnapshotModel:
    return HistoricalZoneScoreSnapshotModel(
        date=zone.scored_for_date,
        species=zone.scored_for_species,
        zone_id=zone.id,
        zone_name=zone.name,
        score=zone.score,
        score_breakdown=zone.score_breakdown.model_dump(),
        score_weights=zone.score_weights.model_dump(),
        weighted_score_breakdown=zone.weighted_score_breakdown.model_dump(),
        environmental_snapshot={
            "sea_surface_temp_f": zone.sea_surface_temp_f,
            "temp_gradient_f_per_nm": zone.temp_gradient_f_per_nm,
            "nearest_strong_break_distance_nm": zone.nearest_strong_break_distance_nm,
            "structure_distance_nm": zone.structure_distance_nm,
            "chlorophyll_mg_m3": zone.chlorophyll_mg_m3,
            "nearest_strong_chl_break_distance_nm": zone.nearest_strong_chl_break_distance_nm,
            "current_speed_kts": zone.current_speed_kts,
            "current_break_index": zone.current_break_index,
            "weather_risk_index": zone.weather_risk_index,
            "summary": zone.summary,
        },
    )
