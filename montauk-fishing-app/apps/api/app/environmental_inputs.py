from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.db_models import ZoneModel
from app.seed_data import MOCK_ZONE_ENVIRONMENTAL_SIGNALS


@dataclass(frozen=True)
class TemperatureSignals:
    sea_surface_temp_f: float
    temp_gradient_f_per_nm: float


@dataclass(frozen=True)
class BathymetrySignals:
    structure_distance_nm: float


@dataclass(frozen=True)
class ChlorophyllSignals:
    chlorophyll_mg_m3: float


@dataclass(frozen=True)
class CurrentSignals:
    current_speed_kts: float
    current_break_index: float


@dataclass(frozen=True)
class WeatherSignals:
    weather_risk_index: float


@dataclass(frozen=True)
class ZoneEnvironmentalSignals:
    sea_surface_temp_f: float
    temp_gradient_f_per_nm: float
    structure_distance_nm: float
    chlorophyll_mg_m3: float
    current_speed_kts: float
    current_break_index: float
    weather_risk_index: float


class TemperatureSource(Protocol):
    def get_temperature(self, zone: ZoneModel, trip_date: date) -> TemperatureSignals: ...


class BathymetrySource(Protocol):
    def get_bathymetry(self, zone: ZoneModel, trip_date: date) -> BathymetrySignals: ...


class ChlorophyllSource(Protocol):
    def get_chlorophyll(self, zone: ZoneModel, trip_date: date) -> ChlorophyllSignals: ...


class CurrentSource(Protocol):
    def get_current(self, zone: ZoneModel, trip_date: date) -> CurrentSignals: ...


class WeatherSource(Protocol):
    def get_weather(self, zone: ZoneModel, trip_date: date) -> WeatherSignals: ...


class EnvironmentalInputProvider(Protocol):
    def get_zone_signals(self, zone: ZoneModel, trip_date: date) -> ZoneEnvironmentalSignals: ...


class ZoneEnvironmentalSignalsNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class ZoneSignalRecord:
    zone_id: str
    signals: ZoneEnvironmentalSignals


class ZoneEnvironmentalSignalStore(Protocol):
    def get_zone_signals(self, zone_id: str, trip_date: date) -> ZoneEnvironmentalSignals: ...


class MockZoneEnvironmentalSignalStore:
    """Temporary signal store backed by seeded mock values.

    The store is date-aware at the interface level even though the current mock values are not.
    That keeps the zones flow ready for date-specific live products without changing the service
    boundary again.
    """

    def __init__(self, records: dict[str, dict[str, float]] | None = None):
        self.records = records or MOCK_ZONE_ENVIRONMENTAL_SIGNALS

    def get_zone_signals(self, zone_id: str, trip_date: date) -> ZoneEnvironmentalSignals:
        raw_signals = self.records.get(zone_id)
        if raw_signals is None:
            raise ZoneEnvironmentalSignalsNotFoundError(
                f"No environmental signals found for zone '{zone_id}' on {trip_date.isoformat()}."
            )
        return ZoneEnvironmentalSignals(**raw_signals)


class SeededTemperatureSource:
    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_temperature(self, zone: ZoneModel, trip_date: date) -> TemperatureSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return TemperatureSignals(
            sea_surface_temp_f=signals.sea_surface_temp_f,
            temp_gradient_f_per_nm=signals.temp_gradient_f_per_nm,
        )


class SeededBathymetrySource:
    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_bathymetry(self, zone: ZoneModel, trip_date: date) -> BathymetrySignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return BathymetrySignals(structure_distance_nm=signals.structure_distance_nm)


class SeededChlorophyllSource:
    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_chlorophyll(self, zone: ZoneModel, trip_date: date) -> ChlorophyllSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return ChlorophyllSignals(chlorophyll_mg_m3=signals.chlorophyll_mg_m3)


class SeededCurrentSource:
    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_current(self, zone: ZoneModel, trip_date: date) -> CurrentSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return CurrentSignals(
            current_speed_kts=signals.current_speed_kts,
            current_break_index=signals.current_break_index,
        )


class SeededWeatherSource:
    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_weather(self, zone: ZoneModel, trip_date: date) -> WeatherSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return WeatherSignals(weather_risk_index=signals.weather_risk_index)


class ZoneEnvironmentalInputService:
    """Composes zone signals from domain-specific data sources.

    Defaults still read seeded placeholder values from the `zones` table, but the service
    can now swap in real SST, chlorophyll, current, bathymetry, and weather providers one
    domain at a time without changing route handlers or scoring logic.
    """

    def __init__(
        self,
        temperature_source: TemperatureSource | None = None,
        bathymetry_source: BathymetrySource | None = None,
        chlorophyll_source: ChlorophyllSource | None = None,
        current_source: CurrentSource | None = None,
        weather_source: WeatherSource | None = None,
        signal_store: ZoneEnvironmentalSignalStore | None = None,
    ):
        signal_store = signal_store or MockZoneEnvironmentalSignalStore()
        self.temperature_source = temperature_source or SeededTemperatureSource(signal_store)
        self.bathymetry_source = bathymetry_source or SeededBathymetrySource(signal_store)
        self.chlorophyll_source = chlorophyll_source or SeededChlorophyllSource(signal_store)
        self.current_source = current_source or SeededCurrentSource(signal_store)
        self.weather_source = weather_source or SeededWeatherSource(signal_store)

    def get_zone_signals(self, zone: ZoneModel, trip_date: date) -> ZoneEnvironmentalSignals:
        temperature = self.temperature_source.get_temperature(zone, trip_date)
        bathymetry = self.bathymetry_source.get_bathymetry(zone, trip_date)
        chlorophyll = self.chlorophyll_source.get_chlorophyll(zone, trip_date)
        current = self.current_source.get_current(zone, trip_date)
        weather = self.weather_source.get_weather(zone, trip_date)

        return ZoneEnvironmentalSignals(
            sea_surface_temp_f=temperature.sea_surface_temp_f,
            temp_gradient_f_per_nm=temperature.temp_gradient_f_per_nm,
            structure_distance_nm=bathymetry.structure_distance_nm,
            chlorophyll_mg_m3=chlorophyll.chlorophyll_mg_m3,
            current_speed_kts=current.current_speed_kts,
            current_break_index=current.current_break_index,
            weather_risk_index=weather.weather_risk_index,
        )


MockEnvironmentalInputProvider = ZoneEnvironmentalInputService
