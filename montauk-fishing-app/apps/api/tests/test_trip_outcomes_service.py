import unittest
from datetime import date

from app.schemas import TripOutcomeCreate, TripOutcomeUpdate
from app.services.trip_outcomes import TripOutcomeNotFoundError, TripOutcomeService


class FakeTripOutcomeModel:
    def __init__(
        self,
        *,
        outcome_id: int,
        trip_date: date,
        target_species: str,
        zone_id: str | None,
        catch_success: float,
        catch_count: int,
        vessel: str,
        notes: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ):
        self.id = outcome_id
        self.date = trip_date
        self.target_species = target_species
        self.zone_id = zone_id
        self.latitude = latitude
        self.longitude = longitude
        self.catch_success = catch_success
        self.catch_count = catch_count
        self.vessel = vessel
        self.notes = notes


class FakeTripOutcomeRepository:
    def __init__(self):
        self.records: dict[int, FakeTripOutcomeModel] = {}
        self.next_id = 1

    def list_all(self):
        return list(self.records.values())

    def get(self, outcome_id: int):
        return self.records.get(outcome_id)

    def create(self, outcome):
        outcome.id = self.next_id
        self.records[self.next_id] = outcome
        self.next_id += 1
        return outcome

    def update(self, outcome):
        self.records[outcome.id] = outcome
        return outcome

    def delete(self, outcome_id: int) -> bool:
        return self.records.pop(outcome_id, None) is not None


class TripOutcomeServiceTestCase(unittest.TestCase):
    def test_create_update_and_delete_outcome(self) -> None:
        service = TripOutcomeService(repository=FakeTripOutcomeRepository())

        created = service.create_outcome(
            TripOutcomeCreate(
                date=date(2025, 9, 14),
                target_species="yellowfin",
                zone_id="hudson-edge-east",
                catch_success=0.92,
                catch_count=6,
                vessel="North Star",
                notes="Strong life on the edge.",
            )
        )
        self.assertEqual(created.id, "1")

        updated = service.update_outcome(
            1,
            TripOutcomeUpdate(
                catch_count=7,
                notes="Updated after final tally.",
            ),
        )
        self.assertEqual(updated.catch_count, 7)
        self.assertEqual(updated.notes, "Updated after final tally.")

        service.delete_outcome(1)
        self.assertEqual(service.list_outcomes(), [])

    def test_update_missing_outcome_raises_not_found(self) -> None:
        service = TripOutcomeService(repository=FakeTripOutcomeRepository())

        with self.assertRaises(TripOutcomeNotFoundError):
            service.update_outcome(999, TripOutcomeUpdate(notes="missing"))


if __name__ == "__main__":
    unittest.main()
