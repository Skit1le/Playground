import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.chlorophyll_provider import (
    CachedChlorophyllSnapshotAdapter,
    ChlorophyllObservation,
    ChlorophyllPoint,
)
from app.environmental_inputs import ChlorophyllBackedSource, MockZoneEnvironmentalSignalStore, ZoneEnvironmentalInputService
from app.services.chlorophyll_cache import ChlorophyllCacheService, ChlorophyllCacheWarmRequest
from app.services.chlorophyll_map import ChlorophyllBreakMapService
from app.services.zones import ZonesService
from tests.test_zones_service import (
    FakeChlorophyllProvider,
    FakeSpeciesConfigRepository,
    FakeZoneRepository,
    make_species_config,
    make_zone,
)


class ChlorophyllCacheServiceTestCase(unittest.TestCase):
    def test_successful_cache_warm_writes_snapshot_and_inspection_lists_it(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as temp_dir:
            live_provider = FakeChlorophyllProvider(
                ChlorophyllObservation(chlorophyll_mg_m3=0.29),
                points=(
                    ChlorophyllPoint(latitude=40.95, longitude=-71.88, chlorophyll_mg_m3=0.26),
                    ChlorophyllPoint(latitude=40.92, longitude=-71.82, chlorophyll_mg_m3=0.31),
                ),
                source_name="live",
            )
            live_provider.last_dataset_id = "live-dataset"
            live_provider.last_resolved_timestamp = "2026-06-18T12:00:00Z"
            cache_adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
            )
            service = ChlorophyllCacheService(
                cache_adapter=cache_adapter,
                live_provider=live_provider,
                processed_provider=live_provider,
            )

            response = service.warm_cache(
                ChlorophyllCacheWarmRequest(
                    requested_dates=(date(2026, 6, 18),),
                    bboxes=((-72.4, 39.8, -69.8, 41.4),),
                    mode="live",
                )
            )
            inspection = service.inspect_cache()

            self.assertEqual(response.warmed_count, 1)
            self.assertEqual(response.failed_count, 0)
            self.assertEqual(inspection.entry_count, 2)
            self.assertEqual(inspection.entries[0].dataset_id, "live-dataset")

    def test_warmed_cache_is_reused_for_chlorophyll_map(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as temp_dir:
            live_provider = FakeChlorophyllProvider(
                ChlorophyllObservation(chlorophyll_mg_m3=0.29),
                points=(
                    ChlorophyllPoint(latitude=40.95, longitude=-71.88, chlorophyll_mg_m3=0.26),
                    ChlorophyllPoint(latitude=40.92, longitude=-71.82, chlorophyll_mg_m3=0.31),
                ),
                source_name="live",
            )
            cache_adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
            )
            service = ChlorophyllCacheService(
                cache_adapter=cache_adapter,
                live_provider=live_provider,
                processed_provider=live_provider,
            )
            service.warm_cache(
                ChlorophyllCacheWarmRequest(
                    requested_dates=(date(2026, 6, 18),),
                    bboxes=((-72.4, 39.8, -69.8, 41.4),),
                    mode="live",
                )
            )
            map_service = ChlorophyllBreakMapService(cache_adapter, target_cells=36)

            response = map_service.get_chlorophyll_break_map(
                trip_date=date(2026, 6, 18),
                bbox=(-72.4, 39.8, -69.8, 41.4),
            )

            self.assertEqual(response.metadata.source, "cached_real")
            self.assertEqual(response.metadata.source_status, "cached")
            self.assertTrue(response.metadata.fallback_used)

    def test_zones_reflect_cached_real_after_warming(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as temp_dir:
            live_provider = FakeChlorophyllProvider(
                ChlorophyllObservation(chlorophyll_mg_m3=0.29),
                points=(
                    ChlorophyllPoint(latitude=40.95, longitude=-71.88, chlorophyll_mg_m3=0.26),
                    ChlorophyllPoint(latitude=40.92, longitude=-71.82, chlorophyll_mg_m3=0.31),
                ),
                source_name="live",
            )
            cache_adapter = CachedChlorophyllSnapshotAdapter(
                cache_dir=temp_dir,
                min_lat=39.8,
                max_lat=41.4,
                min_lon=-72.4,
                max_lon=-69.8,
            )
            ChlorophyllCacheService(
                cache_adapter=cache_adapter,
                live_provider=live_provider,
                processed_provider=live_provider,
            ).warm_cache(
                ChlorophyllCacheWarmRequest(
                    requested_dates=(date(2026, 6, 18),),
                    bboxes=((-72.4, 39.8, -69.8, 41.4),),
                    mode="live",
                )
            )
            zone = make_zone(zone_id="prime-edge", name="Prime Edge", distance_nm=61)
            zones_service = ZonesService(
                zone_repository=FakeZoneRepository([zone]),
                species_config_repository=FakeSpeciesConfigRepository(make_species_config()),
                environmental_input_provider=ZoneEnvironmentalInputService(
                    chlorophyll_source=ChlorophyllBackedSource(cache_adapter),
                    signal_store=MockZoneEnvironmentalSignalStore(
                        records={
                            "prime-edge": {
                                "sea_surface_temp_f": 64.2,
                                "temp_gradient_f_per_nm": 1.1,
                                "structure_distance_nm": 2.1,
                                "chlorophyll_mg_m3": 0.29,
                                "current_speed_kts": 1.3,
                                "current_break_index": 0.7,
                                "weather_risk_index": 0.18,
                            }
                        }
                    ),
                ),
            )

            ranked_zone = zones_service.list_ranked_zones("bluefin", date(2026, 6, 18), limit=10)[0]

            self.assertEqual(ranked_zone.source_metadata.chlorophyll.source, "cached_real")
            self.assertEqual(ranked_zone.source_metadata.chlorophyll.source_status, "cached")


if __name__ == "__main__":
    unittest.main()
