import unittest
from datetime import date

from fastapi import HTTPException

from app.api.routes.zones import list_zones
from app.schemas import (
    RankedZone,
    ScoreBreakdown,
    ScoreExplanationFactor,
    WeightedScoreBreakdown,
    WeightedScoreConfig,
    ZoneCenter,
    ZoneScoreExplanation,
)
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
        nearest_strong_break_distance_nm=3.4,
        structure_distance_nm=1.2,
        chlorophyll_mg_m3=0.28,
        nearest_strong_chl_break_distance_nm=4.1,
        current_speed_kts=1.6,
        current_break_index=0.88,
        weather_risk_index=0.14,
        score=91.7,
        score_breakdown=ScoreBreakdown(
            temp_suitability=100.0,
            temp_gradient=84.0,
            temp_break_proximity=89.0,
            edge_alignment=76.0,
            structure_proximity=80.0,
            chlorophyll_suitability=100.0,
            chlorophyll_break_proximity=82.0,
            current_suitability=96.4,
            weather_fishability=92.0,
        ),
        score_weights=WeightedScoreConfig(
            temp_suitability=0.2051,
            temp_gradient=0.1368,
            temp_break_proximity=0.0598,
            edge_alignment=0.0256,
            structure_proximity=0.1538,
            chlorophyll_suitability=0.094,
            chlorophyll_break_proximity=0.0342,
            current_suitability=0.1111,
            weather_fishability=0.1538,
        ),
        weighted_score_breakdown=WeightedScoreBreakdown(
            temp_suitability=20.5,
            temp_gradient=11.5,
            temp_break_proximity=5.3,
            edge_alignment=1.9,
            structure_proximity=12.3,
            chlorophyll_suitability=9.4,
            chlorophyll_break_proximity=2.8,
            current_suitability=10.7,
            weather_fishability=14.1,
        ),
        score_explanation=ZoneScoreExplanation(
            headline="Prime Edge ranks well because the water setup stacks multiple favorable signals.",
            summary="SST, color, and structure all line up for bluefin.",
            top_reasons=[
                "Species temperature fit: Water temperature lines up with the preferred bluefin range.",
                "SST break proximity: Closer zones sit nearer to meaningful temperature breaks where bait and pelagics often stack.",
            ],
            factors=[
                ScoreExplanationFactor(
                    factor="temp_suitability",
                    label="Species temperature fit",
                    raw_value="65.0 F",
                    score=100.0,
                    weighted_contribution=20.5,
                    reason="Water temperature lines up with the preferred bluefin range.",
                )
            ],
        ),
        scored_for_species="bluefin",
        scored_for_date=date(2026, 6, 18),
    )


class ZonesRouteTestCase(unittest.TestCase):
    def test_list_zones_delegates_to_service(self) -> None:
        fake_service = FakeZonesService(response=[make_ranked_zone()])

        response = list_zones(
            zones_service=fake_service,
            date_value="2026-06-18",
            species="bluefin",
        )

        self.assertEqual(len(response), 1)
        self.assertEqual(fake_service.calls, [("bluefin", date(2026, 6, 18), 10)])

    def test_list_zones_accepts_mm_dd_yyyy_dates(self) -> None:
        fake_service = FakeZonesService(response=[make_ranked_zone()])

        response = list_zones(
            zones_service=fake_service,
            date_value="06-18-2026",
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
                date_value="06/18/2026",
                species="bluefin",
            )

        self.assertEqual(context.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
