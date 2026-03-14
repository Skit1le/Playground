"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type KeyboardEvent } from "react";
import {
  buildApiTimeoutMessage,
  buildApiUnavailableMessage,
  buildLayerStatusMessage,
  clearRequestFailure,
  formatBboxParam,
  getRequestFailureState,
  isApiUnavailableMessage,
  rememberRequestFailure,
  normalizeZoneExplanation,
  type MapBbox,
} from "./dashboardUtils";
import styles from "./page.module.css";

const OffshoreMap = dynamic(() => import("./OffshoreMap"), {
  ssr: false,
});

type Zone = {
  id: string;
  name: string;
  species: string[];
  distance_nm: number;
  center: { lat: number; lng: number };
  scored_for_species: string;
  scored_for_date: string;
  score: number;
  sea_surface_temp_f: number;
  temp_gradient_f_per_nm: number;
  nearest_strong_break_distance_nm?: number | null;
  structure_distance_nm: number;
  chlorophyll_mg_m3: number;
  nearest_strong_chl_break_distance_nm?: number | null;
  current_speed_kts: number;
  current_break_index: number;
  weather_risk_index: number;
  score_breakdown: Record<string, number>;
  score_weights: Record<string, number>;
  weighted_score_breakdown: Record<string, number>;
  score_explanation?: {
    headline: string;
    summary: string;
    best_use_case_summary: string;
    confidence_score: number;
    watchouts: string[];
    top_reasons: string[];
    factors: Array<{
      factor: string;
      label: string;
      raw_value: string;
      score: number;
      weighted_contribution: number;
      reason: string;
    }>;
  };
  source_metadata?: {
    sst: {
      source: string;
      source_status: string;
      live_data_available: boolean;
      fallback_used: boolean;
      dataset_id?: string | null;
      failure_reason?: string | null;
      warning_messages?: string[] | null;
    };
    chlorophyll: {
      source: string;
      source_status: string;
      live_data_available: boolean;
      fallback_used: boolean;
      dataset_id?: string | null;
      failure_reason?: string | null;
      warning_messages?: string[] | null;
    };
    current: {
      source: string;
      source_status: string;
      live_data_available: boolean;
      fallback_used: boolean;
      warning_messages?: string[] | null;
    };
    bathymetry: {
      source: string;
      source_status: string;
      live_data_available: boolean;
      fallback_used: boolean;
      warning_messages?: string[] | null;
    };
    weather: {
      source: string;
      source_status: string;
      live_data_available: boolean;
      fallback_used: boolean;
      warning_messages?: string[] | null;
    };
    live_data_available: boolean;
    fallback_used: boolean;
    warning_messages?: string[] | null;
  };
  depth_ft: number;
  summary: string;
};

type TripLog = {
  id: string;
  date: string;
  zone_id: string;
  species: string[];
  vessel: string;
  catch_count: number;
  notes: string;
};

type SpeciesConfig = {
  species: string;
  label: string;
  season_window: string;
  preferred_temp_f: number[];
  notes: string;
  temp_break_config?: {
    strong_break_threshold_f_per_nm: number;
    full_score_distance_nm: number;
    zero_score_distance_nm: number;
    factor_weight: number;
  } | null;
  chlorophyll_break_config?: {
    strong_break_threshold_mg_m3_per_nm: number;
    full_score_distance_nm: number;
    zero_score_distance_nm: number;
    factor_weight: number;
  } | null;
  weights?: Record<string, number>;
};

type HealthResponse = {
  status: string;
  app: string;
  environment: string;
  database: string;
};

type SstMapFeature = {
  type: "Feature";
  geometry: {
    type: "Polygon";
    coordinates: [Array<[number, number]>];
  };
  properties: {
    sea_surface_temp_f: number;
    break_intensity_f_per_nm: number;
  };
};

type SstMapResponse = {
  metadata: {
    date: string;
    bbox: [number, number, number, number];
    source: "live" | "processed" | "mock_fallback" | "unavailable" | string;
    source_status?: string;
    live_data_available?: boolean;
    fallback_used?: boolean;
    provider_name?: string | null;
    dataset_id?: string | null;
    requested_date?: string | null;
    resolved_data_timestamp?: string | null;
    units: "fahrenheit";
    point_count: number;
    cell_count: number;
    temp_range_f: [number, number] | null;
    break_intensity_range?: [number, number] | null;
    grid_resolution?: [number, number] | null;
    failure_reason?: string | null;
    warning_messages?: string[] | null;
  };
  data: {
    type: "FeatureCollection";
    features: SstMapFeature[];
  };
};

type ChlorophyllBreakMapFeature = {
  type: "Feature";
  geometry: {
    type: "Polygon";
    coordinates: [Array<[number, number]>];
  };
  properties: {
    chlorophyll_mg_m3: number;
    break_intensity_mg_m3_per_nm: number;
  };
};

type ChlorophyllBreakMapResponse = {
  metadata: {
    date: string;
    bbox: [number, number, number, number];
    source: string;
    source_status?: string;
    live_data_available?: boolean;
    fallback_used?: boolean;
    provider_name?: string | null;
    dataset_id?: string | null;
    requested_date?: string | null;
    resolved_data_timestamp?: string | null;
    units: "mg_m3";
    point_count: number;
    cell_count: number;
    chlorophyll_range_mg_m3?: [number, number] | null;
    break_intensity_range_mg_m3_per_nm?: [number, number] | null;
    grid_resolution?: [number, number] | null;
    failure_reason?: string | null;
    warning_messages?: string[] | null;
  };
  data: {
    type: "FeatureCollection";
    features: ChlorophyllBreakMapFeature[];
  };
};

const DEFAULT_ISO_DATE = "2026-03-11";
const DEFAULT_SPECIES = "bluefin";
const DEFAULT_MAP_BBOX: MapBbox = [-72.28, 40.62, -71.02, 41.18];
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const DEFAULT_REQUEST_TIMEOUT_MS = 4000;
const ZONES_REQUEST_TIMEOUT_MS = 9000;
const OVERLAY_REFRESH_DEBOUNCE_MS = 180;
const RECOVERY_HEALTHCHECK_INTERVAL_MS = 5000;
const DEFAULT_SPECIES_CONFIGS: SpeciesConfig[] = [
  {
    species: "bluefin",
    label: "Bluefin Tuna",
    season_window: "May-November",
    preferred_temp_f: [58.0, 66.0],
    notes: "Seeded local fallback used when the API species-config endpoint is unavailable.",
  },
  {
    species: "yellowfin",
    label: "Yellowfin Tuna",
    season_window: "July-October",
    preferred_temp_f: [67.0, 74.0],
    notes: "Seeded local fallback used when the API species-config endpoint is unavailable.",
  },
  {
    species: "mahi",
    label: "Mahi",
    season_window: "June-September",
    preferred_temp_f: [70.0, 78.0],
    notes: "Seeded local fallback used when the API species-config endpoint is unavailable.",
  },
];

function formatDisplayDate(date: Date): string {
  const month = `${date.getUTCMonth() + 1}`.padStart(2, "0");
  const day = `${date.getUTCDate()}`.padStart(2, "0");
  const year = date.getUTCFullYear();
  return `${month}/${day}/${year}`;
}

function toApiDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function parseDisplayDate(displayDate: string): Date | null {
  const match = displayDate.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!match) {
    return null;
  }

  const [, month, day, year] = match;
  const monthNumber = Number(month);
  const dayNumber = Number(day);
  const yearNumber = Number(year);
  const parsedDate = new Date(Date.UTC(yearNumber, monthNumber - 1, dayNumber));

  if (
    Number.isNaN(parsedDate.getTime()) ||
    parsedDate.getUTCFullYear() !== yearNumber ||
    parsedDate.getUTCMonth() !== monthNumber - 1 ||
    parsedDate.getUTCDate() !== dayNumber
  ) {
    return null;
  }

  return parsedDate;
}

function buildEmptySstMapResponse(apiDate: string, bbox: MapBbox): SstMapResponse {
  return {
    metadata: {
      date: apiDate,
      bbox,
      source: "unavailable",
      units: "fahrenheit",
      point_count: 0,
      cell_count: 0,
      temp_range_f: null,
      break_intensity_range: null,
    },
    data: {
      type: "FeatureCollection",
      features: [],
    },
  };
}

function buildEmptyChlorophyllBreakMapResponse(apiDate: string, bbox: MapBbox): ChlorophyllBreakMapResponse {
  return {
    metadata: {
      date: apiDate,
      bbox,
      source: "unavailable",
      units: "mg_m3",
      point_count: 0,
      cell_count: 0,
      chlorophyll_range_mg_m3: null,
      break_intensity_range_mg_m3_per_nm: null,
    },
    data: {
      type: "FeatureCollection",
      features: [],
    },
  };
}

async function fetchApi<T>(
  path: string,
  options?: {
    signal?: AbortSignal;
    timeoutMs?: number;
  },
): Promise<T> {
  const controller = new AbortController();
  const timeoutMs = options?.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  options?.signal?.addEventListener("abort", onAbort);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") {
      if (options?.signal?.aborted) {
        throw error;
      }
      throw new Error(buildApiTimeoutMessage(path, timeoutMs, API_BASE_URL));
    }
    throw new Error(buildApiUnavailableMessage(path, API_BASE_URL));
  } finally {
    window.clearTimeout(timeoutId);
    options?.signal?.removeEventListener("abort", onAbort);
  }

  if (!response.ok) {
    throw new Error(`API request failed (${response.status}) for ${path}`);
  }

  return response.json() as Promise<T>;
}

export default function HomeDashboard() {
  const initialDate = new Date(`${DEFAULT_ISO_DATE}T00:00:00.000Z`);

  const [selectedSpecies, setSelectedSpecies] = useState(DEFAULT_SPECIES);
  const [selectedDate, setSelectedDate] = useState(initialDate);
  const [displayDate, setDisplayDate] = useState(formatDisplayDate(initialDate));
  const [dateError, setDateError] = useState<string | null>(null);

  const [zones, setZones] = useState<Zone[]>([]);
  const [tripLogs, setTripLogs] = useState<TripLog[]>([]);
  const [speciesConfigs, setSpeciesConfigs] = useState<SpeciesConfig[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [sstMapData, setSstMapData] = useState<SstMapResponse | null>(null);
  const [chlorophyllBreakMapData, setChlorophyllBreakMapData] = useState<ChlorophyllBreakMapResponse | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);

  const [isZonesLoading, setIsZonesLoading] = useState(true);
  const [isSstMapLoading, setIsSstMapLoading] = useState(true);
  const [isChlBreakMapLoading, setIsChlBreakMapLoading] = useState(true);
  const [zonesError, setZonesError] = useState<string | null>(null);
  const [sstMapError, setSstMapError] = useState<string | null>(null);
  const [chlorophyllBreakMapError, setChlorophyllBreakMapError] = useState<string | null>(null);
  const [supportingError, setSupportingError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const apiDate = toApiDate(selectedDate);
  const mapRequestBbox = DEFAULT_MAP_BBOX;
  const bboxParam = useMemo(() => formatBboxParam(mapRequestBbox), [mapRequestBbox]);
  const requestBbox = useMemo(() => bboxParam.split(",").map((value) => Number(value)) as MapBbox, [bboxParam]);
  const zonesRequestKey = useMemo(() => `zones:${apiDate}:${selectedSpecies}`, [apiDate, selectedSpecies]);
  const sstRequestKey = useMemo(() => `sst:${apiDate}:${bboxParam}`, [apiDate, bboxParam]);
  const chlorophyllRequestKey = useMemo(() => `chlorophyll-breaks:${apiDate}:${bboxParam}`, [apiDate, bboxParam]);

  const handleRetryRequests = useCallback(() => {
    clearRequestFailure(zonesRequestKey);
    clearRequestFailure(sstRequestKey);
    clearRequestFailure(chlorophyllRequestKey);
    setReloadToken((current) => current + 1);
  }, [chlorophyllRequestKey, sstRequestKey, zonesRequestKey]);

  useEffect(() => {
    let isActive = true;

    Promise.allSettled([
      fetchApi<TripLog[]>("/trip-logs"),
      fetchApi<SpeciesConfig[]>("/configs/species"),
      fetchApi<HealthResponse>("/health"),
    ]).then((results) => {
      if (!isActive) {
        return;
      }

      const [tripLogsResult, speciesConfigsResult, healthResult] = results;
      const errors: string[] = [];

      if (tripLogsResult.status === "fulfilled") {
        setTripLogs(tripLogsResult.value);
      } else {
        errors.push(
          tripLogsResult.reason instanceof Error
            ? tripLogsResult.reason.message
            : "Failed to load trip logs.",
        );
        setTripLogs([]);
      }

      if (speciesConfigsResult.status === "fulfilled") {
        setSpeciesConfigs(speciesConfigsResult.value);
      } else {
        errors.push(
          speciesConfigsResult.reason instanceof Error
            ? speciesConfigsResult.reason.message
            : "Failed to load species config.",
        );
        setSpeciesConfigs(DEFAULT_SPECIES_CONFIGS);
      }

      if (healthResult.status === "fulfilled") {
        setHealth(healthResult.value);
      } else {
        errors.push(
          healthResult.reason instanceof Error
            ? healthResult.reason.message
            : "Failed to load API health status.",
        );
        if (!isActive) {
          return;
        }
        setHealth({
          status: "unavailable",
          app: "API unavailable",
          environment: "local dev",
          database: "unknown",
        });
      }

      setSupportingError(errors.length > 0 ? errors.join(" ") : null);
    });

    return () => {
      isActive = false;
    };
  }, [reloadToken]);

  useEffect(() => {
    const priorFailure = getRequestFailureState(zonesRequestKey);
    if (priorFailure) {
      setIsZonesLoading(false);
      setZonesError(priorFailure.message);
      return;
    }

    const controller = new AbortController();
    setIsZonesLoading(true);
    setZonesError(null);

    fetchApi<Zone[]>(`/zones?date=${apiDate}&species=${selectedSpecies}`, {
      signal: controller.signal,
      timeoutMs: ZONES_REQUEST_TIMEOUT_MS,
    })
      .then((zoneResponse) => {
        clearRequestFailure(zonesRequestKey);
        setZones(zoneResponse);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const message =
          error instanceof Error
            ? error.message
            : `Zone rankings unavailable because the API at ${API_BASE_URL} could not be reached.`;
        setZones([]);
        setZonesError(message);
        rememberRequestFailure(zonesRequestKey, message);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsZonesLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [apiDate, selectedSpecies, zonesRequestKey, reloadToken]);

  useEffect(() => {
    const priorFailure = getRequestFailureState(sstRequestKey);
    if (priorFailure) {
      setIsSstMapLoading(false);
      setSstMapError(priorFailure.message);
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      setIsSstMapLoading(true);
      setSstMapError(null);

      fetchApi<SstMapResponse>(`/map/sst?date=${apiDate}&bbox=${encodeURIComponent(bboxParam)}`, {
        signal: controller.signal,
        timeoutMs: 5000,
      })
        .then((response) => {
          clearRequestFailure(sstRequestKey);
          setSstMapData(response);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          const message =
            error instanceof Error
              ? error.message
              : `SST overlay unavailable because the API at ${API_BASE_URL} could not be reached.`;
          setSstMapData(buildEmptySstMapResponse(apiDate, requestBbox));
          setSstMapError(message);
          rememberRequestFailure(sstRequestKey, message);
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setIsSstMapLoading(false);
          }
        });
    }, OVERLAY_REFRESH_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [apiDate, bboxParam, requestBbox, sstRequestKey, reloadToken]);

  useEffect(() => {
    const priorFailure = getRequestFailureState(chlorophyllRequestKey);
    if (priorFailure) {
      setIsChlBreakMapLoading(false);
      setChlorophyllBreakMapError(priorFailure.message);
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      setIsChlBreakMapLoading(true);
      setChlorophyllBreakMapError(null);

      fetchApi<ChlorophyllBreakMapResponse>(
        `/map/chlorophyll-breaks?date=${apiDate}&bbox=${encodeURIComponent(bboxParam)}`,
        {
          signal: controller.signal,
          timeoutMs: 5000,
        },
      )
        .then((response) => {
          clearRequestFailure(chlorophyllRequestKey);
          setChlorophyllBreakMapData(response);
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          const message =
            error instanceof Error
              ? error.message
              : `Chlorophyll break overlay unavailable because the API at ${API_BASE_URL} could not be reached.`;
          setChlorophyllBreakMapData(buildEmptyChlorophyllBreakMapResponse(apiDate, requestBbox));
          setChlorophyllBreakMapError(message);
          rememberRequestFailure(chlorophyllRequestKey, message);
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setIsChlBreakMapLoading(false);
          }
        });
    }, OVERLAY_REFRESH_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [apiDate, bboxParam, chlorophyllRequestKey, requestBbox, reloadToken]);

  const topZone = zones[0] ?? null;
  const selectedZone = zones.find((zone) => zone.id === selectedZoneId) ?? topZone;
  const selectedZoneExplanation = selectedZone
    ? normalizeZoneExplanation(selectedZone.score_explanation, selectedZone)
    : null;
  const selectedZoneSourceWarnings = selectedZone?.source_metadata?.warning_messages ?? [];
  const sourceWarnings = useMemo(() => {
    const warnings = [
      buildLayerStatusMessage("SST", sstMapData?.metadata),
      buildLayerStatusMessage("chlorophyll", chlorophyllBreakMapData?.metadata),
    ].filter((warning): warning is string => Boolean(warning));
    return Array.from(new Set(warnings));
  }, [chlorophyllBreakMapData, sstMapData]);
  const hasUnavailableRequestError = useMemo(
    () =>
      [zonesError, sstMapError, chlorophyllBreakMapError, supportingError].some((message) =>
        isApiUnavailableMessage(message),
      ),
    [chlorophyllBreakMapError, sstMapError, supportingError, zonesError],
  );

  useEffect(() => {
    if (!hasUnavailableRequestError) {
      return;
    }

    let isActive = true;
    const intervalId = window.setInterval(() => {
      fetchApi<HealthResponse>("/health", { timeoutMs: 2000 })
        .then((response) => {
          if (!isActive) {
            return;
          }
          setHealth(response);
          clearRequestFailure(zonesRequestKey);
          clearRequestFailure(sstRequestKey);
          clearRequestFailure(chlorophyllRequestKey);
          setZonesError(null);
          setSstMapError(null);
          setChlorophyllBreakMapError(null);
          setSupportingError(null);
          setReloadToken((current) => current + 1);
        })
        .catch(() => {
          // Keep the current passive error state until the API recovers.
        });
    }, RECOVERY_HEALTHCHECK_INTERVAL_MS);

    return () => {
      isActive = false;
      window.clearInterval(intervalId);
    };
  }, [chlorophyllRequestKey, hasUnavailableRequestError, sstRequestKey, zonesRequestKey]);

  useEffect(() => {
    if (zones.length === 0) {
      setSelectedZoneId(null);
      return;
    }
    if (selectedZoneId && zones.some((zone) => zone.id === selectedZoneId)) {
      return;
    }
    setSelectedZoneId(zones[0]?.id ?? null);
  }, [selectedZoneId, zones]);

  function handleSpeciesChange(event: ChangeEvent<HTMLSelectElement>) {
    setSelectedSpecies(event.target.value);
  }

  function handleDateChange(event: ChangeEvent<HTMLInputElement>) {
    const nextValue = event.target.value;
    setDisplayDate(nextValue);

    if (nextValue.length < 10) {
      setDateError(null);
      return;
    }

    const parsedDate = parseDisplayDate(nextValue);
    if (parsedDate) {
      setSelectedDate(parsedDate);
      setDateError(null);
      return;
    }

    setDateError("Enter the date as MM/DD/YYYY.");
  }

  function handleDateBlur() {
    const parsedDate = parseDisplayDate(displayDate);
    if (!parsedDate) {
      setDateError("Enter the date as MM/DD/YYYY.");
      return;
    }

    setSelectedDate(parsedDate);
    setDisplayDate(formatDisplayDate(parsedDate));
    setDateError(null);
  }

  function handleZoneCardKeyDown(event: KeyboardEvent<HTMLElement>, zoneId: string) {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    setSelectedZoneId(zoneId);
  }

  return (
    <main className={styles.shell}>
      <section className={styles.mapPane}>
        <OffshoreMap
          chlorophyllBreakMapData={chlorophyllBreakMapData}
          chlorophyllBreakMapError={chlorophyllBreakMapError}
          isChlorophyllBreakMapLoading={isChlBreakMapLoading}
          isSstMapLoading={isSstMapLoading}
          isZonesLoading={isZonesLoading}
          onZoneSelect={setSelectedZoneId}
          selectedZoneId={selectedZoneId}
          sstMapData={sstMapData}
          sstMapError={sstMapError}
          zones={zones}
          zonesError={zonesError}
        />
      </section>

      <aside className={styles.panel}>
        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Trip Builder</h2>
          <div className={styles.controlGrid}>
            <div className={styles.controlCard}>
              <label className={styles.label} htmlFor="species">
                Species
              </label>
              <select className={styles.select} id="species" value={selectedSpecies} onChange={handleSpeciesChange}>
                {speciesConfigs.map((species) => (
                  <option key={species.species} value={species.species}>
                    {species.label}
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.controlCard}>
              <label className={styles.label} htmlFor="trip-date">
                Date
              </label>
              <input
                aria-invalid={Boolean(dateError)}
                className={styles.input}
                id="trip-date"
                inputMode="numeric"
                onBlur={handleDateBlur}
                onChange={handleDateChange}
                placeholder="MM/DD/YYYY"
                type="text"
                value={displayDate}
              />
              <p className={styles.controlHint}>Displayed as MM/DD/YYYY. Sent to the API as {apiDate}.</p>
              {dateError && <p className={styles.errorText}>{dateError}</p>}
            </div>
          </div>
          {isZonesLoading && <p className={styles.loadingBanner}>Refreshing zone scores for {selectedSpecies}...</p>}
          {isSstMapLoading && <p className={styles.loadingBanner}>Refreshing the SST map overlay...</p>}
          {isChlBreakMapLoading && <p className={styles.loadingBanner}>Refreshing chlorophyll edge overlay...</p>}
          {zonesError && <p className={styles.errorBanner}>{zonesError}</p>}
          {sstMapError && <p className={styles.errorBanner}>{sstMapError}</p>}
          {chlorophyllBreakMapError && <p className={styles.errorBanner}>{chlorophyllBreakMapError}</p>}
          {supportingError && <p className={styles.errorBanner}>{supportingError}</p>}
          {sourceWarnings.map((warning) => (
            <p className={styles.loadingBanner} key={warning}>
              {warning}
            </p>
          ))}
          {(zonesError || sstMapError || chlorophyllBreakMapError || supportingError) && (
            <button className={styles.retryButton} onClick={handleRetryRequests} type="button">
              Retry data requests
            </button>
          )}
          {(zonesError || sstMapError || chlorophyllBreakMapError || supportingError) && (
            <p className={styles.controlHint}>Current API base URL: {API_BASE_URL}</p>
          )}
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Top Zone</h2>
          {topZone ? (
            <div className={styles.featuredZone}>
              <h3 className={styles.featuredTitle}>{topZone.name}</h3>
              <p className={styles.listText}>{topZone.summary}</p>
              <div className={styles.pillRow}>
                {topZone.species.map((species) => (
                  <span className={styles.pill} key={species}>
                    {species}
                  </span>
                ))}
              </div>
              <div className={styles.featuredStats}>
                <div className={styles.stat}>
                  <p className={styles.statLabel}>Confidence</p>
                  <p className={styles.statValue}>{topZone.score_explanation?.confidence_score?.toFixed(1) ?? "--"}</p>
                </div>
                <div className={styles.stat}>
                  <p className={styles.statLabel}>SST</p>
                  <p className={styles.statValue}>{topZone.sea_surface_temp_f.toFixed(1)} F</p>
                </div>
                <div className={styles.stat}>
                  <p className={styles.statLabel}>Chlorophyll</p>
                  <p className={styles.statValue}>{topZone.chlorophyll_mg_m3.toFixed(2)}</p>
                </div>
                <div className={styles.stat}>
                  <p className={styles.statLabel}>Current</p>
                  <p className={styles.statValue}>{topZone.current_speed_kts.toFixed(1)} kts</p>
                </div>
              </div>
            </div>
          ) : (
            <div className={styles.featuredEmpty}>
              <p className={styles.listText}>No ranked zones available for the current species and date.</p>
            </div>
          )}
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Selected Zone Why It Ranks</h2>
          {selectedZone ? (
            <div className={styles.explanationCard}>
              <h3 className={styles.featuredTitle}>{selectedZone.name}</h3>
              <p className={styles.listText}>{selectedZoneExplanation?.headline}</p>
              <p className={styles.controlHint}>{selectedZoneExplanation?.summary}</p>
              <div className={styles.featuredStats}>
                <div className={styles.stat}>
                  <p className={styles.statLabel}>Confidence</p>
                  <p className={styles.statValue}>{selectedZoneExplanation ? selectedZoneExplanation.confidence_score.toFixed(1) : "--"}</p>
                </div>
                <div className={styles.stat}>
                  <p className={styles.statLabel}>Best Use</p>
                  <p className={styles.listText}>{selectedZoneExplanation?.best_use_case_summary}</p>
                </div>
              </div>
              <div className={styles.list}>
                {selectedZoneExplanation?.top_reasons.map((reason) => (
                  <div className={styles.listItem} key={reason}>
                    <p className={styles.listText}>{reason}</p>
                  </div>
                ))}
              </div>
              <div className={styles.list}>
                {selectedZoneExplanation?.factors.map((factor) => (
                  <article className={styles.listItem} key={factor.factor}>
                    <div className={styles.listTitleRow}>
                      <h4 className={styles.listTitle}>{factor.label}</h4>
                      <span className={styles.listTag}>+{factor.weighted_contribution.toFixed(1)}</span>
                    </div>
                    <p className={styles.listMeta}>
                      Raw {factor.raw_value} | Factor score {factor.score.toFixed(1)}
                    </p>
                    <p className={styles.listText}>{factor.reason}</p>
                  </article>
                ))}
              </div>
              {selectedZoneExplanation && selectedZoneExplanation.watchouts.length > 0 && (
                <div className={styles.list}>
                  {selectedZoneExplanation.watchouts.map((watchout) => (
                    <div className={styles.listItem} key={watchout}>
                      <div className={styles.listTitleRow}>
                        <h4 className={styles.listTitle}>Watchout</h4>
                      </div>
                      <p className={styles.listText}>{watchout}</p>
                    </div>
                  ))}
                </div>
              )}
              {selectedZoneSourceWarnings.length > 0 && (
                <div className={styles.list}>
                  {selectedZoneSourceWarnings.map((warning) => (
                    <div className={styles.listItem} key={warning}>
                      <div className={styles.listTitleRow}>
                        <h4 className={styles.listTitle}>Data Source Note</h4>
                      </div>
                      <p className={styles.listText}>{warning}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className={styles.featuredEmpty}>
              <p className={styles.listText}>Click a zone on the map or in the list to inspect exactly why it ranks well.</p>
            </div>
          )}
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Top Zones</h2>
          <div className={styles.list}>
            {zones.map((zone) => (
              <article
                className={`${styles.listItem} ${selectedZoneId === zone.id ? styles.selectedListItem : ""}`}
                key={`${zone.id}-panel-${zone.scored_for_date}`}
                onClick={() => setSelectedZoneId(zone.id)}
                onKeyDown={(event) => handleZoneCardKeyDown(event, zone.id)}
                role="button"
                tabIndex={0}
              >
                <div className={styles.listTitleRow}>
                  <h3 className={styles.listTitle}>{zone.name}</h3>
                  <span className={styles.listTag}>Score {zone.score}</span>
                </div>
                <p className={styles.listMeta}>
                  {zone.distance_nm} nm | SST {zone.sea_surface_temp_f.toFixed(1)} F | Depth {zone.depth_ft} ft
                </p>
                <p className={styles.listText}>{zone.summary}</p>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Species Config</h2>
          <div className={styles.list}>
            {speciesConfigs.map((species) => (
              <article className={styles.listItem} key={species.species}>
                <div className={styles.listTitleRow}>
                  <h3 className={styles.listTitle}>{species.label}</h3>
                  <span className={styles.listTag}>{species.season_window}</span>
                </div>
                <p className={styles.listMeta}>
                  Preferred temp {species.preferred_temp_f[0]}-{species.preferred_temp_f[1]} F
                </p>
                <p className={styles.listText}>{species.notes}</p>
                {species.temp_break_config && (
                  <p className={styles.controlHint}>
                    SST break: full within {species.temp_break_config.full_score_distance_nm} nm, fades to zero by{" "}
                    {species.temp_break_config.zero_score_distance_nm} nm.
                  </p>
                )}
                {species.chlorophyll_break_config && (
                  <p className={styles.controlHint}>
                    Chlorophyll break: full within {species.chlorophyll_break_config.full_score_distance_nm} nm, fades to zero by{" "}
                    {species.chlorophyll_break_config.zero_score_distance_nm} nm.
                  </p>
                )}
              </article>
            ))}
          </div>
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Recent Trip Logs</h2>
          <div className={styles.list}>
            {tripLogs.map((trip) => (
              <article className={styles.listItem} key={trip.id}>
                <div className={styles.listTitleRow}>
                  <h3 className={styles.listTitle}>{trip.vessel}</h3>
                  <span className={styles.listTag}>{trip.catch_count} fish</span>
                </div>
                <p className={styles.listMeta}>
                  {trip.date} | {trip.zone_id}
                </p>
                <p className={styles.listText}>{trip.notes}</p>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>System Status</h2>
          <div className={styles.statusRow}>
            <article className={styles.statusCard}>
              <h3 className={styles.statusTitle}>{health?.app ?? "Loading API status..."}</h3>
              <p className={styles.statusText}>
                Status: {health?.status ?? "pending"} | Environment: {health?.environment ?? "loading"}
              </p>
              {!health && <p className={styles.statusText}>API base URL: {API_BASE_URL}</p>}
            </article>
            <article className={styles.statusCard}>
              <h3 className={styles.statusTitle}>Database</h3>
              <p className={styles.statusText}>Connection state: {health?.database ?? "loading"}</p>
            </article>
          </div>
        </section>
      </aside>
    </main>
  );
}
