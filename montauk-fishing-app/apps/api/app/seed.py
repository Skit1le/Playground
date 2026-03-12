from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, engine
from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.seed_data import SPECIES_SCORING_CONFIGS, ZONE_CATALOG


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)


def seed_database(session: Session) -> None:
    existing_species = {
        config.species: config
        for config in session.scalars(select(SpeciesScoringConfigModel)).all()
    }
    for config in SPECIES_SCORING_CONFIGS:
        existing = existing_species.get(config["species"])
        if existing is None:
            session.add(SpeciesScoringConfigModel(**config))
            continue

        for field_name, value in config.items():
            setattr(existing, field_name, value)

    existing_zones = {zone.id: zone for zone in session.scalars(select(ZoneModel)).all()}
    for zone in ZONE_CATALOG:
        existing = existing_zones.get(zone["id"])
        if existing is None:
            session.add(ZoneModel(**zone))
            continue

        for field_name, value in zone.items():
            setattr(existing, field_name, value)

    session.commit()
