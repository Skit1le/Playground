import unittest
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.routes.trip_outcomes import create_trip_outcome, delete_trip_outcome, list_trip_outcomes, update_trip_outcome
from app.schemas import TripOutcomeCreate, TripOutcomeRecord, TripOutcomeUpdate


class FakeTripOutcomeService:
    def __init__(self):
        self.records = [
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

    def list_outcomes(self):
        return self.records

    def create_outcome(self, payload: TripOutcomeCreate):
        return TripOutcomeRecord(id="2", **payload.model_dump())

    def update_outcome(self, outcome_id: int, payload: TripOutcomeUpdate):
        base = self.records[0].model_dump()
        base["id"] = str(outcome_id)
        base.update(payload.model_dump(exclude_unset=True))
        return TripOutcomeRecord(**base)

    def delete_outcome(self, outcome_id: int):
        return None


class TripOutcomeRouteTestCase(unittest.TestCase):
    def test_trip_outcome_routes_require_database(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status="unavailable")))
        with self.assertRaises(HTTPException) as context:
            list_trip_outcomes(request=request, trip_outcome_service=FakeTripOutcomeService())
        self.assertEqual(context.exception.status_code, 503)

    def test_create_update_delete_trip_outcome(self) -> None:
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database_status="ok")))
        service = FakeTripOutcomeService()

        created = create_trip_outcome(
            request=request,
            trip_outcome_service=service,
            payload=TripOutcomeCreate(
                date=date(2025, 9, 15),
                target_species="bluefin",
                zone_id="dip-north",
                catch_success=0.66,
                catch_count=2,
                vessel="Second Drift",
                notes="Late afternoon life.",
            ),
        )
        updated = update_trip_outcome(
            outcome_id=1,
            payload=TripOutcomeUpdate(notes="Updated notes"),
            request=request,
            trip_outcome_service=service,
        )
        deleted = delete_trip_outcome(
            outcome_id=1,
            request=request,
            trip_outcome_service=service,
        )

        self.assertEqual(created.id, "2")
        self.assertEqual(updated.notes, "Updated notes")
        self.assertEqual(deleted.status_code, 204)


if __name__ == "__main__":
    unittest.main()
