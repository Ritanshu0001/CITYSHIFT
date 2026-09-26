# CityShift: Design Decisions and Locked Contracts

Source: the team plan "CityShift: full plan" (Sep 26, 2026), kept verbatim as `contracts/SOURCE-PLAN.md` for background, the demo script and the Q&A answers. This file is the single source of truth for everything shared between P1 (Data + API), P2 (Model + Scenarios + Pitch) and P3 (Frontend).

- This file lives at `contracts/CONTRACTS.md` in the skeleton repo.
- It is **frozen at hour 0.5**. After that it changes only with all three people present.
- Where `SOURCE-PLAN.md` and this file differ, this file wins. The source plan is context, not a spec.
- Every coder gives their agent three files: this one, `SOURCE-PLAN.md`, and their own plan from `plans/`. The agent reads this file first.

Product framing (do not drift from it): CityShift uses public data to find driving environments that differ from a reference city (Phoenix) and turns those differences into candidate test scenarios. Never claim Waymo lacks this or that we teach Waymo to drive. Tagline: "Waymax tests the scenario. CityShift finds the scenario worth testing."

---

## 1. Design decisions

Each decision has a one-line reason. These are settled. Do not re-open them during the build.

| # | Decision | Why |
|---|----------|-----|
| D1 | **Monorepo with three top-level directories** (`backend/`, `frontend/`, `contracts/`) and strict per-person ownership (see section 2). | Three agents working in parallel must never edit the same file. Ownership by directory is easy to enforce. |
| D2 | **Files on disk are the integration point between P1 and P2.** P1 writes `features.csv` + `city.json`; P2 reads them and returns Python dicts that match the result JSON. | P2 can develop against a fake CSV from minute one. P1 can test the data pipeline without the model. Neither blocks the other. |
| D3 | **P1 owns the orchestrator (`pipeline.py`) and calls three P2 functions by fixed signature** (section 4.4). P2 never edits `pipeline.py`; P1 never edits `backend/app/model/`. | One clear seam. If P2's code is not ready, P1's pipeline still runs the data half. |
| D4 | **The Phoenix reference model is a saved artifact committed to the repo.** Fit once by P2, loaded by everyone. | Scoring must be identical on every laptop, and nobody should need to refit during the demo. |
| D5 | **Job runner is one in-process thread and a dict.** No Redis, no Celery, no database. One job runs at a time; extra requests queue. | Demo runs on a laptop. Anything heavier is time spent on infrastructure instead of the product. |
| D6 | **The cache directory is the source of truth.** `GET /cities/{slug}` reads `cache/{slug}/result.json`. Demo cities' `result.json`, `features.csv` and `city.json` are committed to git. OSMnx's own HTTP cache is git-ignored. | Instant repeat requests, and the backup demo works on any machine with the repo cloned. |
| D7 | **Frontend is mock-first.** `NEXT_PUBLIC_USE_MOCK=1` serves a local `result.json` that matches the contract exactly. | P3 builds the whole UI on hour 0 without waiting for P1 or P2. |
| D8 | **Fixed geometry for every city: 8 km radius, H3 resolution 8, drop hexes with under 0.5 km of road.** Constants live in `backend/app/schemas.py`. | Same-size areas make the Phoenix comparison fair. If the radius must shrink for speed, it shrinks for every city and P2 refits Phoenix. |
| D9 | **Scoring is exactly what SOURCE-PLAN.md section 5 says:** `log1p`, `StandardScaler`, `IsolationForest(random_state=42)`, percentile against Phoenix's own scores. Rare features (present in under 1% of Phoenix hexes) skip the model and become "novel" flags. | Phoenix vs itself lands at about 5% red by construction, which is the answer to the judges' "does the score mean anything" question. |
| D10 | **Scenarios come from the fixed rule table in SOURCE-PLAN.md section 6, restated in section 4.7 below. No LLM in the core path.** LLM polish is a stretch goal, off by default. | Every card must show exactly what triggered it. Deterministic output means no demo surprises. |
| D11 | **Tech pins:** Python 3.11 + venv + pip; Node 20 LTS + npm; Next.js App Router + TypeScript; `@vis.gl/react-google-maps` for the map; `@deck.gl/google-maps` `GoogleMapsOverlay` + `@deck.gl/geo-layers` `H3HexagonLayer` for hexes; `h3` **v4** Python API (`latlng_to_cell`, `grid_disk`, `cell_area`). | Removes every "which library" debate. The h3 v3/v4 naming difference is the most common source of agent hallucination in this stack, so v4 is named explicitly. |
| D12 | **Trunk-based git.** Everyone commits small and often to `main`, `git pull --rebase` before every push. No long-lived branches. | Directory ownership makes conflicts nearly impossible, and branches add merge time a hackathon does not have. |
| D13 | **Shared files have a single owner and are append-only after hour 0.5:** `contracts/CONTRACTS.md` (all three, frozen), `backend/app/schemas.py` (P1 writes from this contract, then frozen), `backend/requirements.txt` (P1 writes the full list at hour 0; P2 may append lines only), `README.md` (P1). | Append-only files never produce merge conflicts. |
| D14 | **Frontend routing:** `/` (search + cached-cities list), `/city/[slug]` (progress screen while a job runs, then map + panels). The slug is in the URL so a cached city is one link away for the backup demo. | The "here's one we ran earlier" fallback in SOURCE-PLAN.md section 10 must be a single click. |
| D15 | **Driving side:** frontend sends an optional `country_code` from Google Places; backend falls back to a reverse-geocode lookup, then to `"right"`. Left-hand-traffic list is a static table in P1's code. | SOURCE-PLAN.md section 3 calls for a small country lookup table. This keeps it off the network in the demo path. |
| D16 | **Weather:** Open-Meteo Historical Weather API, daily `precipitation_sum` and `snowfall_sum`, 2020-01-01 to 2024-12-31. Rain day = precipitation ≥ 1 mm. Heavy-rain day = ≥ 20 mm. Snow day = snowfall ≥ 1 cm. All reported as days per year (total ÷ 5). | Matches the thresholds in SOURCE-PLAN.md section 4 and adds the missing snow threshold so P1 and P2 compute the same number. |

Three small additions to the contract in SOURCE-PLAN.md section 7, made so the three parts fit together. Accept or reject them at hour 0, then freeze:

1. `POST /analyze` always returns the same shape (`job_id`, `slug`, `status`, `cached`) instead of "a job ID or the cached result". One response shape means one frontend code path.
2. `summary` gains `slug` and `novel_city` (SOURCE-PLAN.md section 5 mentions city-level novel flags but section 7 leaves them out of the summary shape).
3. `POST /analyze` accepts an optional `country_code`.

---

## 2. Repository layout and ownership

```
cityshift/
  README.md                      P1
  .gitignore                     P1
  contracts/
    CONTRACTS.md                 ALL (this file, frozen at 0.5h)
    CHANGE_REQUESTS.md           ALL (append-only; see section 6)
$1
  plans/
    P1-DATA-AND-API.md           P1 (read-only after 0.5h)
    P2-MODEL-SCENARIOS-PITCH.md  P2 (read-only after 0.5h)
    P3-FRONTEND.md               P3 (read-only after 0.5h)
  backend/
    requirements.txt             P1 (P2 may append)
    app/
      __init__.py                P1
      schemas.py                 P1 (from this contract, then frozen)
      main.py                    P1   FastAPI app + routes
      jobs.py                    P1   job registry + background thread
      pipeline.py                P1   analyze_city orchestrator
      cache.py                   P1   slugify, paths, read/write
      data/                      P1
        grid.py                       H3 grid for a center + radius
        osm.py                        OSMnx pulls + Overpass fallback
        weather.py                    Open-Meteo
        driving_side.py               country -> left/right
        features.py                   feature table builder
      model/                     P2
        reference.py                  fit + save Phoenix reference
        scoring.py                    score_city()
        summary.py                    build_summary()
        scenarios.py                  build_scenarios()
        reference/                    saved artifact (committed)
          phoenix_reference.joblib
          reference_meta.json
    scripts/
      run_city.py                P1   CLI: features for one city
      precache.py                P1   run demo cities
      make_fake_features.py      P2   fixtures generator
      fit_reference.py           P2   fit + save artifact
      validate.py                P2   validation table for slides
    tests/
      fixtures/                  P2   fake_phoenix_features.csv, fake_target_features.csv, fake_city.json
  cache/                         P1 (generated; demo cities committed)
    {slug}/
      meta.json
      features.csv
      city.json
      result.json
  frontend/                      P3 (everything under it)
  pitch/                         P2   slides, Q&A card, Devpost text
  demo/                          P3   demo video + script
```

Hard rules:

- You only create or edit files in directories marked with your name.
- If you need something in another person's directory, write the request to `contracts/CHANGE_REQUESTS.md` (section 6) and keep working with a local stub in your own directory.
- `cache/` is written by P1's code only. P2's scripts read from it and write results through P1's `cache.py` helpers or to `backend/tests/fixtures/`.

---

## 3. Fixed constants

Defined once in `backend/app/schemas.py` and mirrored in `frontend/src/lib/constants.ts`.

| Name | Value |
|------|-------|
| `RADIUS_KM` | 8 |
| `H3_RES` | 8 |
| `MIN_ROAD_KM` | 0.5 (hexes with less road are dropped) |
| `WEATHER_START`, `WEATHER_END` | `2020-01-01`, `2024-12-31` |
| `RAIN_MM`, `HEAVY_RAIN_MM`, `SNOW_CM` | 1.0, 20.0, 1.0 |
| `RARE_PRESENCE_THRESHOLD` | 0.01 (feature present in under 1% of Phoenix hexes is rare) |
| `BAND_YELLOW`, `BAND_RED` | 80, 95 (score < 80 green; 80 to 95 yellow; ≥ 95 red) |
| `TOP_FEATURES_N` | 3 |
| `JOB_STEPS` | `["roads", "infrastructure", "weather", "scoring", "scenarios"]` (exact order and spelling) |
| `REFERENCE_SLUG` | `phoenix-az-usa` |
| `REFERENCE_CENTER` | lat 33.4484, lng -112.0740 |
| `ISOFOREST_SEED` | 42 |
| `NOVEL_Z_EQUIVALENT` | 3.0 (used in scenario priority for novel triggers) |

Slug rule: lowercase the city name, replace every run of non-alphanumeric characters with a single hyphen, strip leading and trailing hyphens. `"Phoenix, AZ, USA"` → `phoenix-az-usa`. `"London, UK"` → `london-uk`. The frontend never computes slugs; it uses the one the API returns.

---

## 4. Contracts

### 4.1 HTTP API (P1 serves, P3 consumes)

Base URL in dev: `http://localhost:8000`. CORS allows `http://localhost:3000`.

| Endpoint | Request | Response |
|----------|---------|----------|
| `POST /analyze` | `{"name": str, "lat": float, "lng": float, "country_code": str \| null}` | `200 {"job_id": str, "slug": str, "status": "queued" \| "running" \| "done", "cached": bool}`. If the city is already cached: `status = "done"`, `cached = true`, and `job_id` is still a valid id whose `GET /jobs/{id}` returns `done`. |
| `GET /jobs/{id}` | | `200 {"job_id": str, "slug": str, "status": "queued" \| "running" \| "done" \| "error", "step": str \| null, "steps_done": [str], "message": str \| null, "error": str \| null}`. `step` and `steps_done` values come from `JOB_STEPS`. `404` if unknown id. |
| `GET /cities` | | `200 {"cities": [{"slug": str, "name": str, "center": {"lat": float, "lng": float}, "n_hexes": int, "pct_red": float, "created_at": str}]}` sorted by name. |
| `GET /cities/{slug}` | | `200 CityResult` (4.2). `404 {"detail": "not cached"}` if missing. |

Frontend polling interval: 1500 ms.

### 4.2 `CityResult` JSON (P2 produces, P1 serves, P3 renders)

```json
{
  "hexes": [
    {
      "h3": "8829a1d6dbfffff",
      "shift_score": 97.4,
      "band": "red",
      "top_features": [
        {"name": "intersection_density", "value": 88.1, "ref_median": 31.2, "z": 3.1, "pct": 99.2},
        {"name": "signal_density",       "value": 14.9, "ref_median":  4.1, "z": 2.4, "pct": 97.0},
        {"name": "crosswalk_density",    "value": 21.3, "ref_median":  6.8, "z": 2.0, "pct": 94.1}
      ],
      "novel": ["movable_bridge_count"]
    }
  ],
  "summary": {
    "city": "New York, NY, USA",
    "slug": "new-york-ny-usa",
    "center": {"lat": 40.7128, "lng": -74.0060},
    "radius_km": 8,
    "n_hexes": 265,
    "pct_red": 41.5,
    "climate": {
      "target":    {"rain_days_per_year": 120.4, "heavy_rain_days_per_year": 6.2, "snow_days_per_year": 11.0},
      "reference": {"rain_days_per_year":  33.0, "heavy_rain_days_per_year": 0.6, "snow_days_per_year":  0.0}
    },
    "driving_side": "right",
    "feature_comparison": [
      {"name": "intersection_density", "target": 60.2, "reference": 31.2}
    ],
    "osm_completeness": 0.42,
    "novel_city": ["snow"]
  },
  "scenarios": [
    {
      "id": "rain_dense_intersection",
      "priority": 87.3,
      "title": "Heavy rain at a dense signalized intersection with a pedestrian crossing",
      "description": "New York has 3.6x Phoenix's rain days. 31 hexes have intersection density above z = 2.",
      "triggered_by": ["heavy_rain_days_per_year 10.3x reference", "intersection_density z > 2 in 31 hexes"],
      "hex_ids": ["8829a1d6dbfffff"],
      "scope": "hex"
    }
  ]
}
```

Field rules:

- `shift_score`: float 0 to 100, one decimal. `band`: `"green" | "yellow" | "red"` from `BAND_YELLOW` / `BAND_RED`.
- `top_features`: at most 3, sorted by `|z|` descending, only from modeled (non-rare) features. `z` is computed on `log1p` values. `pct` is the percentile of the raw value among Phoenix hexes.
- `novel`: rare-feature names with value > 0 in this hex. May be empty. Frontend draws a warning marker when non-empty.
- `feature_comparison`: one row per hex feature in `HEX_FEATURES` order, values are medians over hexes (target city vs Phoenix).
- `novel_city`: subset of `["snow", "left_hand_traffic"]`.
- `scenarios`: sorted by `priority` descending. `scope = "city"` means `hex_ids` is empty and the card applies to the whole city. `id` values are the keys in section 4.7.
- `driving_side`: `"left" | "right"`.

### 4.3 Feature table on disk (P1 writes, P2 reads)

`cache/{slug}/features.csv`, one row per kept hex. Column order is fixed. All densities are per km² of hex area. All shares are fractions 0 to 1 of road length.

| Column | Group | Definition |
|--------|-------|------------|
| `h3` | key | H3 cell id (string) |
| `area_km2` | helper | `h3.cell_area(h3, unit="km^2")` |
| `road_km` | helper | sum of drive-network edge lengths whose midpoint is in the hex, in km |
| `intersection_density` | Network | graph nodes with `street_count >= 3` in hex ÷ area |
| `road_density` | Network | `road_km ÷ area_km2` |
| `arterial_share` | Road mix | length with `highway` in {primary, secondary, tertiary, and their `_link`} ÷ road_km |
| `motorway_share` | Road mix | length with `highway` in {motorway, trunk, and their `_link`} ÷ road_km |
| `oneway_share` | Road mix | length with `oneway == True` ÷ road_km |
| `signal_density` | Control | `highway=traffic_signals` points ÷ area |
| `crosswalk_density` | Control | `highway=crossing` points ÷ area |
| `bike_lane_density` | VRU | `highway=cycleway` line length (km) ÷ area |
| `transit_stop_density` | VRU | count of `highway=bus_stop` + `public_transport=platform|station` + `railway=station|tram_stop` ÷ area |
| `school_density` | Activity | `amenity=school` ÷ area |
| `nightlife_density` | Activity | `amenity=bar|pub|nightclub` ÷ area |
| `tourism_density` | Activity | `tourism=hotel|attraction` ÷ area |
| `bridge_count` | Infra (rare) | edges with a truthy `bridge` tag (count) |
| `movable_bridge_count` | Infra (rare) | edges with `bridge=movable` (count) |
| `tunnel_count` | Infra (rare) | edges with a truthy `tunnel` tag (count) |
| `roundabout_count` | Infra (rare) | edges with `junction=roundabout` (count) |
| `stadium_count` | Infra (rare) | `leisure=stadium` features (count) |
| `avg_lanes` | Optional | mean numeric `lanes` over edges that have it; empty if none |

Assignment rules: edges by midpoint, point features by location, polygon features by centroid. Lists in OSM tags (e.g. `highway=['primary','residential']`) take the first value.

`HEX_FEATURES` (the 17 columns from `intersection_density` to `stadium_count`, in that order) is the list P2 models. `avg_lanes` is never modeled; it appears in `feature_comparison` only when both cities have it.

`cache/{slug}/city.json`:

```json
{
  "name": "Phoenix, AZ, USA", "slug": "phoenix-az-usa",
  "lat": 33.4484, "lng": -112.0740, "radius_km": 8,
  "country_code": "US", "driving_side": "right",
  "rain_days_per_year": 33.0, "heavy_rain_days_per_year": 0.6, "snow_days_per_year": 0.0,
  "osm_completeness": 0.71,
  "n_hexes_total": 271, "n_hexes_kept": 248,
  "created_at": "2026-09-26T18:02:11Z"
}
```

`osm_completeness` = fraction of drive-network edges (by count) that carry a `maxspeed` or `lanes` tag.

### 4.4 Python boundary (P2 implements, P1 calls)

P1's `pipeline.py` imports exactly these three functions. P2 guarantees the names, argument order and return shapes. Return values are plain dicts and lists that serialize to the JSON in 4.2 with no further transformation.

```python
# backend/app/model/scoring.py
def score_city(features: "pd.DataFrame", city: dict) -> list[dict]:
    """features: the features.csv as a DataFrame (h3 as a column, not index).
    city: the city.json dict. Returns hexes[] per section 4.2."""

# backend/app/model/summary.py
def build_summary(features: "pd.DataFrame", city: dict, hexes: list[dict]) -> dict:
    """Returns summary per section 4.2."""

# backend/app/model/scenarios.py
def build_scenarios(features: "pd.DataFrame", city: dict, hexes: list[dict], summary: dict) -> list[dict]:
    """Returns scenarios[] per section 4.2, sorted by priority desc."""
```

The Phoenix reference artifact is loaded lazily inside P2's module on first call. P1 never loads it. If the artifact is missing, `score_city` raises `FileNotFoundError` with a clear message; P1 catches it, marks the job `error`, and the message reaches the UI.

### 4.5 Reference artifact (P2 owns)

`backend/app/model/reference/phoenix_reference.joblib` is a dict with keys: `feature_order` (list of modeled column names), `rare_features` (list), `scaler` (fitted StandardScaler), `iforest` (fitted IsolationForest), `phoenix_scores_sorted` (numpy array), `phoenix_log_mean`, `phoenix_log_std` (arrays aligned to `feature_order`), `phoenix_raw` (DataFrame of Phoenix modeled columns for percentiles and medians), `phoenix_city` (the Phoenix `city.json` dict). `reference_meta.json` is the human-readable copy of everything except the fitted objects, plus `fit_timestamp` and `n_hexes`.

### 4.6 Scoring algorithm (P2 implements; stated here so P1 and P3 can sanity-check numbers)

1. Rare detection: for each column in `HEX_FEATURES`, presence rate = share of Phoenix hexes with value > 0. If below `RARE_PRESENCE_THRESHOLD`, the feature is rare and excluded from steps 2 to 5.
2. Transform: `log1p` on modeled columns, then the saved `StandardScaler`.
3. Anomaly score = `-iforest.score_samples(X)` (higher = more unusual).
4. `shift_score` = percentage of Phoenix scores strictly below this hex's score (searchsorted on `phoenix_scores_sorted`), rounded to one decimal.
5. `z` per feature = (log1p(value) − phoenix_log_mean) ÷ phoenix_log_std. Top 3 by |z|.
6. `novel` = rare features with value > 0 in the target hex.
7. City-level: `pct_red` = share of hexes with band red × 100. `novel_city` includes `"snow"` if target `snow_days_per_year ≥ 2` and reference `< 1`; includes `"left_hand_traffic"` if `driving_side == "left"`.

Expected sanity result: Phoenix scored against itself gives `pct_red ≈ 5`.

### 4.7 Scenario rules (P2 implements; the table is the spec)

`priority = z_mag × n_hexes_affected`. `z_mag` = mean |z| of the triggering feature over affected hexes; for novel triggers `z_mag = NOVEL_Z_EQUIVALENT`. For `scope = "city"`, `n_hexes_affected = n_hexes`. "Much rainier" = target `rain_days_per_year ≥ 2 ×` reference.

| `id` | Trigger | Title | Scope |
|------|---------|-------|-------|
| `movable_bridge` | any hex with `movable_bridge_count` in `novel` | Queue at an opening bridge + adjacent lane change | hex |
| `rain_dense_intersection` | much rainier city AND hexes with `intersection_density` z > 2 | Heavy rain at a dense signalized intersection with a pedestrian crossing | hex |
| `crosswalk_wide_arterial` | hexes with `crosswalk_density` z > 2 AND `arterial_share` z > 1 | Pedestrian crossing a wide arterial | hex |
| `cyclist_complex_intersection` | hexes with `bike_lane_density` z > 2 AND `intersection_density` z > 2 | Cyclist at a complex intersection (car turning across a cyclist) | hex |
| `late_night_pedestrians` | hexes with `nightlife_density` z > 2 | Late-night pedestrian activity | hex |
| `stadium_event` | hexes with `stadium_count` > 0 | Event crowd leaving + rideshare pickup congestion | hex |
| `bus_in_lane` | hexes with `transit_stop_density` z > 2 | Bus stopping in lane and pulling out | hex |
| `snow_traction` | `"snow"` in `novel_city` | Reduced traction + hidden lane markings | city |
| `left_hand_traffic` | `"left_hand_traffic"` in `novel_city` | Mirrored turn logic; turns across oncoming traffic | city |
| `roundabout_or_tunnel` | any hex with `roundabout_count` or `tunnel_count` in `novel` | Multi-lane roundabout entry; GPS loss and lighting change in a tunnel | hex |

A rule with zero affected hexes produces no card. `description` is a static template filled with the numbers in `triggered_by`.

---

## 5. Anti-hallucination rules for every agent

1. **Only the fields, endpoints, file names and function signatures in this document exist.** If you need one that is not here, do not invent it. Write it to `contracts/CHANGE_REQUESTS.md` and continue with a local stub in your own directory.
2. **Only three data sources exist:** OpenStreetMap via OSMnx, Open-Meteo Historical Weather API, Google Maps JavaScript API (Places, Map, Street View). GTFS is a stretch goal and is not in the core path.
3. **Verify library APIs against the installed version before writing code.** Run `pip show h3 osmnx scikit-learn` or `npm ls deck.gl @vis.gl/react-google-maps` and read the installed docstrings. h3 v4 uses `latlng_to_cell`, not `geo_to_h3`. OSMnx 2.x uses `ox.features_from_point`, not `geometries_from_point`.
4. **No LLM calls anywhere in the core path.** Scenario text is templated.
5. **Never edit a file outside your ownership**, including the contract, `schemas.py`, and another person's fixtures.
6. **Never change a constant in section 3 locally.** If the radius must shrink, it is a team decision that triggers a Phoenix refit.
7. **Report what you actually ran.** If a city failed or a step was skipped, say so in the commit message or in `CHANGE_REQUESTS.md`.

---

## 6. Change requests

Append to `contracts/CHANGE_REQUESTS.md` in this format. The next time all three sync (checkpoints at hours 0.5, 4, 6, 8, 12, 14), the list is resolved and the contract updated together.

```
## CR-003  (P3, 06:40)  Need hex center lat/lng in hexes[]
Why: Street View needs a position. Workaround: computing it client-side with h3-js cellToLatLng. Status: open
```

---

## 7. Checkpoints, cuts and stretch (from SOURCE-PLAN.md sections 9 to 12)

Checkpoints: 0.5h contracts agreed · 4h real features for Phoenix · 6h three cities through the data pipeline · 8h one city end-to-end from the UI · 12h full flow works · 14h validation numbers ready · last 4h submitted.

Freeze features 4 hours before the deadline. If a live run takes over about 2 minutes, shrink the radius (team decision, D8).

Protect the core flow and never cut it: search, heatmap, why panel, scenario cards.

Cut first, in this order: (1) GTFS transit frequency, (2) extra place categories, (3) Street View panel, (4) comparison-view polish.

Stretch, only if time allows: multi-city reference (Phoenix + SF + LA), GTFS transit frequency, export scenarios as JSON, LLM-polished scenario text.

Pre-cache before the demo: Phoenix, San Francisco, Los Angeles, Austin, Atlanta, Miami, New York, Chicago, Boston, London, Tokyo. Validation cities: Phoenix (≈5% red), Tucson (low), New York (high), London (high, left-hand traffic).
