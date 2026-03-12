import styles from "./page.module.css";

type Zone = {
  id: string;
  name: string;
  species: string[];
  distance_nm: number;
  center: { lat: number; lng: number };
  score: number;
  sst_f: number;
  chlorophyll_mg_m3: number;
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
  id: string;
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

const zonePositions: Record<string, { top: string; left: string }> = {
  "hudson-edge-east": { top: "30%", left: "56%" },
  "cartwright-corner": { top: "54%", left: "68%" },
  "cox-ledges-south": { top: "62%", left: "34%" },
};

async function fetchApi<T>(path: string): Promise<T> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(`${baseUrl}${path}`, { cache: "no-store" });

  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export default async function HomePage() {
  const [zones, tripLogs, speciesConfigs, health] = await Promise.all([
    fetchApi<Zone[]>("/zones"),
    fetchApi<TripLog[]>("/trip-logs"),
    fetchApi<SpeciesConfig[]>("/configs/species"),
    fetchApi<HealthResponse>("/health"),
  ]);

  const topZone = [...zones].sort((a, b) => b.score - a.score)[0];

  return (
    <main className={styles.shell}>
      <section className={styles.mapPane}>
        <div className={styles.mapGrid} />
        <div className={styles.contourA} />
        <div className={styles.contourB} />
        <div className={styles.contourC} />
        <div className={styles.shelfBand} />

        <div className={styles.hud}>
          <div className={styles.brand}>
            <p className={styles.eyebrow}>Montauk Offshore Intelligence</p>
            <h1 className={styles.title}>Read the water before the run.</h1>
            <p className={styles.subtitle}>
              A map-first command surface for offshore planning around Montauk, ready for future SST,
              chlorophyll, bathymetry, and marine weather overlays.
            </p>
          </div>

          <div className={styles.legend}>
            <p className={styles.legendTitle}>Signal Legend</p>
            <div className={styles.legendList}>
              <div className={styles.legendItem}>
                <span className={styles.legendSwatch} style={{ background: "var(--accent)" }} />
                High-confidence zone
              </div>
              <div className={styles.legendItem}>
                <span className={styles.legendSwatch} style={{ background: "var(--warning)" }} />
                Temperature edge
              </div>
              <div className={styles.legendItem}>
                <span className={styles.legendSwatch} style={{ background: "var(--danger)" }} />
                Shelf transition
              </div>
            </div>
          </div>
        </div>

        <div className={styles.zonesLayer}>
          {zones.map((zone) => {
            const position = zonePositions[zone.id] ?? { top: "50%", left: "50%" };
            return (
              <article
                key={zone.id}
                className={styles.zoneCard}
                style={{ top: position.top, left: position.left }}
              >
                <span className={styles.zoneDot} />
                <h2 className={styles.zoneName}>{zone.name}</h2>
                <p className={styles.zoneMeta}>
                  Score {zone.score} | {zone.distance_nm} nm
                </p>
                <p className={styles.zoneSummary}>{zone.summary}</p>
              </article>
            );
          })}
        </div>
      </section>

      <aside className={styles.panel}>
        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Trip Builder</h2>
          <div className={styles.controlGrid}>
            <div className={styles.controlCard}>
              <label className={styles.label} htmlFor="species">
                Species
              </label>
              <select className={styles.select} id="species" defaultValue={speciesConfigs[0]?.id}>
                {speciesConfigs.map((species) => (
                  <option key={species.id} value={species.id}>
                    {species.label}
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.controlCard}>
              <label className={styles.label} htmlFor="trip-date">
                Date
              </label>
              <input className={styles.input} id="trip-date" type="date" defaultValue="2026-06-18" />
            </div>
          </div>
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Top Zone</h2>
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
                <p className={styles.statValue}>{topZone.sst_f.toFixed(1)} F</p>
              </div>
              <div className={styles.stat}>
                <p className={styles.statLabel}>Chlorophyll</p>
                <p className={styles.statValue}>{topZone.chlorophyll_mg_m3.toFixed(2)}</p>
              </div>
              <div className={styles.stat}>
                <p className={styles.statLabel}>Depth</p>
                <p className={styles.statValue}>{topZone.depth_ft} ft</p>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.panelSection}>
          <h2 className={styles.panelHeading}>Top Zones</h2>
          <div className={styles.list}>
            {zones.map((zone) => (
              <article className={styles.listItem} key={zone.id}>
                <div className={styles.listTitleRow}>
                  <h3 className={styles.listTitle}>{zone.name}</h3>
                  <span className={styles.listTag}>Score {zone.score}</span>
                </div>
                <p className={styles.listMeta}>
                  {zone.distance_nm} nm | SST {zone.sst_f.toFixed(1)} F | Depth {zone.depth_ft} ft
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
              <article className={styles.listItem} key={species.id}>
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
              <h3 className={styles.statusTitle}>{health.app}</h3>
              <p className={styles.statusText}>
                Status: {health.status} | Environment: {health.environment}
              </p>
            </article>
            <article className={styles.statusCard}>
              <h3 className={styles.statusTitle}>Database</h3>
              <p className={styles.statusText}>Connection state: {health.database}</p>
            </article>
          </div>
        </section>
      </aside>
    </main>
  );
}
