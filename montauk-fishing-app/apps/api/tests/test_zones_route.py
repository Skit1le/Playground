import unittest
from datetime import date

from fastapi import HTTPException

from app.api.routes.zones import list_zones
from app.schemas import RankedZone, ScoreBreakdown, WeightedScoreBreakdown, WeightedScoreConfig, ZoneCenter
from app.services.zones import SpeciesConfigNotFoundError


class FakeZonesService:
    def __init__(self, response: list[RankedZone] | None = None, error: Exception | None = None):
        self.response = response or []
        self.error = error
        self.calls: list[tuple[str, date, int]] = []

    def list_ranked_zones(self, species: str, trip_date: date, limit: int) -> list[RankedZone]:
        self.calls.append((species, trip_date, limit))
        if self.error is not None:
            raise self.error
        return self.response


def make_ranked_zone() -> RankedZone:
    return RankedZone(
        id="prime-edge",
        name="Prime Edge",
        species=["bluefin"],
        distance_nm=61,
        center=ZoneCenter(lat=40.95, lng=-71.88),
        depth_ft=240,
        summary="Prime Edge summary",
        sea_surface_temp_f=65.0,
        temp_gradient_f_per_nm=2.1,
        structure_distance_nm=1.2,
        chlorophyll_mg_m3=0.28,
        current_speed_kts=1.6,
        current_break_index=0.88,
        weather_risk_index=0.14,
        score=91.7,
        score_breakdown=ScoreBreakdown(
            temp_suitability=100.0,
            temp_gradient=84.0,
            structure_proximity=80.0,
            chlorophyll_suitability=100.0,
            current_suitability=96.4,
            weather_fishability=92.0,
        ),
        score_weights=WeightedScoreConfig(
            temp_suitability=0.24,
            temp_gradient=0.16,
            structure_proximity=0.18,
            chlorophyll_suitability=0.11,
            current_suitability=0.13,
            weather_fishability=0.18,
        ),
        weighted_score_breakdown=WeightedScoreBreakdown(
            temp_suitability=24.0,
            temp_gradient=13.4,
            structure_proximity=14.4,
            chlorophyll_suitability=11.0,
            current_suitability=12.5,
            weather_fishability=16.4,
        ),
        scored_for_species="bluefin",
        scored_for_date=date(2026, 6, 18),
    )


class ZonesRouteTestCase(unittest.TestCase):
    def test_list_zones_delegates_to_service(self) -> None:
        fake_service = FakeZonesService(response=[make_ranked_zone()])

        response = list_zones(
            zones_service=fake_service,
            date_value=date(2026, 6, 18),
            species="bluefin",
        )

        self.assertEqual(len(response), 1)
        self.assertEqual(fake_service.calls, [("bluefin", date(2026, 6, 18), 10)])

    def test_list_zones_returns_not_found_for_missing_config(self) -> None:
        fake_service = FakeZonesService(
            error=SpeciesConfigNotFoundError("No scoring configuration found for species 'bluefin'.")
        )

        with self.assertRaises(HTTPException) as context:
            list_zones(
                zones_service=fake_service,
                date_value=date(2026, 6, 18),
                species="bluefin",
            )

        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
