# CityShift

Enter any city. CityShift shows where its driving environment differs from selected benchmark environments in Phoenix, San Francisco, Los Angeles, Austin, and Atlanta, then turns those differences into prioritized test scenarios using public data.

*Waymax tests the scenario. CityShift finds the scenario worth testing.*

[Read the full project overview (PDF)](output/pdf/CityShift_Project_Overview.pdf)

## Project overview

CityShift is a decision-support tool for early research, simulation planning, and new-city preparation. It combines public road, infrastructure, activity, weather, terrain, and crash data into a repeatable view of local driving differences.

The project answers one practical question: **What is different about driving here, where does it happen, and what should be tested first?**

### How a city analysis works

1. **Search:** Select a city through place search.
2. **Divide:** Split an 8 km radius into H3 resolution-8 hexagons, about 0.74 km2 each.
3. **Measure:** Convert public datasets into consistent road, infrastructure, activity, and climate metrics.
4. **Compare:** Compare each usable hex with 1,153 pooled reference hexes from the five benchmark cities.
5. **Prioritize:** Turn unusual conditions into ranked candidate scenarios with locations and supporting evidence.

The reference cities are project-selected benchmark environments, not an official statement of Waymo's current operating footprint.

### What CityShift measures

| Area | Signals |
|------|---------|
| Road network | Intersection density, road density, arterial share, motorway share, one-way share |
| Traffic control | Signal density and crosswalk density |
| Mobility | Bike-lane density and transit-stop density |
| Local activity | School, nightlife, and tourism density |
| Infrastructure | Bridges, movable bridges, tunnels, roundabouts, and stadiums |
| Climate and context | Rain, heavy rain, snow, terrain slope, driving side, average lanes, and map-data completeness |

Terrain slope and average lane count are shown as context but do not currently affect the Shift score. Weather is measured at city level rather than per hex.

### How to read a Shift score

A Shift score describes **difference, not danger**. Each mapped hex includes its three strongest differences, with the local value, benchmark median, statistical distance, and benchmark percentile.

| Score | Map label | Meaning |
|------:|-----------|---------|
| Below 80 | Within baseline | Similar to the benchmark distribution |
| 80 to 94.9 | Notable shift | Meaningfully different and worth reviewing |
| 95 or higher | Strong shift | More unusual than at least 95% of reference areas |

Rare features that cannot be scored reliably are marked as novel. Scenario priority grows with both the strength of a difference and the number of affected hexes, helping distinguish isolated conditions from patterns that may deserve broader testing.

### What the product provides

- An interactive, color-coded H3 map with exact affected locations.
- A Why panel that explains the evidence behind a selected hex.
- City-to-benchmark comparisons and ranked scenario cards.
- Separate US fatal-crash context from NHTSA FARS.
- Downloadable city briefings and evidence-grounded chat.
- Safe Journey, a rider-facing route prototype with fastest, balanced, and lower-exposure options.

Safe Journey is designed around clear choices and visible tradeoffs, including the needs of older adults who may prefer a more predictable route. Historical crash exposure is not a prediction that a crash will occur, and a lower-exposure route is not guaranteed to be safer. The feature supports transparency and rider comfort; it does not replace current road conditions, accessibility needs, emergency guidance, or validated safety systems.

### Intended use and limits

CityShift can narrow the search space for new-market screening, simulation-suite creation, regression testing, mapping and data collection, on-road test planning, and safety-review preparation. Candidate scenarios still require expert validation before they inform safety decisions or deployment.

Important limitations:

- A high Shift score means different, not automatically dangerous; a low score does not prove an area is safe.
- Public map data may be incomplete or outdated.
- Fatal-crash context is US-only and is not normalized by population or traffic volume.
- The analysis covers an 8 km radius around the selected city center.
- CityShift does not replace Waymo's internal maps, telemetry, simulation, validation, or operational judgment.

## Start here

Give your coding agent, in order: `contracts/CONTRACTS.md` (single source of truth, frozen at hour 0.5), `contracts/SOURCE-PLAN.md` (background, demo, Q&A; the contract wins on conflicts), then your plan in `plans/`. Instruction: "Read the contract first, then the source plan, then my plan. Follow my plan phase by phase. Only touch files my plan says I own."

| Person | Plan | Owns |
|--------|------|------|
| P1 | `plans/P1-DATA-AND-API.md` | `backend/` except `backend/app/model/`, plus `cache/`, this README |
| P2 | `plans/P2-MODEL-SCENARIOS-PITCH.md` | `backend/app/model/`, `backend/tests/fixtures/`, model scripts, `pitch/` |
| P3 | `plans/P3-FRONTEND.md` | `frontend/`, `demo/` |

## Environment

Both apps and the backend scripts load the single `.env` in the repository root. For a new checkout, copy `.env.example` to `.env` and fill in `GOOGLE_MAPS_KEY` and `GEMINI_API_KEY`. Existing shell or deployment variables take precedence. Restart both servers after changing `.env`; production frontend builds need to be rebuilt when browser settings change.

The root `.env` is git-ignored. Gemini settings stay on the server; the Google Maps browser key and `NEXT_PUBLIC_*` settings are included in the frontend bundle.

## Backend (P1, P2)

Python 3.11 (macOS: `brew install python@3.11`). All commands run from `backend/`.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate          # Windows Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt
python -c "import h3, osmnx; print(h3.__version__, osmnx.__version__)"   # expect 4.x and 2.x
```

```bash
uvicorn app.main:app --port 8000                                                  # API, CORS for localhost:3000
python scripts/run_city.py "Phoenix, AZ, USA" 33.4484 -112.0740 --country US      # features for one city
python scripts/precache.py              # all demo cities; add --data-only before P2's model exists
python scripts/precache.py --rescore    # after a model/scenario change: re-score cached cities, offline
python scripts/precache.py --cities data/saved_cities.json   # the saved city list instead of the demo cities
python scripts/prebuild_routes.py       # Safe Journey road graphs for every US city, so /ride opens without a download
```

Smoke test (API running):

```bash
curl -X POST localhost:8000/analyze -H 'content-type: application/json' \
  -d '{"name":"Phoenix, AZ, USA","lat":33.4484,"lng":-112.074,"country_code":"US"}'   # cached: true
curl localhost:8000/jobs/<job_id>
curl localhost:8000/cities
curl localhost:8000/cities/phoenix-az-usa
```

Slugs come from the `name` sent to `POST /analyze`. Send Google Places' formatted address ("New York, NY, USA", "London, UK") to hit the pre-cached cities.

Data: OpenStreetMap (ODbL) via OSMnx; weather from Open-Meteo (CC BY 4.0); terrain context in the UI from Google Elevation, not scored; Crash data: NHTSA FARS 2020-2024 (2024 preliminary), display only (`scripts/build_fars_extract.py` rebuilds `backend/data/`, `scripts/build_crashes.py` writes `cache/*/crashes.json`). Open-Meteo responses are cached in `backend/openmeteo_cache/` (free tier: 10,000 calls a day; a 5-year weather pull is ~130).

OSM downloads try Overpass, Private.coffee, then VK Maps, with a 300-second deadline per server attempt, up to three attempts for temporary HTTP errors, and automatic failover. Road queries start with a 60-second / 128 MiB server resource allowance and retry at 180 seconds / 512 MiB if the server reports that the smaller budget was exceeded. Infrastructure uses a compact query over the same 8 km area and tags, increasing its resource budget when needed. These settings apply to new-city searches and batch downloads; successful results are saved for later searches. Before requesting roads, the downloader checks all configured mirrors and the old/new query budgets for an identical cached road selection, so routing reuses earlier analysis downloads. To use your own server list, launch with `CITYSHIFT_OVERPASS_URLS="https://your-server/api" uvicorn app.main:app --port 8000` (comma-separated URLs, in priority order). Public-server outages still require a reachable mirror or an already cached city.

## Frontend (P3)

Node 20. Configure the root `.env` as described above, then run `npm ci` and `npm run dev` from `frontend/`. No separate frontend environment file is needed.

## Layout

See `contracts/CONTRACTS.md` section 2. `cache/{slug}/` holds `features.csv`, `city.json`, `meta.json`, `result.json` and is committed for demo cities. `backend/osmnx_cache/` is OSMnx's raw HTTP cache and is git-ignored.
