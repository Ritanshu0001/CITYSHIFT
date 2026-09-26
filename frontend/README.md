# CityShift frontend

CityShift compares an 8 km slice of any city with Phoenix and turns the strongest public-data differences into candidate driving-simulation scenarios.

## Run locally

Node 20 is required.

```bash
nvm use
npm ci
cp .env.local.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Mock mode is enabled by default and uses dark-filtered OpenStreetMap tiles without a key. Add a Google key for the contract's production map, Places, and Street View path.

## Environment

```dotenv
NEXT_PUBLIC_GOOGLE_MAPS_KEY=
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_USE_MOCK=1
```

Set `NEXT_PUBLIC_USE_MOCK=0` to use the FastAPI service. The Google key needs Maps JavaScript API, Places API, and Geocoding API access.

## Commands

```bash
npm run mock:generate
npm run lint
npx tsc --noEmit
npm run build
```

See [HANDOFF.md](./HANDOFF.md) for implementation status, validation evidence, ownership boundaries, and the exact continuation steps for another Codex account.
