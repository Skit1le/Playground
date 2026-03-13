import unittest
from datetime import date
from time import sleep

from app.chlorophyll_provider import ChlorophyllDataUnavailableError, ChlorophyllObservation, ChlorophyllPoint
from app.current_provider import CurrentDataUnavailableError, CurrentObservation
from app.db_models import SpeciesScoringConfigModel, ZoneModel
from app.environmental_inputs import (
    ChlorophyllBackedSource,
    CurrentBackedSource,
    FallbackBathymetrySource,
    FallbackChlorophyllSource,
    FallbackCurrentSource,
    FallbackTemperatureSource,
    FallbackWeatherSource,
    MockZoneEnvironmentalSignalStore,
    SeededBathymetrySource,
    SeededCurrentSource,
    SeededChlorophyllSource,
    SeededTemperatureSource,
    SeededWeatherSource,
    SstBackedTemperatureSource,
    StructureBackedSource,
    WeatherBackedSource,
    ZoneEnvironmentalInputService,
    ZoneEnvironmentalSignals,
)
from app.services.zones import SpeciesConfigNotFoundError, ZonesService
from app.sst_provider import SstDataUnavailableError, SstObservation, SstPoint
from app.structure_provider import StructureDataUnavailableError, StructureObservation
from app.weather_provider import WeatherDataUnavailableError, WeatherObservation


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
        if zone.id == "prime-edge":
            return ZoneEnvironmentalSignals(
                sea_surface_temp_f=66.4,
                temp_gradient_f_per_nm=2.4,
                structure_distance_nm=0.9,
                chlorophyll_mg_m3=0.31,
                current_speed_kts=1.7,
                current_break_index=0.91,
                weather_risk_index=0.12,
            )
        return ZoneEnvironmentalSignals(
            sea_surface_temp_f=58.0,
            temp_gradient_f_per_nm=0.8,
            structure_distance_nm=3.5,
            chlorophyll_mg_m3=0.48,
            current_speed_kts=0.9,
            current_break_index=0.45,
            weather_risk_index=0.42,
        )


class FakeSstProvider:
    def __init__(
        self,
        observation: SstObservation | Exception | dict[str, SstObservation] = SstObservation(
            sea_surface_temp_f=66.0,
            temp_gradient_f_per_nm=1.2,
        ),
        source_name: str = "processed",
        points: tuple[SstPoint, ...] | None = None,
    ):
        self.observation = observation
        self.source_name = source_name
        self.calls: list[tuple[str, date]] = []
        self.min_lat = 39.8
        self.max_lat = 41.4
        self.min_lon = -72.4
        self.max_lon = -69.8
        self.points = points or ()

    def get_zone_sst(self, zone_id: str, latitude: float, longitude: float, trip_date: date) -> SstObservation:
        self.calls.append((zone_id, trip_date))
        if isinstance(self.observation, Exception):
            raise self.observation
        if isinstance(self.observation, dict):
            return self.observation[zone_id]
        return self.observation

    def get_sst_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[SstPoint, ...]:
        return self.points


class FakeChlorophyllProvider:
    def __init__(
        self,
        observation: ChlorophyllObservation | Exception,
        points: tuple[ChlorophyllPoint, ...] | None = None,
    ):
        self.observation = observation
        self.calls: list[tuple[str, date]] = []
        self.min_lat = 39.8
        self.max_lat = 41.4
        self.min_lon = -72.4
        self.max_lon = -69.8
        self.points = points or ()

    def get_zone_chlorophyll(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> ChlorophyllObservation:
        self.calls.append((zone_id, trip_date))
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation

    def get_chlorophyll_points(
        self,
        trip_date: date,
        *,
        min_lat: float | None = None,
        max_lat: float | None = None,
        min_lon: float | None = None,
        max_lon: float | None = None,
    ) -> tuple[ChlorophyllPoint, ...]:
        return self.points


class FakeCurrentProvider:
    def __init__(self, observation: CurrentObservation | Exception):
        self.observation = observation
        self.calls: list[tuple[str, date]] = []

    def get_zone_current(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> CurrentObservation:
        self.calls.append((zone_id, trip_date))
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation


class FakeStructureProvider:
    def __init__(self, observation: StructureObservation | Exception):
        self.observation = observation
        self.calls: list[tuple[str, date]] = []

    def get_zone_structure(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> StructureObservation:
        self.calls.append((zone_id, trip_date))
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation


class FakeWeatherProvider:
    def __init__(self, observation: WeatherObservation | Exception):
        self.observation = observation
        self.calls: list[tuple[str, date]] = []

    def get_zone_weather(
        self,
        zone_id: str,
        latitude: float,
        longitude: float,
        trip_date: date,
    ) -> WeatherObservation:
        self.calls.append((zone_id, trip_date))
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation


class SlowSstProvider:
    def __init__(self, delay_seconds: float):
        self.delay_seconds = delay_seconds

    def get_zone_sst(self, zone_id: str, latitude: float, longitude: float, trip_date: date) -> SstObservation:
        sleep(self.delay_seconds)
        return SstObservation(
            sea_surface_temp_f=71.2,
            temp_gradient_f_per_nm=1.9,
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
    center_lat: float = 40.95,
    center_lng: float = -71.88,
) -> ZoneModel:
    return ZoneModel(
        id=zone_id,
        name=name,
        species=["bluefin"],
        distance_nm=distance_nm,
        center_lat=center_lat,
        center_lng=center_lng,
        summary=f"{name} summary",
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
                    ),
                    make_zone(
                        zone_id="prime-edge",
                        name="Prime Edge",
                        distance_nm=61,
                    ),
                ]
            ),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=FakeEnvironmentalInputProvider(),
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
                "nearest_strong_break_distance_nm",
                "structure_distance_nm",
                "chlorophyll_mg_m3",
                "nearest_strong_chl_break_distance_nm",
                "current_speed_kts",
                "current_break_index",
                "weather_risk_index",
                "score",
                "score_breakdown",
                "score_weights",
                "weighted_score_breakdown",
                "score_explanation",
                "scored_for_species",
                "scored_for_date",
            },
        )
        self.assertEqual(ranked_zones[0].scored_for_species, "bluefin")
        self.assertEqual(ranked_zones[0].scored_for_date, date(2026, 6, 18))
        self.assertIn("temp_break_proximity", ranked_zones[0].score_breakdown.model_dump())
        self.assertIn("chlorophyll_break_proximity", ranked_zones[0].score_breakdown.model_dump())
        self.assertIn("edge_alignment", ranked_zones[0].score_breakdown.model_dump())
        self.assertIn("temp_break_proximity", ranked_zones[0].score_weights.model_dump())
        self.assertIn("chlorophyll_break_proximity", ranked_zones[0].score_weights.model_dump())
        self.assertIn("edge_alignment", ranked_zones[0].score_weights.model_dump())
        self.assertIn("temp_break_proximity", ranked_zones[0].weighted_score_breakdown.model_dump())
        self.assertIn("chlorophyll_break_proximity", ranked_zones[0].weighted_score_breakdown.model_dump())
        self.assertIn("edge_alignment", ranked_zones[0].weighted_score_breakdown.model_dump())
        self.assertGreater(len(ranked_zones[0].score_explanation.top_reasons), 0)
        self.assertGreater(len(ranked_zones[0].score_explanation.factors), 0)

    def test_list_ranked_zones_exposes_weights_and_weighted_score_breakdown(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=FakeEnvironmentalInputProvider(),
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertAlmostEqual(
            ranked_zone.score,
            round(sum(ranked_zone.weighted_score_breakdown.model_dump().values()), 1),
            places=0,
        )
        self.assertAlmostEqual(sum(ranked_zone.score_weights.model_dump().values()), 1.0, places=3)

    def test_bluefin_temperature_scoring_is_not_overly_punitive_on_warm_shoulder(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=FakeEnvironmentalInputProvider(),
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertGreaterEqual(ranked_zone.score_breakdown.temp_suitability, 90.0)

    def test_list_ranked_zones_rewards_proximity_to_strong_sst_breaks(self) -> None:
        break_points = (
            SstPoint(latitude=40.85, longitude=-72.1, sea_surface_temp_f=41.0),
            SstPoint(latitude=40.95, longitude=-72.1, sea_surface_temp_f=41.0),
            SstPoint(latitude=41.05, longitude=-72.1, sea_surface_temp_f=41.0),
            SstPoint(latitude=40.85, longitude=-71.95, sea_surface_temp_f=41.2),
            SstPoint(latitude=40.95, longitude=-71.95, sea_surface_temp_f=41.1),
            SstPoint(latitude=41.05, longitude=-71.95, sea_surface_temp_f=41.2),
            SstPoint(latitude=40.85, longitude=-71.8, sea_surface_temp_f=47.6),
            SstPoint(latitude=40.95, longitude=-71.8, sea_surface_temp_f=47.9),
            SstPoint(latitude=41.05, longitude=-71.8, sea_surface_temp_f=47.8),
            SstPoint(latitude=40.85, longitude=-71.65, sea_surface_temp_f=48.0),
            SstPoint(latitude=40.95, longitude=-71.65, sea_surface_temp_f=48.0),
            SstPoint(latitude=41.05, longitude=-71.65, sea_surface_temp_f=48.1),
        )
        sst_provider = FakeSstProvider(
            observation={
                "break-close": SstObservation(sea_surface_temp_f=46.8, temp_gradient_f_per_nm=2.2),
                "break-far": SstObservation(sea_surface_temp_f=46.8, temp_gradient_f_per_nm=2.2),
            },
            source_name="live",
            points=break_points,
        )
        environmental_input_provider = ZoneEnvironmentalInputService(
            temperature_source=SstBackedTemperatureSource(sst_provider),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "break-close": {
                        "sea_surface_temp_f": 46.8,
                        "temp_gradient_f_per_nm": 2.2,
                        "structure_distance_nm": 2.0,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.18,
                    },
                    "break-far": {
                        "sea_surface_temp_f": 46.8,
                        "temp_gradient_f_per_nm": 2.2,
                        "structure_distance_nm": 2.0,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.18,
                    },
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository(
                [
                    make_zone(zone_id="break-close", name="Break Close", distance_nm=58, center_lng=-71.87),
                    make_zone(zone_id="break-far", name="Break Far", distance_nm=58, center_lng=-71.35),
                ]
            ),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
            sst_break_target_cells=480,
            strong_break_threshold_f_per_nm=0.05,
        )

        ranked_zones = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)
        close_zone = next(zone for zone in ranked_zones if zone.id == "break-close")
        far_zone = next(zone for zone in ranked_zones if zone.id == "break-far")

        self.assertIsNotNone(close_zone.nearest_strong_break_distance_nm)
        self.assertIsNotNone(far_zone.nearest_strong_break_distance_nm)
        assert close_zone.nearest_strong_break_distance_nm is not None
        assert far_zone.nearest_strong_break_distance_nm is not None
        self.assertLess(close_zone.nearest_strong_break_distance_nm, far_zone.nearest_strong_break_distance_nm)
        self.assertGreater(close_zone.score_breakdown.temp_break_proximity, far_zone.score_breakdown.temp_break_proximity)
        self.assertGreater(close_zone.weighted_score_breakdown.temp_break_proximity, 0.0)

    def test_list_ranked_zones_exposes_break_distance_with_mock_sst_fallback(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=ZoneEnvironmentalInputService(
                temperature_source=SstBackedTemperatureSource(
                    FakeSstProvider(
                        observation=SstObservation(sea_surface_temp_f=63.5, temp_gradient_f_per_nm=0.9),
                        source_name="mock_fallback",
                        points=(
                            SstPoint(latitude=40.9, longitude=-72.05, sea_surface_temp_f=63.5),
                            SstPoint(latitude=40.9, longitude=-71.85, sea_surface_temp_f=67.8),
                            SstPoint(latitude=41.0, longitude=-72.05, sea_surface_temp_f=63.3),
                            SstPoint(latitude=41.0, longitude=-71.85, sea_surface_temp_f=68.0),
                        ),
                    )
                ),
                signal_store=MockZoneEnvironmentalSignalStore(
                    records={
                        "prime-edge": {
                            "sea_surface_temp_f": 63.5,
                            "temp_gradient_f_per_nm": 0.9,
                            "structure_distance_nm": 2.6,
                            "chlorophyll_mg_m3": 0.27,
                            "current_speed_kts": 1.4,
                            "current_break_index": 0.73,
                            "weather_risk_index": 0.22,
                        }
                    }
                ),
            ),
            sst_break_target_cells=320,
            strong_break_threshold_f_per_nm=0.04,
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertIsNotNone(ranked_zone.nearest_strong_break_distance_nm)
        self.assertGreaterEqual(ranked_zone.score_breakdown.temp_break_proximity, 0.0)

    def test_list_ranked_zones_rewards_proximity_to_strong_chlorophyll_breaks(self) -> None:
        chlorophyll_points = (
            ChlorophyllPoint(latitude=40.85, longitude=-72.1, chlorophyll_mg_m3=0.12),
            ChlorophyllPoint(latitude=40.95, longitude=-72.1, chlorophyll_mg_m3=0.12),
            ChlorophyllPoint(latitude=41.05, longitude=-72.1, chlorophyll_mg_m3=0.13),
            ChlorophyllPoint(latitude=40.85, longitude=-71.95, chlorophyll_mg_m3=0.14),
            ChlorophyllPoint(latitude=40.95, longitude=-71.95, chlorophyll_mg_m3=0.14),
            ChlorophyllPoint(latitude=41.05, longitude=-71.95, chlorophyll_mg_m3=0.15),
            ChlorophyllPoint(latitude=40.85, longitude=-71.8, chlorophyll_mg_m3=0.36),
            ChlorophyllPoint(latitude=40.95, longitude=-71.8, chlorophyll_mg_m3=0.35),
            ChlorophyllPoint(latitude=41.05, longitude=-71.8, chlorophyll_mg_m3=0.34),
            ChlorophyllPoint(latitude=40.85, longitude=-71.65, chlorophyll_mg_m3=0.38),
            ChlorophyllPoint(latitude=40.95, longitude=-71.65, chlorophyll_mg_m3=0.37),
            ChlorophyllPoint(latitude=41.05, longitude=-71.65, chlorophyll_mg_m3=0.36),
        )
        environmental_input_provider = ZoneEnvironmentalInputService(
            chlorophyll_source=ChlorophyllBackedSource(
                FakeChlorophyllProvider(
                    ChlorophyllObservation(chlorophyll_mg_m3=0.28),
                    points=chlorophyll_points,
                )
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "chl-close": {
                        "sea_surface_temp_f": 66.0,
                        "temp_gradient_f_per_nm": 1.6,
                        "structure_distance_nm": 2.0,
                        "chlorophyll_mg_m3": 0.28,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.18,
                    },
                    "chl-far": {
                        "sea_surface_temp_f": 66.0,
                        "temp_gradient_f_per_nm": 1.6,
                        "structure_distance_nm": 2.0,
                        "chlorophyll_mg_m3": 0.28,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.18,
                    },
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository(
                [
                    make_zone(zone_id="chl-close", name="Chl Close", distance_nm=58, center_lng=-71.87),
                    make_zone(zone_id="chl-far", name="Chl Far", distance_nm=58, center_lng=-71.3),
                ]
            ),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
            chlorophyll_break_target_cells=360,
            strong_chlorophyll_break_threshold_mg_m3_per_nm=0.01,
        )

        ranked_zones = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)
        close_zone = next(zone for zone in ranked_zones if zone.id == "chl-close")
        far_zone = next(zone for zone in ranked_zones if zone.id == "chl-far")

        self.assertIsNotNone(close_zone.nearest_strong_chl_break_distance_nm)
        self.assertIsNotNone(far_zone.nearest_strong_chl_break_distance_nm)
        self.assertLess(
            close_zone.nearest_strong_chl_break_distance_nm,
            far_zone.nearest_strong_chl_break_distance_nm,
        )
        self.assertGreater(
            close_zone.score_breakdown.chlorophyll_break_proximity,
            far_zone.score_breakdown.chlorophyll_break_proximity,
        )

    def test_list_ranked_zones_exposes_chlorophyll_break_distance_with_mock_fallback(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=ZoneEnvironmentalInputService(
                chlorophyll_source=ChlorophyllBackedSource(
                    FakeChlorophyllProvider(
                        ChlorophyllObservation(chlorophyll_mg_m3=0.27),
                        points=(
                            ChlorophyllPoint(latitude=40.9, longitude=-72.05, chlorophyll_mg_m3=0.14),
                            ChlorophyllPoint(latitude=40.9, longitude=-71.85, chlorophyll_mg_m3=0.33),
                            ChlorophyllPoint(latitude=41.0, longitude=-72.05, chlorophyll_mg_m3=0.13),
                            ChlorophyllPoint(latitude=41.0, longitude=-71.85, chlorophyll_mg_m3=0.34),
                        ),
                    )
                ),
                signal_store=MockZoneEnvironmentalSignalStore(
                    records={
                        "prime-edge": {
                            "sea_surface_temp_f": 63.5,
                            "temp_gradient_f_per_nm": 0.9,
                            "structure_distance_nm": 2.6,
                            "chlorophyll_mg_m3": 0.27,
                            "current_speed_kts": 1.4,
                            "current_break_index": 0.73,
                            "weather_risk_index": 0.22,
                        }
                    }
                ),
            ),
            chlorophyll_break_target_cells=320,
            strong_chlorophyll_break_threshold_mg_m3_per_nm=0.01,
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertIsNotNone(ranked_zone.nearest_strong_chl_break_distance_nm)
        self.assertGreaterEqual(ranked_zone.score_breakdown.chlorophyll_break_proximity, 0.0)

    def test_list_ranked_zones_rewards_combined_edge_alignment(self) -> None:
        sst_points = (
            SstPoint(latitude=40.9, longitude=-72.05, sea_surface_temp_f=41.0),
            SstPoint(latitude=40.9, longitude=-71.85, sea_surface_temp_f=47.8),
            SstPoint(latitude=41.0, longitude=-72.05, sea_surface_temp_f=41.2),
            SstPoint(latitude=41.0, longitude=-71.85, sea_surface_temp_f=48.0),
        )
        chlorophyll_points = (
            ChlorophyllPoint(latitude=40.9, longitude=-72.05, chlorophyll_mg_m3=0.12),
            ChlorophyllPoint(latitude=40.9, longitude=-71.85, chlorophyll_mg_m3=0.34),
            ChlorophyllPoint(latitude=41.0, longitude=-72.05, chlorophyll_mg_m3=0.13),
            ChlorophyllPoint(latitude=41.0, longitude=-71.85, chlorophyll_mg_m3=0.35),
        )
        environmental_input_provider = ZoneEnvironmentalInputService(
            temperature_source=SstBackedTemperatureSource(
                FakeSstProvider(
                    observation=SstObservation(sea_surface_temp_f=66.0, temp_gradient_f_per_nm=1.7),
                    source_name="live",
                    points=sst_points,
                )
            ),
            chlorophyll_source=ChlorophyllBackedSource(
                FakeChlorophyllProvider(
                    ChlorophyllObservation(chlorophyll_mg_m3=0.27),
                    points=chlorophyll_points,
                )
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "both-edges": {
                        "sea_surface_temp_f": 66.0,
                        "temp_gradient_f_per_nm": 1.7,
                        "structure_distance_nm": 2.0,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.18,
                    },
                    "temp-only": {
                        "sea_surface_temp_f": 66.0,
                        "temp_gradient_f_per_nm": 1.7,
                        "structure_distance_nm": 2.0,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.18,
                    },
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository(
                [
                    make_zone(zone_id="both-edges", name="Both Edges", distance_nm=58, center_lng=-71.87),
                    make_zone(zone_id="temp-only", name="Temp Only", distance_nm=58, center_lng=-71.35),
                ]
            ),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
            sst_break_target_cells=320,
            chlorophyll_break_target_cells=320,
        )

        ranked_zones = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)
        both_edges = next(zone for zone in ranked_zones if zone.id == "both-edges")
        temp_only = next(zone for zone in ranked_zones if zone.id == "temp-only")

        self.assertGreater(both_edges.score_breakdown.edge_alignment, temp_only.score_breakdown.edge_alignment)
        self.assertGreater(both_edges.weighted_score_breakdown.edge_alignment, 0.0)

    def test_list_ranked_zones_uses_provider_signals_in_response_payload(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository(
                [
                    make_zone(
                        zone_id="prime-edge",
                        name="Prime Edge",
                        distance_nm=61,
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

    def test_list_ranked_zones_prefers_provider_signals_over_zone_object_values(self) -> None:
        conflicting_zone = make_zone(
            zone_id="prime-edge",
            name="Prime Edge",
            distance_nm=61,
        )
        conflicting_zone.sea_surface_temp_f = 54.2
        conflicting_zone.temp_gradient_f_per_nm = 0.4
        conflicting_zone.structure_distance_nm = 5.8
        conflicting_zone.chlorophyll_mg_m3 = 0.62
        conflicting_zone.current_speed_kts = 0.3
        conflicting_zone.current_break_index = 0.08
        conflicting_zone.weather_risk_index = 0.79

        service = ZonesService(
            zone_repository=FakeZoneRepository([conflicting_zone]),
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

    def test_list_ranked_zones_uses_provider_supplied_sst_with_mock_non_sst_fields(self) -> None:
        environmental_input_provider = ZoneEnvironmentalInputService(
            temperature_source=SstBackedTemperatureSource(
                FakeSstProvider(
                    SstObservation(
                        sea_surface_temp_f=71.2,
                        temp_gradient_f_per_nm=1.9,
                    )
                )
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertEqual(ranked_zone.sea_surface_temp_f, 71.2)
        self.assertEqual(ranked_zone.temp_gradient_f_per_nm, 1.9)
        self.assertEqual(ranked_zone.chlorophyll_mg_m3, 0.27)
        self.assertEqual(ranked_zone.current_speed_kts, 1.4)

    def test_list_ranked_zones_uses_provider_supplied_chlorophyll_with_other_signals_unchanged(self) -> None:
        environmental_input_provider = ZoneEnvironmentalInputService(
            chlorophyll_source=ChlorophyllBackedSource(
                FakeChlorophyllProvider(ChlorophyllObservation(chlorophyll_mg_m3=0.33))
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertEqual(ranked_zone.chlorophyll_mg_m3, 0.33)
        self.assertEqual(ranked_zone.sea_surface_temp_f, 61.1)
        self.assertEqual(ranked_zone.current_speed_kts, 1.4)

    def test_list_ranked_zones_uses_provider_supplied_current_with_other_signals_unchanged(self) -> None:
        environmental_input_provider = ZoneEnvironmentalInputService(
            current_source=CurrentBackedSource(
                FakeCurrentProvider(
                    CurrentObservation(
                        current_speed_kts=2.05,
                        current_break_index=0.84,
                    )
                )
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertEqual(ranked_zone.current_speed_kts, 2.05)
        self.assertEqual(ranked_zone.current_break_index, 0.84)
        self.assertEqual(ranked_zone.chlorophyll_mg_m3, 0.27)
        self.assertEqual(ranked_zone.structure_distance_nm, 2.6)

    def test_list_ranked_zones_uses_provider_supplied_structure_with_other_signals_unchanged(self) -> None:
        environmental_input_provider = ZoneEnvironmentalInputService(
            bathymetry_source=StructureBackedSource(
                FakeStructureProvider(StructureObservation(structure_distance_nm=0.45))
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertEqual(ranked_zone.structure_distance_nm, 0.45)
        self.assertEqual(ranked_zone.current_speed_kts, 1.4)
        self.assertEqual(ranked_zone.weather_risk_index, 0.22)

    def test_list_ranked_zones_uses_provider_supplied_weather_with_other_signals_unchanged(self) -> None:
        environmental_input_provider = ZoneEnvironmentalInputService(
            weather_source=WeatherBackedSource(
                FakeWeatherProvider(WeatherObservation(weather_risk_index=0.11))
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )
        service = ZonesService(
            zone_repository=FakeZoneRepository([make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)]),
            species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
            environmental_input_provider=environmental_input_provider,
        )

        ranked_zone = service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

        self.assertEqual(ranked_zone.weather_risk_index, 0.11)
        self.assertEqual(ranked_zone.structure_distance_nm, 2.6)
        self.assertEqual(ranked_zone.current_speed_kts, 1.4)

    def test_list_ranked_zones_raises_when_species_config_is_missing(self) -> None:
        service = ZonesService(
            zone_repository=FakeZoneRepository([]),
            species_config_repository=FakeSpeciesConfigRepository(None),
        )

        with self.assertRaises(SpeciesConfigNotFoundError):
            service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)

    def test_zone_environmental_input_service_falls_back_when_sst_provider_fails(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            temperature_source=FallbackTemperatureSource(
                primary=SstBackedTemperatureSource(
                    FakeSstProvider(SstDataUnavailableError("missing processed SST"))
                ),
                fallback=SeededTemperatureSource(signal_store),
            ),
            signal_store=signal_store,
        )

        signals = provider.get_zone_signals(zone, date(2026, 6, 18))

        self.assertEqual(signals.sea_surface_temp_f, 63.5)
        self.assertEqual(signals.temp_gradient_f_per_nm, 0.9)

    def test_zone_environmental_input_service_exposes_source_metadata(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        provider = ZoneEnvironmentalInputService(
            temperature_source=SstBackedTemperatureSource(
                FakeSstProvider(
                    SstObservation(
                        sea_surface_temp_f=71.2,
                        temp_gradient_f_per_nm=1.9,
                    )
                )
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.metadata.sst_source, "processed")
        self.assertEqual(resolved.metadata.chlorophyll_source, "mock")
        self.assertEqual(resolved.metadata.current_source, "mock")

    def test_zone_environmental_input_service_exposes_live_sst_source_metadata(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        provider = ZoneEnvironmentalInputService(
            temperature_source=SstBackedTemperatureSource(
                FakeSstProvider(
                    SstObservation(
                        sea_surface_temp_f=71.2,
                        temp_gradient_f_per_nm=1.9,
                    ),
                    source_name="live",
                )
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.metadata.sst_source, "live")

    def test_zone_environmental_input_service_exposes_processed_chlorophyll_source_metadata(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        provider = ZoneEnvironmentalInputService(
            chlorophyll_source=ChlorophyllBackedSource(
                FakeChlorophyllProvider(ChlorophyllObservation(chlorophyll_mg_m3=0.33))
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.metadata.sst_source, "mock")
        self.assertEqual(resolved.metadata.chlorophyll_source, "processed")
        self.assertEqual(resolved.metadata.current_source, "mock")

    def test_zone_environmental_input_service_exposes_processed_current_source_metadata(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        provider = ZoneEnvironmentalInputService(
            current_source=CurrentBackedSource(
                FakeCurrentProvider(
                    CurrentObservation(
                        current_speed_kts=2.05,
                        current_break_index=0.84,
                    )
                )
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.metadata.sst_source, "mock")
        self.assertEqual(resolved.metadata.chlorophyll_source, "mock")
        self.assertEqual(resolved.metadata.current_source, "processed")

    def test_zone_environmental_input_service_exposes_processed_structure_source_metadata(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        provider = ZoneEnvironmentalInputService(
            bathymetry_source=StructureBackedSource(
                FakeStructureProvider(StructureObservation(structure_distance_nm=0.45))
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.metadata.bathymetry_source, "processed")
        self.assertEqual(resolved.metadata.weather_source, "mock")

    def test_zone_environmental_input_service_exposes_processed_weather_source_metadata(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        provider = ZoneEnvironmentalInputService(
            weather_source=WeatherBackedSource(
                FakeWeatherProvider(WeatherObservation(weather_risk_index=0.11))
            ),
            signal_store=MockZoneEnvironmentalSignalStore(
                records={
                    "prime-edge": {
                        "sea_surface_temp_f": 61.1,
                        "temp_gradient_f_per_nm": 0.4,
                        "structure_distance_nm": 2.6,
                        "chlorophyll_mg_m3": 0.27,
                        "current_speed_kts": 1.4,
                        "current_break_index": 0.73,
                        "weather_risk_index": 0.22,
                    }
                }
            ),
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.metadata.weather_source, "processed")

    def test_zone_environmental_input_service_falls_back_when_chlorophyll_provider_fails(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            chlorophyll_source=FallbackChlorophyllSource(
                primary=ChlorophyllBackedSource(
                    FakeChlorophyllProvider(ChlorophyllDataUnavailableError("missing processed chlorophyll"))
                ),
                fallback=SeededChlorophyllSource(signal_store),
            ),
            signal_store=signal_store,
        )

        signals = provider.get_zone_signals(zone, date(2026, 6, 18))
        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(signals.chlorophyll_mg_m3, 0.27)
        self.assertEqual(resolved.metadata.chlorophyll_source, "mock_fallback")

    def test_zone_environmental_input_service_falls_back_when_current_provider_fails(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            current_source=FallbackCurrentSource(
                primary=CurrentBackedSource(
                    FakeCurrentProvider(CurrentDataUnavailableError("missing processed current"))
                ),
                fallback=SeededCurrentSource(signal_store),
            ),
            signal_store=signal_store,
        )

        signals = provider.get_zone_signals(zone, date(2026, 6, 18))
        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(signals.current_speed_kts, 1.4)
        self.assertEqual(signals.current_break_index, 0.73)
        self.assertEqual(resolved.metadata.current_source, "mock_fallback")

    def test_zone_environmental_input_service_falls_back_when_structure_provider_fails(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            bathymetry_source=FallbackBathymetrySource(
                primary=StructureBackedSource(
                    FakeStructureProvider(StructureDataUnavailableError("missing processed structure"))
                ),
                fallback=SeededBathymetrySource(signal_store),
            ),
            signal_store=signal_store,
        )

        signals = provider.get_zone_signals(zone, date(2026, 6, 18))
        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(signals.structure_distance_nm, 2.6)
        self.assertEqual(resolved.metadata.bathymetry_source, "mock_fallback")

    def test_zone_environmental_input_service_falls_back_when_weather_provider_fails(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            weather_source=FallbackWeatherSource(
                primary=WeatherBackedSource(
                    FakeWeatherProvider(WeatherDataUnavailableError("missing processed weather"))
                ),
                fallback=SeededWeatherSource(signal_store),
            ),
            signal_store=signal_store,
        )

        signals = provider.get_zone_signals(zone, date(2026, 6, 18))
        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(signals.weather_risk_index, 0.22)
        self.assertEqual(resolved.metadata.weather_source, "mock_fallback")

    def test_zone_environmental_input_service_exposes_mock_fallback_sst_metadata(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            temperature_source=FallbackTemperatureSource(
                primary=SstBackedTemperatureSource(
                    FakeSstProvider(SstDataUnavailableError("missing processed SST"))
                ),
                fallback=SeededTemperatureSource(signal_store),
            ),
            signal_store=signal_store,
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.metadata.sst_source, "mock_fallback")

    def test_zone_environmental_input_service_falls_back_from_live_sst_to_processed(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            temperature_source=FallbackTemperatureSource(
                primary=SstBackedTemperatureSource(
                    FakeSstProvider(SstDataUnavailableError("live SST timeout"), source_name="live")
                ),
                fallback=FallbackTemperatureSource(
                    primary=SstBackedTemperatureSource(
                        FakeSstProvider(
                            SstObservation(sea_surface_temp_f=68.8, temp_gradient_f_per_nm=1.6),
                            source_name="processed",
                        )
                    ),
                    fallback=SeededTemperatureSource(signal_store),
                ),
            ),
            signal_store=signal_store,
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.signals.sea_surface_temp_f, 68.8)
        self.assertEqual(resolved.signals.temp_gradient_f_per_nm, 1.6)
        self.assertEqual(resolved.metadata.sst_source, "processed")

    def test_zone_environmental_input_service_falls_back_from_live_to_processed_to_mock(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            temperature_source=FallbackTemperatureSource(
                primary=SstBackedTemperatureSource(
                    FakeSstProvider(SstDataUnavailableError("live SST timeout"), source_name="live")
                ),
                fallback=FallbackTemperatureSource(
                    primary=SstBackedTemperatureSource(
                        FakeSstProvider(SstDataUnavailableError("processed SST missing"), source_name="processed")
                    ),
                    fallback=SeededTemperatureSource(signal_store),
                ),
            ),
            signal_store=signal_store,
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.signals.sea_surface_temp_f, 63.5)
        self.assertEqual(resolved.signals.temp_gradient_f_per_nm, 0.9)
        self.assertEqual(resolved.metadata.sst_source, "mock_fallback")

    def test_zone_environmental_input_service_falls_back_when_sst_provider_times_out(self) -> None:
        zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
        signal_store = MockZoneEnvironmentalSignalStore(
            records={
                "prime-edge": {
                    "sea_surface_temp_f": 63.5,
                    "temp_gradient_f_per_nm": 0.9,
                    "structure_distance_nm": 2.6,
                    "chlorophyll_mg_m3": 0.27,
                    "current_speed_kts": 1.4,
                    "current_break_index": 0.73,
                    "weather_risk_index": 0.22,
                }
            }
        )
        provider = ZoneEnvironmentalInputService(
            temperature_source=FallbackTemperatureSource(
                primary=SstBackedTemperatureSource(SlowSstProvider(delay_seconds=0.05)),
                fallback=SeededTemperatureSource(signal_store),
                timeout_seconds=0.01,
            ),
            signal_store=signal_store,
        )

        resolved = provider.resolve_zone_inputs(zone, date(2026, 6, 18))

        self.assertEqual(resolved.signals.sea_surface_temp_f, 63.5)
        self.assertEqual(resolved.signals.temp_gradient_f_per_nm, 0.9)
        self.assertEqual(resolved.metadata.sst_source, "mock_fallback")


if __name__ == "__main__":
    unittest.main()
