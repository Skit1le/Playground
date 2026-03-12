from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.db_models import ZoneModel


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


class SeededTemperatureSource:
    def get_temperature(self, zone: ZoneModel, trip_date: date) -> TemperatureSignals:
        return TemperatureSignals(
            sea_surface_temp_f=zone.sea_surface_temp_f,
            temp_gradient_f_per_nm=zone.temp_gradient_f_per_nm,
        )


class SeededBathymetrySource:
    def get_bathymetry(self, zone: ZoneModel, trip_date: date) -> BathymetrySignals:
        return BathymetrySignals(structure_distance_nm=zone.structure_distance_nm)


class SeededChlorophyllSource:
    def get_chlorophyll(self, zone: ZoneModel, trip_date: date) -> ChlorophyllSignals:
        return ChlorophyllSignals(chlorophyll_mg_m3=zone.chlorophyll_mg_m3)


class SeededCurrentSource:
    def get_current(self, zone: ZoneModel, trip_date: date) -> CurrentSignals:
        return CurrentSignals(
            current_speed_kts=zone.current_speed_kts,
            current_break_index=zone.current_break_index,
        )


class SeededWeatherSource:
    def get_weather(self, zone: ZoneModel, trip_date: date) -> WeatherSignals:
        return WeatherSignals(weather_risk_index=zone.weather_risk_index)


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
    ):
        self.temperature_source = temperature_source or SeededTemperatureSource()
        self.bathymetry_source = bathymetry_source or SeededBathymetrySource()
        self.chlorophyll_source = chlorophyll_source or SeededChlorophyllSource()
        self.current_source = current_source or SeededCurrentSource()
        self.weather_source = weather_source or SeededWeatherSource()

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
