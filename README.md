# CityShift

Enter any city. CityShift shows where its driving environment differs from Phoenix and turns those differences into prioritized test scenarios, using only public data.

*Waymax tests the scenario. CityShift finds the scenario worth testing.*

## Start here

1. Read `contracts/CONTRACTS.md`. It is the single source of truth for every shared shape, constant and file name. Frozen at hour 0.5.
2. Read `contracts/SOURCE-PLAN.md` for background, the demo script and the judge Q&A. Where it differs from the contract, the contract wins.
3. Read your own plan in `plans/`. Only touch the files it says you own.

Give your coding agent those three files, in that order, with this instruction: "Read the contract first, then the source plan, then my plan. Follow my plan phase by phase. Only touch files my plan says I own."

| Person | Plan | Owns |
|--------|------|------|
| P1 | `plans/P1-DATA-AND-API.md` | `backend/` except `backend/app/model/`, plus `cache/`, this README |
| P2 | `plans/P2-MODEL-SCENARIOS-PITCH.md` | `backend/app/model/`, `backend/tests/fixtures/`, model scripts, `pitch/` |
| P3 | `plans/P3-FRONTEND.md` | `frontend/`, `demo/` |

## Backend (P1, P2)

Python 3.11.

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -c "import h3, osmnx; print(h3.__version__, osmnx.__version__)"   # expect 4.x and 2.x
```

Run the API (once `app/main.py` exists):

```bash
uvicorn app.main:app --reload --port 8000
```

Run one city from the CLI (once `scripts/run_city.py` exists):

```bash
python scripts/run_city.py "Phoenix, AZ, USA" 33.4484 -112.0740 --country US
```

## Frontend (P3)

Node 20. `frontend/` does not exist yet on purpose; the generator creates it:

```bash
npx create-next-app@latest frontend --ts --app --src-dir --eslint --tailwind
```

Then copy `frontend/.env.local.example` to `frontend/.env.local` and set `NEXT_PUBLIC_GOOGLE_MAPS_KEY`. Run with `npm run dev` from `frontend/`.

## Layout

See `contracts/CONTRACTS.md` section 2 for the full tree and ownership. `cache/` holds per-city results and is committed for demo cities. `osmnx_cache/` is OSMnx's raw HTTP cache and is git-ignored.
