import unittest
from datetime import date

from app.db_models import SpeciesScoringConfigModel
from app.environmental_inputs import ZoneEnvironmentalSignals
from app.scoring import ZoneScoringEngine, build_temp_break_config


def make_config(species: str) -> SpeciesScoringConfigModel:
    return SpeciesScoringConfigModel(
        species=species,
        label=f"{species.title()} Test",
        season_window="June-October",
        notes="test",
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


def make_signals(distance_nm: float | None) -> ZoneEnvironmentalSignals:
    return ZoneEnvironmentalSignals(
        sea_surface_temp_f=66.0,
        temp_gradient_f_per_nm=1.8,
        structure_distance_nm=1.8,
        chlorophyll_mg_m3=0.28,
        current_speed_kts=1.5,
        current_break_index=0.82,
        weather_risk_index=0.18,
        nearest_strong_break_distance_nm=distance_nm,
        nearest_strong_chl_break_distance_nm=distance_nm,
    )


class ScoringTestCase(unittest.TestCase):
    def test_species_specific_temp_break_config_is_exposed(self) -> None:
        bluefin = build_temp_break_config("bluefin")
        yellowfin = build_temp_break_config("yellowfin")
        mahi = build_temp_break_config("mahi")

        self.assertGreater(bluefin.strong_break_threshold_f_per_nm, yellowfin.strong_break_threshold_f_per_nm)
        self.assertLess(bluefin.full_score_distance_nm, yellowfin.full_score_distance_nm)
        self.assertLess(mahi.factor_weight, yellowfin.factor_weight)

    def test_same_break_distance_scores_differently_by_species(self) -> None:
        engine = ZoneScoringEngine()
        trip_date = date(2026, 6, 18)
        signals = make_signals(2.5)

        bluefin_result = engine.score(signals, make_config("bluefin"), trip_date)
        yellowfin_result = engine.score(signals, make_config("yellowfin"), trip_date)
        mahi_result = engine.score(signals, make_config("mahi"), trip_date)

        self.assertLess(bluefin_result.breakdown.temp_break_proximity, yellowfin_result.breakdown.temp_break_proximity)
        self.assertEqual(yellowfin_result.breakdown.temp_break_proximity, 100.0)
        self.assertEqual(mahi_result.breakdown.temp_break_proximity, 100.0)

    def test_far_breaks_decay_more_aggressively_for_bluefin_than_yellowfin(self) -> None:
        engine = ZoneScoringEngine()
        trip_date = date(2026, 6, 18)
        signals = make_signals(15.0)

        bluefin_result = engine.score(signals, make_config("bluefin"), trip_date)
        yellowfin_result = engine.score(signals, make_config("yellowfin"), trip_date)

        self.assertEqual(bluefin_result.breakdown.temp_break_proximity, 0.0)
        self.assertGreater(yellowfin_result.breakdown.temp_break_proximity, 0.0)

    def test_same_chlorophyll_break_distance_scores_differently_by_species(self) -> None:
        engine = ZoneScoringEngine()
        trip_date = date(2026, 6, 18)
        signals = make_signals(3.0)

        bluefin_result = engine.score(signals, make_config("bluefin"), trip_date)
        yellowfin_result = engine.score(signals, make_config("yellowfin"), trip_date)
        mahi_result = engine.score(signals, make_config("mahi"), trip_date)

        self.assertLess(
            bluefin_result.breakdown.chlorophyll_break_proximity,
            yellowfin_result.breakdown.chlorophyll_break_proximity,
        )
        self.assertGreaterEqual(
            mahi_result.breakdown.chlorophyll_break_proximity,
            bluefin_result.breakdown.chlorophyll_break_proximity,
        )

    def test_edge_alignment_rewards_overlap_more_than_single_edge(self) -> None:
        engine = ZoneScoringEngine()
        config = make_config("yellowfin")
        trip_date = date(2026, 6, 18)

        both_edges = engine.score(
            make_signals(3.0),
            config,
            trip_date,
        )
        only_temp_edge = engine.score(
            ZoneEnvironmentalSignals(
                sea_surface_temp_f=66.0,
                temp_gradient_f_per_nm=1.8,
                structure_distance_nm=1.8,
                chlorophyll_mg_m3=0.28,
                current_speed_kts=1.5,
                current_break_index=0.82,
                weather_risk_index=0.18,
                nearest_strong_break_distance_nm=3.0,
                nearest_strong_chl_break_distance_nm=30.0,
            ),
            config,
            trip_date,
        )
        far_from_both = engine.score(
            make_signals(30.0),
            config,
            trip_date,
        )

        self.assertGreater(both_edges.breakdown.edge_alignment, only_temp_edge.breakdown.edge_alignment)
        self.assertEqual(far_from_both.breakdown.edge_alignment, 0.0)


if __name__ == "__main__":
    unittest.main()
