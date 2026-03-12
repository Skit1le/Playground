from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import SpeciesScoringConfigModel, ZoneModel


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
