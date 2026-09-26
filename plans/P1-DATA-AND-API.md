# P1 Plan: Data + API

Read `contracts/CONTRACTS.md` first. It is the authority for every field, file name, constant and function signature. This plan tells you what to build and when. It does not restate the contract; where it says "per contract" go look. `contracts/SOURCE-PLAN.md` is the original team plan, kept for background, the demo script and the Q&A answers; where it differs from the contract, the contract wins.

## Your role

You own everything that turns a city name and coordinates into a feature table on disk, and everything that serves results over HTTP. You also own the orchestrator that calls P2's three functions.

**You own:** `backend/` except `backend/app/model/` and `backend/scripts/{make_fake_features,fit_reference,validate}.py` and `backend/tests/fixtures/`. Also `cache/`, `README.md`, `.gitignore`, `backend/requirements.txt`, `backend/app/schemas.py`.

**You never touch:** `backend/app/model/**`, `frontend/**`, `pitch/**`, `demo/**`, P2's scripts and fixtures, `contracts/CONTRACTS.md` after hour 0.5.

**You produce for others:**
- For P2: `cache/{slug}/features.csv` and `cache/{slug}/city.json` (contract 4.3). Real Phoenix by hour 4. Tucson, New York, London by hour 6.
- For P3: the four endpoints (contract 4.1), CORS enabled, running on port 8000 by hour 8.

**You consume from others:**
- From P2: `score_city`, `build_summary`, `build_scenarios` (contract 4.4). Until they exist, your pipeline runs the data half and writes `features.csv` + `city.json` only.
- From P3: nothing.

## Guardrails specific to you

- h3 is **v4**: `latlng_to_cell`, `cell_to_latlng`, `grid_disk`, `cell_area(cell, unit="km^2")`, `great_circle_distance`. Check `h3.__version__` at hour 0 and fail loudly if it starts with 3.
- OSMnx is **2.x**: `ox.graph_from_point((lat, lng), dist=8000, network_type="drive")`, `ox.features_from_point((lat, lng), tags, dist=8000)`, `ox.graph_to_gdfs(G)`. Settings live on `ox.settings` (`use_cache`, `cache_folder`, `requests_timeout`, `overpass_url`). Read the installed docstrings before using anything else.
- Open-Meteo archive endpoint: `https://archive-api.open-meteo.com/v1/archive` with `latitude`, `longitude`, `start_date`, `end_date`, `daily=precipitation_sum,snowfall_sum`, `timezone=auto`. No key. Snowfall is in cm.
- Do not add a database, a task queue, or Docker. One thread, one dict, files on disk.
- Do not compute scores, bands, z-values or scenarios anywhere in your code. That is P2's job and living in P2's directory.
- If a `features.csv` column is hard to compute for a city, write `0` for that column and note it in `CHANGE_REQUESTS.md`. Never drop or rename a column.

---

## Phase 0: hours 0 to 0.5 (all three together) · checkpoint "contracts agreed"

Deliverables (you do these while the group talks; they are mechanical):

1. The skeleton repo already has the layout from contract section 2, the `__init__.py` files, `.gitignore`, and placeholder `.gitkeep` files. Verify nothing is missing. `cache/` is deliberately not ignored. `frontend/` is deliberately absent (P3 generates it).
2. `backend/requirements.txt` already lists the full team set. Create the venv, `pip install -r requirements.txt`, then replace the list with the `pip freeze` output so versions are pinned. Check `h3.__version__` is 4.x and `osmnx.__version__` is 2.x; if not, fix the pins now.
3. `backend/app/schemas.py` already contains every constant from contract section 3, `HEX_FEATURES`, `FEATURE_CSV_COLUMNS`, and Pydantic models for contract 4.1 and 4.2. Verify it against the contract line by line and fix any mismatch before the freeze. Frozen after 0.5h.
4. `README.md` exists with the bootstrap steps. Keep its run commands current as you add `run_city.py` and `precache.py`. Keep it under 60 lines.
5. `contracts/` already holds `CONTRACTS.md`, `SOURCE-PLAN.md` and `CHANGE_REQUESTS.md`. Push the repo to the team remote so P2 and P3 can clone.

Done when: everyone has cloned, `pip install -r requirements.txt` succeeds, `python -c "import app.schemas"` runs.

---

## Phase 1: hours 0.5 to 4 · checkpoint "real features for Phoenix"

Goal: `python scripts/run_city.py "Phoenix, AZ, USA" 33.4484 -112.0740 --country US` writes `cache/phoenix-az-usa/features.csv`, `city.json` and `meta.json` that match contract 4.3 exactly.

Build in this order; each piece is testable alone.

1. **`cache.py`**: `slugify(name)` per contract rule, `city_dir(slug)`, `write_json`, `read_json`, `write_features(slug, df)`, `read_features(slug)`, `has_result(slug)`, `list_cities()` (reads every `result.json` summary for `GET /cities`). Small and boring.
2. **`data/grid.py`**: `hexes_for(lat, lng) -> list[str]`. Center cell at `H3_RES`, `grid_disk(center, 10)`, keep cells whose center is within `RADIUS_KM` (use `great_circle_distance`). Expect about 270 cells.
3. **`data/weather.py`**: `climate_for(lat, lng) -> dict` with the three `*_days_per_year` keys per contract D16. One HTTP GET, count days, divide by 5. Return zeros and log a warning on failure; never raise.
4. **`data/driving_side.py`**: `driving_side(country_code) -> "left" | "right"` from a static set of left-hand-traffic ISO codes. Start with: `GB IE MT CY AU NZ PG FJ SB TO WS KI NR TV CK NU JP TH MY SG ID BN TL HK MO IN PK BD LK NP BT MV ZA NA BW ZW ZM MW MZ LS SZ KE UG TZ MU SC JM TT BB BS GY SR AG DM GD KN LC VC BM KY VG AI MS TC FK SH`. Also `country_for(lat, lng) -> str | None` using `reverse_geocoder` as the fallback when the API request has no `country_code`. If `reverse_geocoder` fails to import or run, return `None` and the pipeline uses `"right"`.
5. **`data/osm.py`**: two functions. `drive_graph(lat, lng)` returns the graph. `osm_features(lat, lng)` runs the single combined `TAGS` query from SOURCE-PLAN.md section 3 and returns the GeoDataFrame. Set `ox.settings.use_cache = True`, `ox.settings.cache_folder = "osmnx_cache"`, `ox.settings.requests_timeout = 180`, `ox.settings.log_console = True`. Nothing else yet.
6. **`data/features.py`**: `build_features(hex_ids, G, feats) -> (DataFrame, osm_completeness)`. Convert the graph to node and edge GeoDataFrames. Assign nodes by point, edges by midpoint, feature points by location, feature polygons by centroid, all via `latlng_to_cell`. Then compute each column per the contract table. Drop hexes with `road_km < MIN_ROAD_KM`. Reindex to `FEATURE_CSV_COLUMNS`. Tags that are lists take the first value. `osm_completeness` = share of edges with a `maxspeed` or `lanes` tag.
7. **`scripts/run_city.py`**: CLI wrapper that runs steps 2 to 6, writes `features.csv`, `city.json`, `meta.json`, and prints `n_hexes_kept`, the column means, and elapsed seconds per step. This is your main debugging tool all day.

Then run Phoenix. Sanity checks before you hand off: about 240 to 270 rows; `road_density` mostly between 5 and 25 km/km²; `signal_density` non-zero in most hexes; `bridge_count` non-zero in a handful; `movable_bridge_count` all zero; `snow_days_per_year` ≈ 0; `driving_side` right. Commit `cache/phoenix-az-usa/`. Tell P2 the slug.

Then run one more city (Tucson, 32.2226, -110.9747) to confirm nothing was Phoenix-specific.

Done when: both cities' `features.csv` open in pandas with exactly the contract columns, and P2 has confirmed the Phoenix file loads in their fit script.

---

## Phase 2: hours 4 to 6 · checkpoint "3 cities through the data pipeline"

Goal: a dense city finishes in under 2 minutes, and three more cities are cached.

1. **Measure first.** Run New York (40.7128, -74.0060) with the per-step timings from `run_city.py`. The graph pull and the features pull are the usual bottlenecks.
2. **Parallelize the three network calls.** Graph, features and weather are independent. Run them in a `ThreadPoolExecutor` with three workers and join. This is usually the single biggest win.
3. **Trim the graph work.** You only need node `street_count`, edge `length`, `highway`, `oneway`, `bridge`, `tunnel`, `junction`, `lanes`, `maxspeed`. Skip anything that simplifies, projects or adds speeds.
4. **If New York is still over 2 minutes after 2 and 3**, raise it at the hour-6 sync as a possible radius change (contract D8). Do not change the radius alone.
5. Run Tucson, New York, London (51.5074, -0.1278, country GB). Commit the three `cache/` directories. Confirm London's `city.json` says `"driving_side": "left"` and New York's `snow_days_per_year` is well above zero.

Done when: three cities beyond Phoenix are in `cache/` and the slowest took under about 2 minutes wall clock.

---

## Phase 3: hours 6 to 8 · checkpoint "1 city end-to-end from the UI"

Goal: P3 hits `POST /analyze` for a new city, polls `GET /jobs/{id}`, then loads `GET /cities/{slug}`.

1. **`pipeline.py`**: `analyze_city(name, lat, lng, country_code, progress) -> None`. `progress(step)` is a callback you call at the start of each `JOB_STEPS` entry, in contract order: `roads` (graph), `infrastructure` (features query), `weather`, `scoring` (P2's `score_city` + `build_summary`), `scenarios` (P2's `build_scenarios`). Write `features.csv` and `city.json` as soon as the data half is done, then `result.json` at the end. Read `features.csv` back from disk before passing it to P2 so what P2 gets is exactly what is on disk. Wrap P2's calls: on any exception, re-raise with the step name prefixed so the UI can show "scoring failed: ...".
2. **`jobs.py`**: a module-level dict `{job_id: JobState}` and a single worker thread with a `queue.Queue`. `submit(name, lat, lng, country_code) -> JobState` returns immediately. If `cache.has_result(slug)`, create a job already in `done` state and return it (contract 4.1). Status transitions: `queued → running → done | error`. Store `step`, `steps_done`, `message`, `error`.
3. **`main.py`**: the four routes per contract 4.1 with the Pydantic models from `schemas.py`. `CORSMiddleware` with `allow_origins=["http://localhost:3000"]`. Return 404 with `{"detail": "not cached"}` for an unknown slug and 404 for an unknown job id. Nothing else.
4. Smoke test with `curl` in this order: `POST /analyze` for Phoenix (should come back `cached: true`), `GET /cities/phoenix-az-usa`, `POST /analyze` for a city not yet cached, poll the job, fetch the result. Paste the exact `curl` lines into `README.md`.

Done when: P3 confirms one uncached city runs from their search box to their map with no manual steps.

---

## Phase 4: hours 8 to 12 · checkpoint "full flow works"

1. **Overpass fallback in `osm.py`.** Wrap both OSM calls: try with the default `ox.settings.overpass_url`; on any exception, set it to a second public instance (verify one is up at this hour; `https://overpass.kumi.systems/api/interpreter` has historically been one), retry once, then restore the default. Log which server answered. Surface a failure as a job `error` with a readable message, not a stack trace.
2. **`scripts/precache.py`**: the pre-cache list from contract section 7 with hard-coded lat/lng and country codes. Runs cities sequentially through `analyze_city`, skips ones that already have `result.json`, prints a one-line summary per city. Start it in a second terminal and let it run while you do item 3. Commit `cache/` as cities finish.
3. **`GET /cities`** returns every cached city with the summary fields from contract 4.1, sorted by name. P3 uses it for the backup-demo list.
4. **Robustness passes:** a hex with `road_km = 0` must not divide by zero; `avg_lanes` may be all-empty; OSM `oneway` can be a string; a city with zero features of some tag must still produce the column. Re-run Phoenix and diff the new `features.csv` against the committed one; they must be identical (deterministic pipeline).

Done when: all pre-cache cities have `result.json`, and a deliberately broken Overpass URL still produces a clean job error in the UI.

---

## Phase 5: hours 12 to 14 (all three) · checkpoint "validation numbers ready"

- Run P2's `scripts/validate.py` with them and fix any data-side issue it surfaces (a column that is all zeros for a city where it should not be, for example).
- Restart the API from a clean clone on a second machine if one is available. If it does not run from `README.md` alone, fix the README.
- Bug fixes only. No new features.

---

## Last 4 hours (all three) · checkpoint "submitted"

- Feature freeze. Your job is the demo laptop: venv ready, API running, `cache/` complete, `osmnx_cache/` warm for the pre-cache cities so even a "live" repeat is instant.
- Rehearse the backup path with P3: kill the network, open a cached city from `/`, confirm everything renders.
- Help write the Devpost technical section (architecture and data sources). Rehearse three times.

---

## Hand-offs at a glance

| Hour | You give | To | You get | From |
|------|----------|----|---------|------|
| 0.5 | `schemas.py`, `requirements.txt`, repo | All | Frozen contract | All |
| 4 | `cache/phoenix-az-usa/{features.csv,city.json}` | P2 | | |
| 6 | Tucson, New York, London caches | P2 | | |
| 8 | API on :8000 with CORS | P3 | Working `score_city`, `build_summary`, `build_scenarios` | P2 |
| 12 | All pre-cache cities in `cache/` | P2, P3 | | |
