import unittest
from datetime import date

from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.environmental_inputs import ZoneEnvironmentalSignals
from app.services.zones import SpeciesConfigNotFoundError, ZonesService


class FakeSpeciesConfigRepository:
    def __init__(self, config: SpeciesScoringConfigModel | None):
        self.config = config

    def get_by_species(self, species: str) -> SpeciesScoringConfigModel | None:
        if self.config is not None and self.config.species == species:
            return self.config
        return None

    def list_all(self) -> list[SpeciesScoringConfigModel]:
        return [self.config] if self.config is not None else []


class FakeZoneRepository:
    def __init__(self, zones: list[ZoneModel]):
        self.zones = zones

    def list_for_species(self, species: str) -> list[ZoneModel]:
        return [zone for zone in self.zones if species in zone.species]


class FakeEnvironmentalInputProvider:
    def get_zone_signals(self, zone: ZoneModel, trip_date: date) -> ZoneEnvironmentalSignals:
        return ZoneEnvironmentalSignals(
            sea_surface_temp_f=66.4,
            temp_gradient_f_per_nm=2.4,
            structure_distance_nm=0.9,
            chlorophyll_mg_m3=0.31,
            current_speed_kts=1.7,
            current_break_index=0.91,
            weather_risk_index=0.12,
        )


def make_species_config() -> SpeciesScoringConfigModel:
    return SpeciesScoringConfigModel(
        species="bluefin",
        label="Bluefin Tuna",
        season_window="June-October",
        notes="Test config",
        preferred_temp_min_f=62.0,
        preferred_temp_max_f=69.0,
        ideal_chlorophyll_min=0.2,
        ideal_chlorophyll_max=0.4,
        ideal_current_min_kts=1.0,
        ideal_current_max_kts=2.0,
        temp_suitability_weight=0.3,
        temp_gradient_weight=0.2,
        structure_proximity_weight=0.2,
        chlorophyll_suitability_weight=0.1,
        current_suitability_weight=0.1,
        weather_fishability_weight=0.1,
    )


def make_zone(
    *,
    zone_id: str,
    name: str,
    distance_nm: int,
    sea_surface_temp_f: float,
    temp_gradient_f_per_nm: float,
    structure_distance_nm: float,
    chlorophyll_mg_m3: float,
    current_speed_kts: float,
    current_break_index: float,
    weather_risk_index: float,
) -> ZoneModel:
    return ZoneModel(
        id=zone_id,
        name=name,
        species=["bluefin"],
        distance_nm=distance_nm,
        center_lat=40.95,
        center_lng=-71.88,
        summary=f"{name} summary",
        sea_surface_temp_f=sea_surface_temp_f,
        temp_gradient_f_per_nm=temp_gradient_f_per_nm,
        structure_distance_nm=structure_distance_nm,
        chlorophyll_mg_m3=chlorophyll_mg_m3,
        current_speed_kts=current_speed_kts,
        current_break_index=current_break_index,
        weather_risk_index=weather_risk_index,
        depth_ft=240,
    )


class ZonesServiceTestCase(unittest.TestCase):
    def test_list_ranked_zones_sorts_scores_and_keeps_schema(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository(
                [
                    make_zone(
                        zone_id="cold-edge",
                        name="Cold Edge",
                        distance_nm=52,
                        sea_surface_temp_f=58.0,
                        temp_gradient_f_per_nm=0.8,
                        structure_distance_nm=3.5,
                        chlorophyll_mg_m3=0.48,
                        current_speed_kts=0.9,
                        current_break_index=0.45,
                        weather_risk_index=0.42,
                    ),
                    make_zone(
                        zone_id="prime-edge",
                        name="Prime Edge",
                        distance_nm=61,
                        sea_surface_temp_f=65.0,
                        temp_gradient_f_per_nm=2.1,
                        structure_distance_nm=1.2,
                        chlorophyll_mg_m3=0.28,
                        current_speed_kts=1.6,
                        current_break_index=0.88,
                        weather_risk_index=0.14,
                    ),
                ]
            ),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
        )

        ranked_zones = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)

        self.assertEqual([zone.id for zone in ranked_zones], ["prime-edge", "cold-edge"])
        self.assertEqual(
            set(ranked_zones[0].model_dump().keys()),
            {
                "id",
                "name",
                "species",
                "distance_nm",
                "center",
                "depth_ft",
                "summary",
                "sea_surface_temp_f",
                "temp_gradient_f_per_nm",
                "structure_distance_nm",
                "chlorophyll_mg_m3",
                "current_speed_kts",
                "current_break_index",
                "weather_risk_index",
                "score",
                "score_breakdown",
                "scored_for_species",
                "scored_for_date",
            },
        )
        self.assertEqual(ranked_zones[0].scored_for_species, "bluefin")
        self.assertEqual(ranked_zones[0].scored_for_date, date(2026, 6, 18))

    def test_list_ranked_zones_uses_provider_signals_in_response_payload(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository(
                [
                    make_zone(
                        zone_id="prime-edge",
                        name="Prime Edge",
                        distance_nm=61,
                        sea_surface_temp_f=59.0,
                        temp_gradient_f_per_nm=0.7,
                        structure_distance_nm=4.1,
                        chlorophyll_mg_m3=0.47,
                        current_speed_kts=0.8,
                        current_break_index=0.33,
                        weather_risk_index=0.51,
                    )
                ]
            ),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=FakeEnvironmentalInputProvider(),
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertEqual(ranked_zone.sea_surface_temp_f, 66.4)
        self.assertEqual(ranked_zone.temp_gradient_f_per_nm, 2.4)
        self.assertEqual(ranked_zone.structure_distance_nm, 0.9)
        self.assertEqual(ranked_zone.chlorophyll_mg_m3, 0.31)
        self.assertEqual(ranked_zone.current_speed_kts, 1.7)
        self.assertEqual(ranked_zone.current_break_index, 0.91)
        self.assertEqual(ranked_zone.weather_risk_index, 0.12)

    def test_list_ranked_zones_raises_when_species_config_is_missing(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository([]),
            species_config_repository=FakeSpeciesConfigRepository(None),
        )

        with self.assertRaises(SpeciesConfigNotFoundError):
            service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)


if __name__ == "__main__":
    unittest.main()
