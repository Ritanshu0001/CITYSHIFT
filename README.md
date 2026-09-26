# CityShift

Enter any city. CityShift shows where its driving environment differs from Phoenix and turns those differences into prioritized test scenarios, using only public data.

*Waymax tests the scenario. CityShift finds the scenario worth testing.*

## Start here

Give your coding agent, in order: `contracts/CONTRACTS.md` (single source of truth, frozen at hour 0.5), `contracts/SOURCE-PLAN.md` (background, demo, Q&A; the contract wins on conflicts), then your plan in `plans/`. Instruction: "Read the contract first, then the source plan, then my plan. Follow my plan phase by phase. Only touch files my plan says I own."

| Person | Plan | Owns |
|--------|------|------|
| P1 | `plans/P1-DATA-AND-API.md` | `backend/` except `backend/app/model/`, plus `cache/`, this README |
| P2 | `plans/P2-MODEL-SCENARIOS-PITCH.md` | `backend/app/model/`, `backend/tests/fixtures/`, model scripts, `pitch/` |
| P3 | `plans/P3-FRONTEND.md` | `frontend/`, `demo/` |

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

## Frontend (P3)

Node 20. `frontend/` does not exist yet on purpose; generate it with `npx create-next-app@latest frontend --ts --app --src-dir --eslint --tailwind`, copy `frontend/.env.local.example` to `frontend/.env.local`, set `NEXT_PUBLIC_GOOGLE_MAPS_KEY`, then `npm run dev` from `frontend/`.

## Layout

See `contracts/CONTRACTS.md` section 2. `cache/{slug}/` holds `features.csv`, `city.json`, `meta.json`, `result.json` and is committed for demo cities. `backend/osmnx_cache/` is OSMnx's raw HTTP cache and is git-ignored.
