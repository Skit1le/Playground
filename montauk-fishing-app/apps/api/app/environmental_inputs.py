from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import date
import logging
from time import perf_counter
from typing import Protocol

from app.chlorophyll_provider import ChlorophyllDataUnavailableError, ChlorophyllProvider
from app.current_provider import CurrentDataUnavailableError, CurrentProvider
from app.db_models import ZoneModel
from app.seed_data import MOCK_ZONE_ENVIRONMENTAL_SIGNALS
from app.structure_provider import StructureDataUnavailableError, StructureProvider
from app.sst_provider import SstDataUnavailableError, SstProvider
from app.weather_provider import WeatherDataUnavailableError, WeatherProvider

logger = logging.getLogger(__name__)
_PROCESSED_LOOKUP_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="env-signal")

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


@dataclass(frozen=True)
class ZoneEnvironmentalSourceMetadata:
    sst_source: str
    chlorophyll_source: str
    current_source: str
    bathymetry_source: str
    weather_source: str


@dataclass(frozen=True)
class ResolvedZoneEnvironmentalInputs:
    signals: ZoneEnvironmentalSignals
    metadata: ZoneEnvironmentalSourceMetadata


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


def _call_with_timeout(callback, timeout_seconds: float):
    if timeout_seconds <= 0:
        return callback()
    future = _PROCESSED_LOOKUP_EXECUTOR.submit(callback)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"Processed lookup exceeded {timeout_seconds:.3f}s.") from exc


class SeededTemperatureSource:
    source_name = "mock"

    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_temperature(self, zone: ZoneModel, trip_date: date) -> TemperatureSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return TemperatureSignals(
            sea_surface_temp_f=signals.sea_surface_temp_f,
            temp_gradient_f_per_nm=signals.temp_gradient_f_per_nm,
        )


class SstBackedTemperatureSource:
    def __init__(self, sst_provider: SstProvider):
        self.sst_provider = sst_provider
        self.source_name = getattr(sst_provider, "source_name", "processed")
        self.last_source_name = self.source_name

    def get_temperature(self, zone: ZoneModel, trip_date: date) -> TemperatureSignals:
        sst = self.sst_provider.get_zone_sst(
            zone_id=zone.id,
            latitude=zone.center_lat,
            longitude=zone.center_lng,
            trip_date=trip_date,
        )
        self.last_source_name = getattr(
            self.sst_provider,
            "last_source_name",
            getattr(self.sst_provider, "source_name", self.source_name),
        )
        return TemperatureSignals(
            sea_surface_temp_f=sst.sea_surface_temp_f,
            temp_gradient_f_per_nm=sst.temp_gradient_f_per_nm,
        )


class FallbackTemperatureSource:
    def __init__(self, primary: TemperatureSource, fallback: TemperatureSource, timeout_seconds: float = 0.75):
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.last_source_name = "mock_fallback"

    def get_temperature(self, zone: ZoneModel, trip_date: date) -> TemperatureSignals:
        try:
            temperature = _call_with_timeout(
                lambda: self.primary.get_temperature(zone, trip_date),
                self.timeout_seconds,
            )
            self.last_source_name = getattr(
                self.primary,
                "last_source_name",
                getattr(self.primary, "source_name", "processed"),
            )
            return temperature
        except TimeoutError:
            logger.warning(
                "SST lookup timed out for zone '%s' on %s. Falling back to lower-priority SST source.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                temperature = self.fallback.get_temperature(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = getattr(
                self.fallback,
                "last_source_name",
                getattr(self.fallback, "source_name", "mock_fallback"),
            )
            return temperature
        except SstDataUnavailableError:
            logger.warning(
                "Falling back to lower-priority SST source for zone '%s' on %s because the primary SST data was unavailable.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                temperature = self.fallback.get_temperature(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = getattr(
                self.fallback,
                "last_source_name",
                getattr(self.fallback, "source_name", "mock_fallback"),
            )
            return temperature
        except Exception:
            logger.exception(
                "Unexpected SST provider failure for zone '%s' on %s. Falling back to lower-priority SST source.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                temperature = self.fallback.get_temperature(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = getattr(
                self.fallback,
                "last_source_name",
                getattr(self.fallback, "source_name", "mock_fallback"),
            )
            return temperature


class SeededBathymetrySource:
    source_name = "mock"

    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_bathymetry(self, zone: ZoneModel, trip_date: date) -> BathymetrySignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return BathymetrySignals(structure_distance_nm=signals.structure_distance_nm)


class StructureBackedSource:
    source_name = "processed"

    def __init__(self, structure_provider: StructureProvider):
        self.structure_provider = structure_provider

    def get_bathymetry(self, zone: ZoneModel, trip_date: date) -> BathymetrySignals:
        observation = self.structure_provider.get_zone_structure(
            zone_id=zone.id,
            latitude=zone.center_lat,
            longitude=zone.center_lng,
            trip_date=trip_date,
        )
        return BathymetrySignals(structure_distance_nm=observation.structure_distance_nm)


class FallbackBathymetrySource:
    def __init__(self, primary: BathymetrySource, fallback: BathymetrySource, timeout_seconds: float = 0.75):
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.last_source_name = "mock_fallback"

    def get_bathymetry(self, zone: ZoneModel, trip_date: date) -> BathymetrySignals:
        try:
            bathymetry = _call_with_timeout(
                lambda: self.primary.get_bathymetry(zone, trip_date),
                self.timeout_seconds,
            )
            self.last_source_name = "processed"
            return bathymetry
        except TimeoutError:
            logger.warning(
                "Processed structure lookup timed out for zone '%s' on %s. Falling back to mock structure signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                bathymetry = self.fallback.get_bathymetry(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return bathymetry
        except StructureDataUnavailableError:
            logger.warning(
                "Falling back to mock structure signals for zone '%s' on %s because live structure data was unavailable.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                bathymetry = self.fallback.get_bathymetry(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return bathymetry
        except Exception:
            logger.exception(
                "Unexpected structure provider failure for zone '%s' on %s. Falling back to mock structure signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                bathymetry = self.fallback.get_bathymetry(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return bathymetry


class SeededChlorophyllSource:
    source_name = "mock"

    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_chlorophyll(self, zone: ZoneModel, trip_date: date) -> ChlorophyllSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return ChlorophyllSignals(chlorophyll_mg_m3=signals.chlorophyll_mg_m3)


class ChlorophyllBackedSource:
    source_name = "processed"

    def __init__(self, chlorophyll_provider: ChlorophyllProvider):
        self.chlorophyll_provider = chlorophyll_provider

    def get_chlorophyll(self, zone: ZoneModel, trip_date: date) -> ChlorophyllSignals:
        observation = self.chlorophyll_provider.get_zone_chlorophyll(
            zone_id=zone.id,
            latitude=zone.center_lat,
            longitude=zone.center_lng,
            trip_date=trip_date,
        )
        return ChlorophyllSignals(chlorophyll_mg_m3=observation.chlorophyll_mg_m3)


class FallbackChlorophyllSource:
    def __init__(self, primary: ChlorophyllSource, fallback: ChlorophyllSource, timeout_seconds: float = 0.75):
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.last_source_name = "mock_fallback"

    def get_chlorophyll(self, zone: ZoneModel, trip_date: date) -> ChlorophyllSignals:
        try:
            chlorophyll = _call_with_timeout(
                lambda: self.primary.get_chlorophyll(zone, trip_date),
                self.timeout_seconds,
            )
            self.last_source_name = "processed"
            return chlorophyll
        except TimeoutError:
            logger.warning(
                "Processed chlorophyll lookup timed out for zone '%s' on %s. Falling back to mock chlorophyll signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                chlorophyll = self.fallback.get_chlorophyll(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return chlorophyll
        except ChlorophyllDataUnavailableError:
            logger.warning(
                "Falling back to mock chlorophyll signals for zone '%s' on %s because live chlorophyll data was unavailable.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                chlorophyll = self.fallback.get_chlorophyll(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return chlorophyll
        except Exception:
            logger.exception(
                "Unexpected chlorophyll provider failure for zone '%s' on %s. Falling back to mock chlorophyll signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                chlorophyll = self.fallback.get_chlorophyll(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return chlorophyll


class SeededCurrentSource:
    source_name = "mock"

    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_current(self, zone: ZoneModel, trip_date: date) -> CurrentSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return CurrentSignals(
            current_speed_kts=signals.current_speed_kts,
            current_break_index=signals.current_break_index,
        )


class CurrentBackedSource:
    source_name = "processed"

    def __init__(self, current_provider: CurrentProvider):
        self.current_provider = current_provider

    def get_current(self, zone: ZoneModel, trip_date: date) -> CurrentSignals:
        observation = self.current_provider.get_zone_current(
            zone_id=zone.id,
            latitude=zone.center_lat,
            longitude=zone.center_lng,
            trip_date=trip_date,
        )
        return CurrentSignals(
            current_speed_kts=observation.current_speed_kts,
            current_break_index=observation.current_break_index,
        )


class FallbackCurrentSource:
    def __init__(self, primary: CurrentSource, fallback: CurrentSource, timeout_seconds: float = 0.75):
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.last_source_name = "mock_fallback"

    def get_current(self, zone: ZoneModel, trip_date: date) -> CurrentSignals:
        try:
            current = _call_with_timeout(
                lambda: self.primary.get_current(zone, trip_date),
                self.timeout_seconds,
            )
            self.last_source_name = "processed"
            return current
        except TimeoutError:
            logger.warning(
                "Processed current lookup timed out for zone '%s' on %s. Falling back to mock current signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                current = self.fallback.get_current(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return current
        except CurrentDataUnavailableError:
            logger.warning(
                "Falling back to mock current signals for zone '%s' on %s because live current data was unavailable.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                current = self.fallback.get_current(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return current
        except Exception:
            logger.exception(
                "Unexpected current provider failure for zone '%s' on %s. Falling back to mock current signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                current = self.fallback.get_current(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return current


class SeededWeatherSource:
    source_name = "mock"

    def __init__(self, signal_store: ZoneEnvironmentalSignalStore):
        self.signal_store = signal_store

    def get_weather(self, zone: ZoneModel, trip_date: date) -> WeatherSignals:
        signals = self.signal_store.get_zone_signals(zone.id, trip_date)
        return WeatherSignals(weather_risk_index=signals.weather_risk_index)


class WeatherBackedSource:
    source_name = "processed"

    def __init__(self, weather_provider: WeatherProvider):
        self.weather_provider = weather_provider

    def get_weather(self, zone: ZoneModel, trip_date: date) -> WeatherSignals:
        observation = self.weather_provider.get_zone_weather(
            zone_id=zone.id,
            latitude=zone.center_lat,
            longitude=zone.center_lng,
            trip_date=trip_date,
        )
        return WeatherSignals(weather_risk_index=observation.weather_risk_index)


class FallbackWeatherSource:
    def __init__(self, primary: WeatherSource, fallback: WeatherSource, timeout_seconds: float = 0.75):
        self.primary = primary
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.last_source_name = "mock_fallback"

    def get_weather(self, zone: ZoneModel, trip_date: date) -> WeatherSignals:
        try:
            weather = _call_with_timeout(
                lambda: self.primary.get_weather(zone, trip_date),
                self.timeout_seconds,
            )
            self.last_source_name = "processed"
            return weather
        except TimeoutError:
            logger.warning(
                "Processed weather lookup timed out for zone '%s' on %s. Falling back to mock weather signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                weather = self.fallback.get_weather(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return weather
        except WeatherDataUnavailableError:
            logger.warning(
                "Falling back to mock weather signals for zone '%s' on %s because live weather data was unavailable.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                weather = self.fallback.get_weather(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return weather
        except Exception:
            logger.exception(
                "Unexpected weather provider failure for zone '%s' on %s. Falling back to mock weather signals.",
                zone.id,
                trip_date.isoformat(),
            )
            try:
                weather = self.fallback.get_weather(zone, trip_date)
            except Exception:
                self.last_source_name = "unavailable"
                raise
            self.last_source_name = "mock_fallback"
            return weather


class ZoneEnvironmentalInputService:
    """Composes zone signals from domain-specific data sources.

    Defaults read SST, chlorophyll, current, structure, and weather through provider-backed
    paths with fallback to the mock signal store. The service can swap in real SST,
    chlorophyll, current, bathymetry, and weather providers one domain at a time without
    changing route handlers or scoring logic.
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
        return self.resolve_zone_inputs(zone, trip_date).signals

    def resolve_zone_inputs(self, zone: ZoneModel, trip_date: date) -> ResolvedZoneEnvironmentalInputs:
        started_at = perf_counter()
        temperature_started = perf_counter()
        temperature = self.temperature_source.get_temperature(zone, trip_date)
        temperature_elapsed_ms = round((perf_counter() - temperature_started) * 1000, 1)

        bathymetry_started = perf_counter()
        bathymetry = self.bathymetry_source.get_bathymetry(zone, trip_date)
        bathymetry_elapsed_ms = round((perf_counter() - bathymetry_started) * 1000, 1)

        chlorophyll_started = perf_counter()
        chlorophyll = self.chlorophyll_source.get_chlorophyll(zone, trip_date)
        chlorophyll_elapsed_ms = round((perf_counter() - chlorophyll_started) * 1000, 1)

        current_started = perf_counter()
        current = self.current_source.get_current(zone, trip_date)
        current_elapsed_ms = round((perf_counter() - current_started) * 1000, 1)

        weather_started = perf_counter()
        weather = self.weather_source.get_weather(zone, trip_date)
        weather_elapsed_ms = round((perf_counter() - weather_started) * 1000, 1)

        total_elapsed_ms = round((perf_counter() - started_at) * 1000, 1)

        metadata = ZoneEnvironmentalSourceMetadata(
            sst_source=getattr(
                self.temperature_source,
                "last_source_name",
                getattr(self.temperature_source, "source_name", "unknown"),
            ),
            chlorophyll_source=getattr(
                self.chlorophyll_source,
                "last_source_name",
                getattr(self.chlorophyll_source, "source_name", "unknown"),
            ),
            current_source=getattr(
                self.current_source,
                "last_source_name",
                getattr(self.current_source, "source_name", "unknown"),
            ),
            bathymetry_source=getattr(
                self.bathymetry_source,
                "last_source_name",
                getattr(self.bathymetry_source, "source_name", "unknown"),
            ),
            weather_source=getattr(
                self.weather_source,
                "last_source_name",
                getattr(self.weather_source, "source_name", "unknown"),
            ),
        )

        logger.info(
            "Resolved zone environmental inputs",
            extra={
                "zone_id": zone.id,
                "trip_date": trip_date.isoformat(),
                "sst_source": metadata.sst_source,
                "chlorophyll_source": metadata.chlorophyll_source,
                "current_source": metadata.current_source,
                "bathymetry_source": metadata.bathymetry_source,
                "weather_source": metadata.weather_source,
                "temperature_elapsed_ms": temperature_elapsed_ms,
                "bathymetry_elapsed_ms": bathymetry_elapsed_ms,
                "chlorophyll_elapsed_ms": chlorophyll_elapsed_ms,
                "current_elapsed_ms": current_elapsed_ms,
                "weather_elapsed_ms": weather_elapsed_ms,
                "total_elapsed_ms": total_elapsed_ms,
            },
        )

        return ResolvedZoneEnvironmentalInputs(
            signals=ZoneEnvironmentalSignals(
                sea_surface_temp_f=temperature.sea_surface_temp_f,
                temp_gradient_f_per_nm=temperature.temp_gradient_f_per_nm,
                structure_distance_nm=bathymetry.structure_distance_nm,
                chlorophyll_mg_m3=chlorophyll.chlorophyll_mg_m3,
                current_speed_kts=current.current_speed_kts,
                current_break_index=current.current_break_index,
                weather_risk_index=weather.weather_risk_index,
            ),
            metadata=metadata,
        )


MockEnvironmentalInputProvider = ZoneEnvironmentalInputService
