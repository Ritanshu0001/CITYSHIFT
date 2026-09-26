# CityShift frontend handoff

## Current state

The P3 frontend is implemented through the contract's Phase 5 UI validation pass.

- Git remote: `https://github.com/Ritanshu0001/JAR.git`
- Branch: `main`
- Frontend: Next.js App Router, TypeScript, Tailwind CSS 4
- Runtime target: Node 20 (`.nvmrc` and `package.json#engines`)
- Default mode: live FastAPI data (`NEXT_PUBLIC_USE_MOCK=0`; mock mode is opt-in)
- API contract: implemented in `src/lib/types.ts` and `src/lib/api.ts`
- Local contract and plan folders are intentionally ignored by Git and remain in the existing checkout.

## Continue on this device with another Codex account

Do not create a second clone unless you need one. Open the existing directory in VS Code so the ignored local contract files remain available:

```bash
code /Users/muhammad/Downloads/cityshift
```

Sign into the desired Codex account in the VS Code Codex extension, then give it this instruction:

> Read `frontend/HANDOFF.md`, then inspect `git status` and `git log -1`. Continue P3 work only inside `frontend/` and `demo/`. The shared contracts are local and ignored under `contracts/`; read `contracts/CONTRACTS.md`, `contracts/SOURCE-PLAN.md`, then `plans/P3-FRONTEND.md` before changing API shapes.

The Codex account and GitHub account are separate. Confirm the GitHub identity before pushing:

```bash
gh auth status
git remote -v
```

## Local setup

```bash
cd /Users/muhammad/Downloads/cityshift/frontend
nvm use
npm ci
cp .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`.

The live stack is the default. Configure `.env.local` like this:

```dotenv
GOOGLE_MAPS_KEY=your_key_here
NEXT_PUBLIC_API_BASE=/api/backend
NEXT_PUBLIC_USE_MOCK=0
CITYSHIFT_BACKEND_URL=http://127.0.0.1:8000
```

The same-origin `/api/backend` rewrite avoids browser CORS differences between `localhost` and `127.0.0.1`; `CITYSHIFT_BACKEND_URL` controls the server-side target. The Google key must have Maps JavaScript API, Places API (New), and Geocoding API enabled. `.env.local` is ignored and must never be committed.

## What is implemented

- `/`: product narrative, city search, Google Places autocomplete when configured, geocoder/plain-input fallback, cached city list.
- `/city/[slug]`: cached → polling → error → result state machine, polling every 1500 ms.
- Five-step progress screen using the exact contract step names.
- Google Maps + deck.gl `H3HexagonLayer` when a key is present.
- Interactive H3 overlay on real, dark-filtered OpenStreetMap tiles when no Google key is present; this is the local/demo fallback and Google Maps remains the contract-mandated production path.
- Shift legend using the locked `<80`, `80–95`, and `≥95` bands.
- Clickable hex evidence panel with top features, pooled reference medians, z-scores, percentiles, and novel-feature warnings.
- Street View lookup within 100 m, isolated so failure cannot break the evidence panel.
- City-vs-reference climate, driving-side, OSM completeness, novel-city, and top-shift comparison.
- Ranked scenario cards with trigger evidence and persistent map highlighting.
- Responsive layouts, keyboard focus states, reduced-motion support, and no horizontal overflow at 390 px.
- An offline New York mock generated from the latest committed backend result.

## Verification already completed

```bash
npm run lint
npx tsc --noEmit
npm run build
```

The production build uses webpack explicitly because Turbopack stalled while bundling the deck.gl dependency graph in this environment.

Manual browser checks passed for:

- Homepage layout and cached-city navigation.
- Live API listing of all 12 cached cities and instant cached-city navigation.
- Google Places formatted-address selection (`Paris, France`) and API-returned slug navigation.
- Contract-order progress and the readable backend error screen under a controlled Overpass failure.
- Hex selection and evidence rendering.
- Novel feature warning, real no-key street basemap, and no-key Street View fallback.
- Comparison rendering against the pooled five-city reference, including its climate maxima.
- Scenario selection and six-hex map highlighting.
- Desktop at 1440 × 900.
- Mobile at 390 × 844 with `scrollWidth === innerWidth`.

## Live demo status

P1's FastAPI service and P2's model output are integrated. Twelve cached cities return instantly from `/cities`; use these during the demo because a new city can take 2–6 minutes when Overpass is slow. The browser-verified backup path opens New York from the home list and renders the H3 map, Why evidence, and all scenario cards from local cached data. If Google Maps is unavailable or the browser goes offline, the map now switches to the local dark H3 surface instead of leaving a blank map.

## Dependency note

`npm audit` currently reports 11 transitive advisories beneath deck.gl's optional loaders (`fflate`, `image-size`, and related packages). `npm audit fix` cannot resolve them safely; `--force` proposes a breaking deck.gl downgrade. The app uses `H3HexagonLayer`, not the affected archive, texture, or 3D model loaders. Do not run `npm audit fix --force` without retesting the map integration.

## Ownership boundary

P3 owns `frontend/**` and `demo/**`. Do not edit `backend/**`, `cache/**`, `pitch/**`, or the locked contract files. If the live backend differs from the contract, report it to P1 rather than changing the frontend types to match an accidental response.
