# P3 Plan: Frontend

Read `contracts/CONTRACTS.md` first. It is the authority for every endpoint, JSON field and constant. This plan tells you what to build and when. It does not restate the contract; where it says "per contract" go look. `contracts/SOURCE-PLAN.md` is the original team plan, kept for background, the demo script and the Q&A answers; where it differs from the contract, the contract wins.

## Your role

You own everything the judges see: search, progress screen, hex heatmap, why panel with Street View, city-vs-Phoenix comparison, scenario cards, and the demo video.

**You own:** `frontend/**` and `demo/**`.

**You never touch:** `backend/**`, `cache/**`, `pitch/**`, `contracts/CONTRACTS.md` after hour 0.5.

**You produce for others:**
- For P2: screenshots of the map, why panel, comparison and cards for the slides, around hour 12.
- For everyone: the demo video in the last 4 hours.

**You consume from others:**
- From P1: the four endpoints in contract 4.1 on `http://localhost:8000`, available around hour 8. Until then you run on the mock (design decision D7).
- From P2: nothing directly; their output arrives through P1's API.

## Guardrails specific to you

- Build every component against `src/lib/types.ts`, which mirrors contract 4.2 field for field. If a field you want is not in the contract, do not add it to the type. Write a change request and derive it client-side if you can (example: hex center from `h3-js`).
- Stack is fixed by contract D11: Next.js App Router + TypeScript, `@vis.gl/react-google-maps`, `@deck.gl/google-maps` `GoogleMapsOverlay`, `@deck.gl/geo-layers` `H3HexagonLayer`, `h3-js` v4 (`cellToLatLng`, `cellToBoundary`). Check installed versions before writing code; read the installed package's typings rather than guessing prop names.
- Two env vars only: `NEXT_PUBLIC_GOOGLE_MAPS_KEY` and `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`), plus `NEXT_PUBLIC_USE_MOCK` for development. Commit `.env.local.example`; never commit the real key.
- The Google key needs Maps JavaScript API, Places API and Geocoding API enabled with billing on. Street View panoramas are part of Maps JavaScript API. Confirm this at hour 0, not hour 10.
- Google's legacy `places.Autocomplete` widget may be unavailable to keys created after early 2025. If it errors, spend at most 30 minutes on `PlaceAutocompleteElement`, then fall back to a plain text input plus `google.maps.Geocoder`. The fallback is fully acceptable for the demo.
- Colors are fixed: green below 80, yellow 80 to 95, red 95 and up, per contract. Pick one exact RGB per band in `src/lib/constants.ts` and use it everywhere (map, legend, cards).
- No global state library. React state in the page component plus props is enough for this app.
- Never compute slugs, scores, bands or z-values client-side. Use what the API sends.

---

## Phase 0: hours 0 to 0.5 (all three together) · checkpoint "contracts agreed"

Your specific job in the discussion: confirm the response shape of `POST /analyze` (single shape, `cached` flag) and the `JOB_STEPS` list, because your progress screen is built on them. Ask now if the hex center should be in the API; the contract's answer is no, compute it with `h3-js`.

Mechanical deliverables while the group talks:

1. From the repo root, run `npx create-next-app@latest frontend` with TypeScript (the `frontend/` directory is deliberately absent so the generator does not refuse to run); choose, App Router, `src/` directory, ESLint, Tailwind. Then install `@vis.gl/react-google-maps`, `@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/geo-layers`, `@deck.gl/google-maps`, `h3-js`.
2. `src/lib/types.ts`: `Hex`, `TopFeature`, `Summary`, `Scenario`, `CityResult`, `AnalyzeResponse`, `JobStatus`, `CitiesResponse` exactly per contract 4.1 and 4.2.
3. `src/lib/constants.ts`: `API_BASE`, `POLL_MS = 1500`, `JOB_STEPS`, band thresholds and colors, `REFERENCE_SLUG`.
4. `src/mocks/result.json`: start from the example in contract 4.2 and expand to about 60 hexes around one center with a realistic band mix (most green, some yellow, a few red, one or two with `novel`), five scenarios, a full `feature_comparison`. Write a tiny `src/mocks/generate.ts` if hand-writing is slower than scripting. Also `src/mocks/cities.json` and `src/mocks/job.json`.
5. `src/lib/api.ts`: `analyze()`, `getJob()`, `getCities()`, `getCity()` typed against `types.ts`. When `NEXT_PUBLIC_USE_MOCK=1`, return the mocks (and make `getJob()` advance one step per call so the progress screen can be developed).

Done when: `npm run dev` serves a blank page with no type errors and the mock loads.

---

## Phase 1: hours 0.5 to 4 · checkpoint "map on fake hexes"

Goal: `/city/[slug]` renders the mock hexes on a Google map, colored by band.

1. **`src/app/layout.tsx`**: wrap in `APIProvider` from `@vis.gl/react-google-maps` with the key. Global styles only.
2. **`src/components/HexMap.tsx`**: a `Map` from the react wrapper centered on `summary.center`, zoom about 12. Inside, a small child component uses `useMap()` to create one `GoogleMapsOverlay`, calls `setMap`, and updates `setProps({layers: [...]})` whenever hexes or the selected hex change. One `H3HexagonLayer` with `getHexagon: d => d.h3`, `getFillColor` by band (alpha around 140), `getLineColor` and `lineWidthMinPixels` for outlines, `pickable: true`, `onClick` to lift the selected hex to the parent. A second thin layer, or a highlight color, for the selected hex. Novel hexes get a visible marker: simplest is a second `H3HexagonLayer` filtered to `novel.length > 0` with a thick dashed-looking outline or a dark border.
3. Start with the default raster map (no `mapId`). If hexes flicker or z-fight with the basemap, create a vector Map ID in the Google console and pass it as `mapId`.
4. **`src/app/city/[slug]/page.tsx`**: client component. Loads the result via `api.getCity(slug)` and renders `HexMap` full-height with a right-hand panel placeholder. Legend in a corner with the three bands and the thresholds.
5. **`src/components/Legend.tsx`**: three swatches with "< 80", "80 to 95", "≥ 95" and the phrase "more unusual than X% of Phoenix areas".

Done when: the mock's red hexes are visibly red, clicking one logs its `h3`, and the page survives a reload.

---

## Phase 2: hours 4 to 6 · checkpoint "why panel + search"

1. **`src/components/WhyPanel.tsx`**: shows the selected hex's `shift_score` with the sentence "more unusual than {shift_score}% of Phoenix areas", the band chip, and a three-row table of `top_features`: human name, `value`, `ref_median` (label it "Phoenix median"), `z`, `pct`. Below it, a warning block listing `novel` entries when non-empty. Human names come from a small `FEATURE_LABELS` map in `constants.ts` covering all 17 `HEX_FEATURES` (for example `intersection_density` → "Intersections / km²").
2. **`src/components/SearchBox.tsx`** on `src/app/page.tsx`: input with Places Autocomplete restricted to cities, fields `geometry`, `name`, `formatted_address`, `address_components`. On selection, build `{name: formatted_address, lat, lng, country_code}` where `country_code` is the `short_name` of the `country` address component. If Autocomplete is unavailable (see guardrails), a text input and a `Geocoder.geocode({address})` call produce the same object.
3. **`/` page layout**: hero line with the tagline, the search box, and below it a "Cities we've already analyzed" list from `api.getCities()`, each linking to `/city/[slug]`. This list is the backup demo path, so make it work on the mock now.
4. On search: call `api.analyze()`, then `router.push('/city/' + slug + '?job=' + job_id)`.

Done when: selecting a mock hex fills the why panel with the right numbers, and searching navigates to the city route with a `job` query param.

---

## Phase 3: hours 6 to 8 · checkpoint "progress screen wired to API"

Goal: switch `NEXT_PUBLIC_USE_MOCK` off and run one real city from search to map.

1. **`src/components/ProgressScreen.tsx`**: five rows from `JOB_STEPS` with the labels "Pulling road network", "Pulling infrastructure and places", "Pulling five years of weather", "Scoring against Phoenix", "Building scenarios". A row is done if its step is in `steps_done`, active if it equals `step`, pending otherwise. Show `message` under the active row when present. On `status = "error"`, show `error` in red and a "Back to search" link.
2. **`/city/[slug]` state machine**: on mount, call `getCity(slug)`. If 200, render results. If 404 and a `job` query param exists, poll `getJob(job)` every `POLL_MS` until `done` or `error`; on `done`, call `getCity(slug)` again and render. If 404 with no job param, show "This city hasn't been analyzed yet" with a link to `/`. Clean up the interval on unmount.
3. Set `NEXT_PUBLIC_USE_MOCK=0`, point at P1's API, run Phoenix (should be instant and `cached`), then a new city.
4. Note every mismatch between the real API and your types. If the API differs from the contract, that is P1's bug; tell them. If your type differs from the contract, fix your type.

Done when: a judge-style flow works end to end on a real uncached city with no manual steps and no console errors.

---

## Phase 4: hours 8 to 12 · checkpoint "comparison view + scenario cards"

1. **`src/components/ScenarioCards.tsx`**: one card per scenario in API order (already sorted by priority). Card shows rank, `title`, `description`, `scope` chip ("city-wide" or "N hexes"), and a "Triggered by" list from `triggered_by`. Hovering or clicking a card highlights its `hex_ids` on the map (lift the highlighted set to the page and pass it to `HexMap` as a third layer or as a color override). City-scope cards highlight nothing.
2. **`src/components/ComparisonView.tsx`**: three blocks. Climate: three paired bars (target vs Phoenix) for rain days, heavy-rain days, snow days. Context: driving side (with a "Left-hand traffic" warning chip when `novel_city` includes it), `osm_completeness` as a percentage with the label "OSM completeness", and a "Snow" chip when `novel_city` includes it. Biggest shifts: the top 6 rows of `feature_comparison` sorted by `|log(target / reference)|`, shown as target vs Phoenix medians with a ratio. Skip rows where reference is 0 to avoid division by zero.
3. **`src/components/StreetViewPanel.tsx`** (cut candidate number 3, so keep it self-contained): when a hex is selected, compute its center with `cellToLatLng`, call `StreetViewService.getPanorama({location, radius: 100})`; if found, render a `StreetViewPanorama` in a fixed-height box under the why panel; if not, show "No Street View here". Do not let a Street View failure break the panel.
4. **Panel layout**: right column with tabs or stacked sections in this order: Why (selected hex, with Street View), Comparison, Scenarios. Default to Comparison when no hex is selected. The map keeps at least 60% of the width on a laptop screen.
5. **Summary strip** above the map: city name, `n_hexes`, `pct_red` as "X% of areas differ strongly from Phoenix".
6. Take screenshots of New York and London for P2's slides: map, a red hex's why panel, comparison, cards.

Done when: every scenario card lists its triggers and highlights its hexes, the comparison view renders for a city with zero snow and a city with snow, and Street View appears for at least one hex.

---

## Phase 5: hours 12 to 14 (all three) · checkpoint "validation numbers ready"

- Open Phoenix, Tucson, New York and London from the cached list. Phoenix should look mostly green, Tucson mostly green with a little yellow, New York and London heavily yellow and red. If the UI disagrees with `validate.py` numbers, the bug is in rendering; fix it.
- Check the legend, the summary strip and the why-panel sentence read correctly for a non-expert. Judges will read them aloud.
- Bug fixes only. Cut Street View or comparison polish now if either is unstable (contract cut order).

---

## Last 4 hours (all three) · checkpoint "submitted"

- Feature freeze. Record the demo video in `demo/`: follow the 2.5-minute script in SOURCE-PLAN.md section 10 beat for beat (hook, Phoenix reference, "name any city" with the progress steps ticking, heatmap and red hex with Street View, comparison, cards, tagline). Record the live path once and the cached backup once; use whichever is cleaner.
- Confirm the app runs from a clean `npm install && npm run dev` against P1's README instructions.
- Rehearse three times with the team, driving the UI yourself. Know exactly which cached city you open if the live run is slow.

---

## Component and route map

```
src/app/layout.tsx                 APIProvider + global styles
src/app/page.tsx                   tagline, SearchBox, cached cities list
src/app/city/[slug]/page.tsx       state machine: cached | polling | error | results
src/components/SearchBox.tsx
src/components/ProgressScreen.tsx
src/components/HexMap.tsx          Map + GoogleMapsOverlay + H3HexagonLayer(s)
src/components/Legend.tsx
src/components/WhyPanel.tsx
src/components/StreetViewPanel.tsx
src/components/ComparisonView.tsx
src/components/ScenarioCards.tsx
src/lib/api.ts                     typed fetchers, mock switch
src/lib/types.ts                   contract 4.1 + 4.2 as TS types
src/lib/constants.ts               API_BASE, POLL_MS, JOB_STEPS, bands, colors, FEATURE_LABELS
src/mocks/                         result.json, cities.json, job.json, generate.ts
```

## Hand-offs at a glance

| Hour | You give | To | You get | From |
|------|----------|----|---------|------|
| 0.5 | Confirmation of API shapes | P1 | Frozen contract | All |
| 8 | End-to-end confirmation | P1 | API on :8000 | P1 |
| 12 | Screenshots for slides | P2 | Scenario cards in `result.json` | P2 via P1 |
| Last 4 | Demo video | All | Final slides | P2 |
