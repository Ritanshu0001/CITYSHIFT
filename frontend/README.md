# CityShift frontend

CityShift compares an 8 km slice of any city with Waymo's established cities—Phoenix, San Francisco, Los Angeles, Austin, and Atlanta—and turns the strongest public-data differences into candidate driving-simulation scenarios.

## Run locally

Node 20 is required.

```bash
nvm use
npm ci
cp .env.local.example .env.local
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The live FastAPI service at port 8000 is the default. Set mock mode to `1` only when working without the backend. Add a Google key for the contract's production map, Places, and Street View path.

## Environment

```dotenv
GOOGLE_MAPS_KEY=
NEXT_PUBLIC_API_BASE=/api/backend
NEXT_PUBLIC_USE_MOCK=0
CITYSHIFT_BACKEND_URL=http://127.0.0.1:8000
```

The same-origin `/api/backend` proxy keeps the app working from both `localhost:3000` and `127.0.0.1:3000`; `CITYSHIFT_BACKEND_URL` is its server-side target. Set `NEXT_PUBLIC_USE_MOCK=1` only to use the bundled deterministic mock. The Google key needs Maps JavaScript API, Places API (New), and Geocoding API access.

## Commands

```bash
npm run mock:generate
npm run lint
npx tsc --noEmit
npm run build
```

See [HANDOFF.md](./HANDOFF.md) for implementation status, validation evidence, ownership boundaries, and the exact continuation steps for another Codex account.
