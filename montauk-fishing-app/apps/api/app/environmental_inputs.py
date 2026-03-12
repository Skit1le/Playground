from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.db_models import ZoneModel


@dataclass(frozen=True)
class ZoneEnvironmentalSignals:
    sea_surface_temp_f: float
    temp_gradient_f_per_nm: float
    structure_distance_nm: float
    chlorophyll_mg_m3: float
    current_speed_kts: float
    current_break_index: float
    weather_risk_index: float


class EnvironmentalInputProvider(Protocol):
    def get_zone_signals(self, zone: ZoneModel, trip_date: date) -> ZoneEnvironmentalSignals: ...


class MockEnvironmentalInputProvider:
    """Temporary provider that reads placeholder environmental signals from seeded zone rows.

    This keeps the scoring pipeline stable while SST, chlorophyll, structure, current,
    and weather feeds are still mocked. Later we can replace this class with a provider
    that reads ingested products or model outputs without changing the route contract.
    """

    def get_zone_signals(self, zone: ZoneModel, trip_date: date) -> ZoneEnvironmentalSignals:
        return ZoneEnvironmentalSignals(
            sea_surface_temp_f=zone.sea_surface_temp_f,
            temp_gradient_f_per_nm=zone.temp_gradient_f_per_nm,
            structure_distance_nm=zone.structure_distance_nm,
            chlorophyll_mg_m3=zone.chlorophyll_mg_m3,
            current_speed_kts=zone.current_speed_kts,
            current_break_index=zone.current_break_index,
            weather_risk_index=zone.weather_risk_index,
        )
