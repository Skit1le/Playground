from __future__ import annotations

from app.db_models import TripOutcomeModel
from app.repositories import TripOutcomeRepository
from app.schemas import TripOutcomeCreate, TripOutcomeRecord, TripOutcomeUpdate


class TripOutcomeNotFoundError(ValueError):
    pass


def build_trip_outcome_record(model: TripOutcomeModel) -> TripOutcomeRecord:
    return TripOutcomeRecord(
        id=str(model.id),
        date=model.date,
        target_species=model.target_species,
        zone_id=model.zone_id,
        latitude=model.latitude,
        longitude=model.longitude,
        catch_success=model.catch_success,
        catch_count=model.catch_count,
        vessel=model.vessel,
        notes=model.notes,
    )


class TripOutcomeService:
    def __init__(self, repository: TripOutcomeRepository):
        self.repository = repository

    def list_outcomes(self) -> list[TripOutcomeRecord]:
        return [build_trip_outcome_record(model) for model in self.repository.list_all()]

    def create_outcome(self, payload: TripOutcomeCreate) -> TripOutcomeRecord:
        model = TripOutcomeModel(**payload.model_dump())
        return build_trip_outcome_record(self.repository.create(model))

    def update_outcome(self, outcome_id: int, payload: TripOutcomeUpdate) -> TripOutcomeRecord:
        model = self.repository.get(outcome_id)
        if model is None:
            raise TripOutcomeNotFoundError(f"Trip outcome '{outcome_id}' was not found.")
        for field_name, value in payload.model_dump(exclude_unset=True).items():
            setattr(model, field_name, value)
        return build_trip_outcome_record(self.repository.update(model))

    def delete_outcome(self, outcome_id: int) -> None:
        if not self.repository.delete(outcome_id):
            raise TripOutcomeNotFoundError(f"Trip outcome '{outcome_id}' was not found.")
