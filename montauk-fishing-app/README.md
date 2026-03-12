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

Today the environmental input service still uses seeded placeholder values from a separate mock signal catalog. That means SST, chlorophyll, current, bathymetry/structure distance, and weather risk are still mocked even though the scoring path is now ready for live providers.

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
