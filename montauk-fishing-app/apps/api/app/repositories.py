from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db_models import (
    HistoricalZoneScoreSnapshotModel,
    SpeciesScoringConfigModel,
    TripOutcomeModel,
    ZoneModel,
)


class SpeciesConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[SpeciesScoringConfigModel]:
        statement = select(SpeciesScoringConfigModel).order_by(SpeciesScoringConfigModel.label)
        return list(self.session.scalars(statement))

    def get_by_species(self, species: str) -> SpeciesScoringConfigModel | None:
        return self.session.get(SpeciesScoringConfigModel, species)


class ZoneRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[ZoneModel]:
        statement = select(ZoneModel).order_by(ZoneModel.distance_nm.asc())
        return list(self.session.scalars(statement))

    def list_for_species(self, species: str) -> list[ZoneModel]:
        statement = (
            select(ZoneModel)
            .where(ZoneModel.species.contains([species]))
            .order_by(ZoneModel.distance_nm.asc())
        )
        return list(self.session.scalars(statement))


class TripOutcomeRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[TripOutcomeModel]:
        statement = select(TripOutcomeModel).order_by(TripOutcomeModel.date.desc(), TripOutcomeModel.id.desc())
        return list(self.session.scalars(statement))

    def get(self, outcome_id: int) -> TripOutcomeModel | None:
        return self.session.get(TripOutcomeModel, outcome_id)

    def create(self, outcome: TripOutcomeModel) -> TripOutcomeModel:
        self.session.add(outcome)
        self.session.commit()
        self.session.refresh(outcome)
        return outcome

    def update(self, outcome: TripOutcomeModel) -> TripOutcomeModel:
        self.session.add(outcome)
        self.session.commit()
        self.session.refresh(outcome)
        return outcome

    def delete(self, outcome_id: int) -> bool:
        outcome = self.get(outcome_id)
        if outcome is None:
            return False
        self.session.delete(outcome)
        self.session.commit()
        return True


class HistoricalZoneScoreSnapshotRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(
        self,
        *,
        species: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[HistoricalZoneScoreSnapshotModel]:
        statement = select(HistoricalZoneScoreSnapshotModel)
        if species:
            statement = statement.where(HistoricalZoneScoreSnapshotModel.species == species)
        if date_from:
            statement = statement.where(HistoricalZoneScoreSnapshotModel.date >= date_from)
        if date_to:
            statement = statement.where(HistoricalZoneScoreSnapshotModel.date <= date_to)
        statement = statement.order_by(
            HistoricalZoneScoreSnapshotModel.date.desc(),
            HistoricalZoneScoreSnapshotModel.species.asc(),
            HistoricalZoneScoreSnapshotModel.score.desc(),
        )
        return list(self.session.scalars(statement))

    def replace_for_date_species(
        self,
        *,
        trip_date: date,
        species: str,
        snapshots: list[HistoricalZoneScoreSnapshotModel],
    ) -> list[HistoricalZoneScoreSnapshotModel]:
        self.session.execute(
            delete(HistoricalZoneScoreSnapshotModel).where(
                HistoricalZoneScoreSnapshotModel.date == trip_date,
                HistoricalZoneScoreSnapshotModel.species == species,
            )
        )
        for snapshot in snapshots:
            self.session.add(snapshot)
        self.session.commit()
        for snapshot in snapshots:
            self.session.refresh(snapshot)
        return snapshots
