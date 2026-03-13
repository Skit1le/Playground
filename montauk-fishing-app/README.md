# Montauk Fishing App

`montauk-fishing-app` is a monorepo scaffold for an offshore fishing intelligence platform focused on Montauk. It includes:

- `apps/web`: Next.js + TypeScript frontend with a real MapLibre offshore map and intelligence panel
- `apps/api`: FastAPI backend with Postgres-backed scoring configs, seeded offshore zones, and ranking endpoints
- `docker-compose.yml`: local development stack for the frontend, backend, and Postgres

The current version uses mock intelligence data and is structured to support future ingestion of SST, chlorophyll, bathymetry, and weather layers.

## Repo Layout

```text
montauk-fishing-app/
  apps/
    api/
    web/
  scripts/
  docker-compose.yml
```

## Prerequisites

- Node.js 20+
- Python 3.11+
- Docker Desktop with Compose support

## Quick Start

### Option 1: Docker Compose

1. Copy the example environment files:

   ```powershell
   Copy-Item .env.example .env
   Copy-Item apps/web/.env.local.example apps/web/.env.local
   Copy-Item apps/api/.env.example apps/api/.env
   ```

2. Start the local stack:

   ```powershell
   docker compose up --build
   ```

3. Open the apps:

- Frontend: [http://localhost:3000](http://localhost:3000)
- Backend API: [http://localhost:8000](http://localhost:8000)
- FastAPI docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Option 2: Run Services Locally

1. Install frontend dependencies:

   ```powershell
   npm install
   ```

2. Create and activate a Python virtual environment, then install backend dependencies:

   ```powershell
   py -3 -m venv apps/api/.venv
   apps/api/.venv/Scripts/activate
   pip install -r apps/api/requirements.txt
   ```

3. Start Postgres with Docker:

   ```powershell
   docker compose up postgres -d
   ```

4. Run the backend:

   ```powershell
   .\scripts\start_api_windows.ps1
   ```

   Direct command if the venv `python.exe` launcher is blocked on Windows:

   ```powershell
   $env:PYTHONPATH="$PWD\apps\api;$PWD\apps\api\.venv\Lib\site-packages"
   py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir apps/api
   ```

   If `py` is not available, use:

   ```powershell
   $env:PYTHONPATH="$PWD\apps\api;$PWD\apps\api\.venv\Lib\site-packages"
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir apps/api
   ```

5. Run the frontend:

   ```powershell
   npm run dev:web
   ```

For local development, prefer `http://127.0.0.1:8000` for the API base URL. The frontend now defaults to that address and shows a clear unavailable message if the API cannot be reached.

The API now also tolerates a missing local Postgres instance in development: startup falls back to seeded in-memory species and zone data after a short retry window, `/health` still responds, and `/zones` plus `/configs/species` can continue serving local mock-backed results.

On Windows, the recommended API startup path is `.\scripts\start_api_windows.ps1`. It avoids relying on `apps/api/.venv/Scripts/python.exe`, which can fail with `Access is denied` on some machines even when the installed packages are fine.

## Environment Variables

### Root `.env`

See [`.env.example`](/C:/Users/miles/OneDrive/Documents/Playground/montauk-fishing-app/.env.example).

### Frontend

See [`apps/web/.env.local.example`](/C:/Users/miles/OneDrive/Documents/Playground/montauk-fishing-app/apps/web/.env.local.example).

### Backend

See [`apps/api/.env.example`](/C:/Users/miles/OneDrive/Documents/Playground/montauk-fishing-app/apps/api/.env.example).

## API Endpoints

- `GET /health`: service status and Postgres connectivity check
- `GET /zones?date=YYYY-MM-DD&species=bluefin`: ranked offshore zones scored for `bluefin`, `yellowfin`, or `mahi`
- `GET /map/sst?date=YYYY-MM-DD&bbox=minLng,minLat,maxLng,maxLat`: backend-normalized SST overlay data for the offshore map
- `GET /trip-logs`: mock trip history entries
- `GET /configs/species`: species scoring configs, preferred ranges, and normalized weights

`GET /zones` responses now include both raw `score_breakdown` values and explainability fields: `score_weights` plus `weighted_score_breakdown`, so the final score can be traced back to each weighted contribution.

## Scoring Engine

Species scoring configs are stored in Postgres and seeded on API startup. Each zone score is a weighted blend of:

- temperature suitability
- temperature gradient
- structure proximity
- chlorophyll suitability
- current suitability
- weather fishability

The backend seeds Montauk offshore waters including Hudson Edge East, Cartwright Corner, Cox Ledges South, Butterfish Hole, and The Dip North.

## Zones Backend Flow

`GET /zones` now runs through a dedicated service layer:

- route handler validates query params and delegates to `ZonesService`
- `ZonesService` loads species config and candidate zones from repositories
- `ZoneEnvironmentalInputService` assembles domain signals for temperature, chlorophyll, current, bathymetry, and weather
- `ZoneScoringEngine` converts those signals plus species config weights into a score and breakdown
- response mappers build the stable `RankedZone` schema returned to the frontend

Today the environmental input service uses provider-backed SST, chlorophyll, current, structure, and weather paths with fallback to a separate mock signal catalog. Every field in `ZoneEnvironmentalSignals` now resolves through a processed-or-fallback path.

SST is now the first signal with a live-data adapter path: the backend can fetch one CoastWatch ERDDAP grid subset for a requested date and bounding box, normalize that upstream dataset into shared internal SST points, derive nearest-zone temperature plus a simple local gradient, and fall back cleanly when that upstream data is unavailable.

The SST resolution order is:

- live CoastWatch ERDDAP grid fetch
- processed SST file
- mock SST fallback

The live/historical adapter works for both recent and historical dates as long as the configured ERDDAP dataset exposes that time range. It fetches one SST grid subset per `date+bbox`, caches that normalized dataset in memory, and reuses it for both:

- zone-level SST extraction in `GET /zones`
- SST map surface generation in `GET /map/sst`

The frontend now also consumes a dedicated backend SST map contract at `GET /map/sst`. That endpoint returns a GeoJSON SST cell surface plus metadata:

- `metadata.source`: `live`, `processed`, `mock_fallback`, or `unavailable`
- `metadata.bbox`, `metadata.point_count`, `metadata.cell_count`, `metadata.temp_range_f`, and `metadata.dataset_id` when available
- `data`: GeoJSON `FeatureCollection` of SST polygon cells with `sea_surface_temp_f`

This is intentionally GeoJSON/grid based rather than raster/tile based because it is the simplest maintainable path for local development: the backend can reuse one cached SST dataset per `date+bbox`, the frontend can render it directly in MapLibre, and the `/zones` response contract stays unchanged.

Runtime logging now includes SST provenance details so local debugging can distinguish `live`, `processed`, and `mock_fallback` usage. `/map/sst` logs the resolved `source`, `dataset_id`, and SST cache key, and the zones flow logs the SST source plus the dataset/cache key used for zone-level extraction. When the map request bbox matches the default zone-level SST bbox, those logs will show the same cached `date+bbox` dataset key.

Chlorophyll now follows the same live/historical adapter path. The backend can fetch one CoastWatch ERDDAP chlorophyll grid subset per `date+bbox`, normalize that upstream dataset into shared internal chlorophyll points, reuse that dataset for zone extraction, and fall back through:

- live CoastWatch ERDDAP grid fetch
- processed chlorophyll file
- mock chlorophyll fallback

Current data now follows the same adapter path: the backend will read processed current files when available, use the nearest usable grid point for `current_speed_kts`, derive a simple local `current_break_index`, cache repeated lookups, and fall back to the mock current catalog if processed data is unavailable or invalid.

Structure/bathymetry now follows the same adapter path: the backend will read processed structure files when available, use the nearest usable grid point for `structure_distance_nm`, cache repeated lookups, and fall back to the mock structure catalog if processed data is unavailable or invalid.

Weather now follows the same adapter path: the backend will read processed weather files when available, use the nearest usable grid point for `weather_risk_index`, cache repeated lookups, and fall back to the mock weather catalog if processed data is unavailable or invalid.

For reliable local development, processed-data adapters now cache both successful lookups and missing/invalid date payloads so a missing processed file only fails once per date instead of once per zone. Each processed lookup also has a small timeout guard before the service falls back to mock values, which keeps `/zones` from hanging behind a slow provider during local runs.

For provider provenance, the backend tracks source labels such as `processed`, `mock_fallback`, and `unavailable` internally. The chlorophyll adapter currently assumes processed files live under `data/processed/coastwatch/chlorophyll/<date>/...json` and expose a top-level `grid` array of `{ latitude, longitude, value }` points where `value` is already chlorophyll concentration in `mg/m3`. The current adapter makes the same file-layout assumption under `data/processed/coastwatch/current/<date>/...json`, with `value` interpreted as current speed in knots. The structure adapter makes the same file-layout assumption under `data/processed/coastwatch/structure/<date>/...json`, with each positive-value grid point treated as usable structure/edge presence and `structure_distance_nm` derived as the nearest distance from the zone center to any such point. The weather adapter makes the same file-layout assumption under `data/processed/coastwatch/weather/<date>/...json`, with `value` interpreted as a normalized weather risk score in the `[0, 1]` range.

To enable live SST fetching, configure the backend with:

- `LIVE_SST_ENABLED=true`
- `LIVE_SST_DATASET_ID=<NOAA CoastWatch ERDDAP SST dataset id>`
- optional `LIVE_SST_BASE_URL`
- optional `LIVE_SST_TIMEOUT_SECONDS`
- optional `LIVE_SST_VARIABLE_NAME`

The default live base URL is `https://coastwatch.pfeg.noaa.gov/erddap/griddap`. A common example dataset ID is `noaacwBLENDEDsstDaily`, but confirm the exact dataset you want before enabling live mode.
For CoastWatch OISST-style datasets such as `ncdcOisst21NrtAgg`, the backend also supports:

- `LIVE_SST_TIME_SUFFIX=T12:00:00Z`
- `LIVE_SST_EXTRA_SELECTORS=[(0.0)]`
- `LIVE_SST_LONGITUDE_MODE=0_360`

That covers daily grids whose SST variable is addressed as `sst[(dateT12:00:00Z)][(0.0)][(lat)][(lon)]` and whose longitudes are stored in `0..360`.

Repeated SST requests for the same `date+bbox` stay in memory for the lifetime of the API process, so local development refreshes do not re-fetch the upstream ERDDAP dataset unnecessarily. If the live fetch fails, the backend immediately falls back to the processed local SST cache, and if that is unavailable too it falls back to the seeded mock SST catalog.

To enable live chlorophyll fetching, configure the backend with:

- `LIVE_CHLOROPHYLL_ENABLED=true`
- `LIVE_CHLOROPHYLL_DATASET_ID=<NOAA CoastWatch ERDDAP chlorophyll dataset id>`
- optional `LIVE_CHLOROPHYLL_BASE_URL`
- optional `LIVE_CHLOROPHYLL_TIMEOUT_SECONDS`
- optional `LIVE_CHLOROPHYLL_VARIABLE_NAME`

Repeated chlorophyll requests for the same `date+bbox` stay in memory for the lifetime of the API process, so local development refreshes do not re-fetch the upstream ERDDAP dataset unnecessarily. If the live fetch fails, the backend immediately falls back to the processed local chlorophyll cache, and if that is unavailable too it falls back to the seeded mock chlorophyll catalog.

## Ingestion Scripts

NOAA CoastWatch ingestion scripts live under [scripts](/C:/Users/miles/OneDrive/Documents/Playground/montauk-fishing-app/scripts). They can fetch SST and chlorophyll subsets by date and bounding box, save raw CSV responses locally, and emit processed JSON that backend code can load through [ingested_products.py](/C:/Users/miles/OneDrive/Documents/Playground/montauk-fishing-app/apps/api/app/ingested_products.py).

See [scripts/README.md](/C:/Users/miles/OneDrive/Documents/Playground/montauk-fishing-app/scripts/README.md) for setup and examples.

## Future Direction

This scaffold is designed so the backend can later layer in:

- SST raster ingestion and contour generation
- Chlorophyll break analysis
- Bathymetry and edge detection
- Wind, swell, and forecast overlays
- Logged catch reports and scoring models
