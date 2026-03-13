"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, type ChangeEvent } from "react";
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
  structure_distance_nm: number;
  chlorophyll_mg_m3: number;
  current_speed_kts: number;
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
    type: "Point";
    coordinates: [number, number];
  };
  properties: {
    sea_surface_temp_f: number;
  };
};

type SstMapResponse = {
  metadata: {
    date: string;
    bbox: [number, number, number, number];
    source: "live" | "processed" | "mock_fallback" | "unavailable" | string;
    units: "fahrenheit";
    point_count: number;
    temp_range_f: [number, number] | null;
  };
  data: {
    type: "FeatureCollection";
    features: SstMapFeature[];
  };
};

const DEFAULT_ISO_DATE = "2026-03-11";
const DEFAULT_SPECIES = "bluefin";
const DEFAULT_MAP_BBOX = "-72.4,39.8,-69.8,41.4";
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const DEFAULT_REQUEST_TIMEOUT_MS = 4000;
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

function getApiUnavailableMessage(path: string): string {
  return `API unavailable at ${API_BASE_URL} while requesting ${path}.`;
}

function buildEmptySstMapResponse(apiDate: string): SstMapResponse {
  return {
    metadata: {
      date: apiDate,
      bbox: [-72.4, 39.8, -69.8, 41.4],
      source: "unavailable",
      units: "fahrenheit",
      point_count: 0,
      temp_range_f: null,
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
      throw new Error(`${getApiUnavailableMessage(path)} Request timed out after ${timeoutMs} ms.`);
    }
    throw new Error(`${getApiUnavailableMessage(path)} Check that the backend is running.`);
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

  const [isZonesLoading, setIsZonesLoading] = useState(true);
  const [isSstMapLoading, setIsSstMapLoading] = useState(true);
  const [zonesError, setZonesError] = useState<string | null>(null);
  const [sstMapError, setSstMapError] = useState<string | null>(null);
  const [supportingError, setSupportingError] = useState<string | null>(null);

  const apiDate = toApiDate(selectedDate);

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
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setIsZonesLoading(true);
    setZonesError(null);

    fetchApi<Zone[]>(`/zones?date=${apiDate}&species=${selectedSpecies}`, {
      signal: controller.signal,
      timeoutMs: 5000,
    })
      .then((zoneResponse) => {
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
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsZonesLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [apiDate, selectedSpecies]);

  useEffect(() => {
    const controller = new AbortController();
    setIsSstMapLoading(true);
    setSstMapError(null);

    fetchApi<SstMapResponse>(`/map/sst?date=${apiDate}&bbox=${encodeURIComponent(DEFAULT_MAP_BBOX)}`, {
      signal: controller.signal,
      timeoutMs: 5000,
    })
      .then((response) => {
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
        setSstMapData(buildEmptySstMapResponse(apiDate));
        setSstMapError(message);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsSstMapLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [apiDate]);

  const topZone = zones[0] ?? null;

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

  return (
    <main className={styles.shell}>
      <section className={styles.mapPane}>
        <OffshoreMap
          isSstMapLoading={isSstMapLoading}
          isZonesLoading={isZonesLoading}
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
          {zonesError && <p className={styles.errorBanner}>{zonesError}</p>}
          {sstMapError && <p className={styles.errorBanner}>{sstMapError}</p>}
          {supportingError && <p className={styles.errorBanner}>{supportingError}</p>}
          {(zonesError || sstMapError || supportingError) && (
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
                  <p className={styles.statValue}>{topZone.score}</p>
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
          <h2 className={styles.panelHeading}>Top Zones</h2>
          <div className={styles.list}>
            {zones.map((zone) => (
              <article className={styles.listItem} key={`${zone.id}-panel-${zone.scored_for_date}`}>
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
