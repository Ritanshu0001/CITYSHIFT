# CityShift frontend handoff

## Current state

The P3 frontend is implemented through the contract's Phase 5 UI validation pass.

- Git remote: `https://github.com/Ritanshu0001/JAR.git`
- Branch: `main`
- Frontend: Next.js App Router, TypeScript, Tailwind CSS 4
- Runtime target: Node 20 (`.nvmrc` and `package.json#engines`)
- Default mode: local mock data (`NEXT_PUBLIC_USE_MOCK` defaults to enabled)
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

Mock mode works without credentials. For the live stack, edit `.env.local`:

```dotenv
NEXT_PUBLIC_GOOGLE_MAPS_KEY=your_key_here
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_USE_MOCK=0
```

The Google key must have Maps JavaScript API, Places API, and Geocoding API enabled. `.env.local` is ignored and must never be committed.

## What is implemented

- `/`: product narrative, city search, Google Places autocomplete when configured, geocoder/plain-input fallback, cached city list.
- `/city/[slug]`: cached → polling → error → result state machine, polling every 1500 ms.
- Five-step progress screen using the exact contract step names.
- Google Maps + deck.gl `H3HexagonLayer` when a key is present.
- Interactive SVG/H3 cartographic fallback when no Maps key is present.
- Shift legend using the locked `<80`, `80–95`, and `≥95` bands.
- Clickable hex evidence panel with top features, Phoenix medians, z-scores, percentiles, and novel-feature warnings.
- Street View lookup within 100 m, isolated so failure cannot break the evidence panel.
- City-vs-Phoenix climate, driving-side, OSM completeness, novel-city, and top-shift comparison.
- Ranked scenario cards with trigger evidence and persistent map highlighting.
- Responsive layouts, keyboard focus states, reduced-motion support, and no horizontal overflow at 390 px.
- A deterministic 61-cell New York mock generated from real H3 indexes.

## Verification already completed

```bash
npm run lint
npx tsc --noEmit
npm run build
```

The production build uses webpack explicitly because Turbopack stalled while bundling the deck.gl dependency graph in this environment.

Manual browser checks passed for:

- Homepage layout and cached-city navigation.
- Search → mock progress → result transition.
- Hex selection and evidence rendering.
- Novel feature warning and no-key Street View fallback.
- Comparison rendering including a zero-value Phoenix snow baseline.
- Scenario selection and six-hex map highlighting.
- Desktop at 1440 × 900.
- Mobile at 390 × 844 with `scrollWidth === innerWidth`.

## External checks still required

These cannot be honestly completed from the current P3-only checkout:

1. Start P1's FastAPI service on port 8000 and set `NEXT_PUBLIC_USE_MOCK=0`.
2. Run a cached Phoenix result, then one uncached city, confirming the API matches `src/lib/types.ts`.
3. Add a valid Google Maps key and confirm Google basemap rendering, Places selection, and at least one Street View panorama.
4. Validate cached Phoenix, Tucson, New York, and London once P1/P2 results exist. Expected qualitative pattern: Phoenix and Tucson mostly green; New York and London more yellow/red; London shows left-hand traffic.
5. Record the final demo only after those live checks. The script is in `demo/DEMO-SCRIPT.md`.

## Dependency note

`npm audit` currently reports 11 transitive advisories beneath deck.gl's optional loaders (`fflate`, `image-size`, and related packages). `npm audit fix` cannot resolve them safely; `--force` proposes a breaking deck.gl downgrade. The app uses `H3HexagonLayer`, not the affected archive, texture, or 3D model loaders. Do not run `npm audit fix --force` without retesting the map integration.

## Ownership boundary

P3 owns `frontend/**` and `demo/**`. Do not edit `backend/**`, `cache/**`, `pitch/**`, or the locked contract files. If the live backend differs from the contract, report it to P1 rather than changing the frontend types to match an accidental response.
