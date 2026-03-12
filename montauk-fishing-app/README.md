# Montauk Fishing App

`montauk-fishing-app` is a monorepo scaffold for an offshore fishing intelligence platform focused on Montauk. It includes:

- `apps/web`: Next.js + TypeScript frontend with a full-screen map-style UI and intelligence panel
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
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r apps/api/requirements.txt
   ```

3. Start Postgres with Docker:

   ```powershell
   docker compose up postgres -d
   ```

4. Run the backend:

   ```powershell
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir apps/api
   ```

5. Run the frontend:

   ```powershell
   npm run dev:web
   ```

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
- `GET /trip-logs`: mock trip history entries
- `GET /configs/species`: species scoring configs, preferred ranges, and normalized weights

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

SST is now the first signal with a live-data adapter path: the backend will read processed CoastWatch SST files when available, derive nearest-zone temperature and a simple local gradient, cache repeated lookups, and fall back to the mock SST catalog if processed data is unavailable or invalid.

Chlorophyll now follows the same adapter path: the backend will read processed CoastWatch chlorophyll files when available, use the nearest usable grid point for `chlorophyll_mg_m3`, cache repeated lookups, and fall back to the mock chlorophyll catalog if processed data is unavailable or invalid.

Current data now follows the same adapter path: the backend will read processed current files when available, use the nearest usable grid point for `current_speed_kts`, derive a simple local `current_break_index`, cache repeated lookups, and fall back to the mock current catalog if processed data is unavailable or invalid.

Structure/bathymetry now follows the same adapter path: the backend will read processed structure files when available, use the nearest usable grid point for `structure_distance_nm`, cache repeated lookups, and fall back to the mock structure catalog if processed data is unavailable or invalid.

Weather now follows the same adapter path: the backend will read processed weather files when available, use the nearest usable grid point for `weather_risk_index`, cache repeated lookups, and fall back to the mock weather catalog if processed data is unavailable or invalid.

For provider provenance, the backend tracks source labels such as `processed`, `mock_fallback`, and `unavailable` internally. The chlorophyll adapter currently assumes processed files live under `data/processed/coastwatch/chlorophyll/<date>/...json` and expose a top-level `grid` array of `{ latitude, longitude, value }` points where `value` is already chlorophyll concentration in `mg/m3`. The current adapter makes the same file-layout assumption under `data/processed/coastwatch/current/<date>/...json`, with `value` interpreted as current speed in knots. The structure adapter makes the same file-layout assumption under `data/processed/coastwatch/structure/<date>/...json`, with each positive-value grid point treated as usable structure/edge presence and `structure_distance_nm` derived as the nearest distance from the zone center to any such point. The weather adapter makes the same file-layout assumption under `data/processed/coastwatch/weather/<date>/...json`, with `value` interpreted as a normalized weather risk score in the `[0, 1]` range.

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
