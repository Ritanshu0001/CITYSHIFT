# P2 Plan: Model + Scenarios + Pitch

Read `contracts/CONTRACTS.md` first. It is the authority for every field, constant, function signature, the scoring algorithm (4.6) and the scenario rule table (4.7). This plan tells you what to build and when. It does not restate the contract; where it says "per contract" go look. `contracts/SOURCE-PLAN.md` is the original team plan, kept for background, the demo script and the Q&A answers; where it differs from the contract, the contract wins.

## Your role

You own the part that turns a feature table into shift scores, explanations, novel flags, a city summary and ranked scenario cards. You also own the pitch: slides, Q&A card, validation numbers.

**You own:** `backend/app/model/**` (including the saved reference artifact), `backend/scripts/make_fake_features.py`, `backend/scripts/fit_reference.py`, `backend/scripts/validate.py`, `backend/tests/fixtures/**`, `pitch/**`.

**You never touch:** anything else under `backend/` (P1), `frontend/**` (P3), `cache/` (written by P1's code; you read from it), `contracts/CONTRACTS.md` after hour 0.5. You may append lines to `backend/requirements.txt` if a dependency is missing, nothing else in that file.

**You produce for others:**
- For P1: three functions with the exact signatures in contract 4.4, importable from `app.model.scoring`, `app.model.summary`, `app.model.scenarios`. Stubbed versions that return contract-shaped fake output by **hour 2**; real versions by **hour 8**.
- For P1 and P3: a committed reference artifact (contract 4.5) by hour 6 so scoring works on every laptop.
- For everyone: validation numbers (Phoenix, Tucson, New York, London) by hour 14, and the slide deck.

**You consume from others:**
- From P1: `cache/{slug}/features.csv` and `city.json` (contract 4.3). Real Phoenix at hour 4. Until then you use your own fake fixtures.
- From P3: nothing.

## Guardrails specific to you

- Your functions receive a DataFrame and dicts and return plain dicts and lists that serialize to contract 4.2 with no further transformation. No Pydantic, no NumPy scalars in the output (cast to `float`, `int`, `str`).
- Read the feature list from `app.schemas.HEX_FEATURES`; never hard-code column names except for the scenario rules, where the contract names them.
- Load the reference artifact lazily on first call and cache it in a module-level variable. Never fit inside `score_city`.
- `random_state=ISOFOREST_SEED` on the IsolationForest. Every fit is reproducible.
- No LLM calls. Scenario text is a template dict keyed by scenario `id`.
- Never write into `cache/`. Your scripts read from it and write to `backend/tests/fixtures/` or `backend/app/model/reference/`.
- If the real Phoenix data makes a rule in contract 4.7 fire on Phoenix itself for most hexes, do not change the threshold silently. Record the number and raise it at the next sync.

---

## Phase 0: hours 0 to 0.5 (all three together) · checkpoint "contracts agreed"

Your specific job in the discussion: confirm the 17 `HEX_FEATURES` columns, the rare-feature rule, the band thresholds and the scenario table are exactly what the group wants, because you are the one who cannot change them later without a refit. Also agree how "much rainier" and the snow novel threshold are defined (contract 4.6 and 4.7 have proposed values).

Done when: the contract is frozen and you can `import app.schemas` from `backend/`.

---

## Phase 1: hours 0.5 to 4 · checkpoint "scoring on fake features"

Goal: the full scoring path runs on fake data and produces contract-shaped output; P1 can import your functions.

1. **`scripts/make_fake_features.py`**: writes `tests/fixtures/fake_phoenix_features.csv`, `fake_target_features.csv` and `fake_city.json` with the exact contract 4.3 columns. About 270 rows each. Draw densities from log-normal distributions with Phoenix-like centers (road density around 12, intersection density around 30, signals around 4, crosswalks around 6). Make `movable_bridge_count`, `tunnel_count` and `roundabout_count` zero in more than 99% of fake Phoenix rows so the rare path is exercised, and give the fake target a handful of non-zero ones plus clearly shifted `intersection_density` and `nightlife_density`. Fixed seed.
2. **`model/reference.py`**: `fit_reference(features: DataFrame, city: dict) -> dict` implementing contract 4.6 steps 1 to 3 on Phoenix, returning the artifact dict per contract 4.5. `save_reference(artifact, dir)` writes `phoenix_reference.joblib` and `reference_meta.json`. `load_reference(dir) -> dict`.
3. **`scripts/fit_reference.py`**: CLI with `--features`, `--city`, `--out`. Run it on the fake Phoenix. Do not commit this fake-fitted artifact.
4. **`model/scoring.py`**: `score_city` per contract 4.4 and 4.6 steps 2 to 6. Round `shift_score` to one decimal, `z` to two, `pct` to one, `value` and `ref_median` to two. Cast everything to Python scalars.
5. **Stubs for the other two** so P1 can import today: `build_summary` returns a contract-shaped dict using whatever is already available (city name, center, n_hexes, pct_red computed from `hexes`, climate copied from `city` and the artifact's `phoenix_city`, empty `feature_comparison`, `novel_city` empty). `build_scenarios` returns `[]`. Both have the final signatures now.
6. **Sanity run:** score fake Phoenix against the fake reference. `pct_red` must be about 5. Score the fake target; the shifted features should dominate `top_features` and the rare ones should appear in `novel`. Print both.

Done when: `python -c "from app.model.scoring import score_city"` works from `backend/`, the fake self-score is about 5% red, and you have told P1 the functions exist.

---

## Phase 2: hours 4 to 6 · checkpoint "fit reference, real scores"

Goal: the real Phoenix reference is fitted and committed; real Tucson scores look sane.

1. Load `cache/phoenix-az-usa/features.csv` and `city.json` from P1. Run `fit_reference.py` on them. Look at `reference_meta.json`: which features came out rare? Expected: `movable_bridge_count` almost certainly; `tunnel_count`, `roundabout_count`, `stadium_count` likely. If `bridge_count` is rare, that is fine too; the rule is the rule.
2. Commit `backend/app/model/reference/phoenix_reference.joblib` and `reference_meta.json`. This is the artifact everyone uses from now on. Note the fit timestamp; if P1 regenerates Phoenix features later (for example after a radius change), refit and recommit.
3. Score Phoenix against itself. Confirm `pct_red ≈ 5`. Record the exact number for the slides.
4. Score Tucson when P1 has it. Expect a low `pct_red` (single digits to low teens) and plausible `top_features`. Eyeball ten random hexes: does the explanation match the numbers?
5. If something looks wrong, check in this order: log1p applied before scaling; `score_samples` sign flipped; percentile computed against the saved sorted array not against the target's own scores.

Done when: the committed artifact loads on P1's machine and Phoenix self-score is about 5% red on real data.

---

## Phase 3: hours 6 to 8 · checkpoint "explanations + novel logic"

Goal: `hexes[]` and `summary` are complete and correct per contract.

1. **Explanations finished:** `top_features` with `value`, `ref_median` (median of the raw Phoenix column), `z` (on log1p), `pct` (percentile of raw value among Phoenix raw values). Exactly three unless fewer than three modeled features exist.
2. **Novel logic finished:** hex-level `novel[]` from rare features with value > 0; city-level `novel_city` per contract 4.6 step 7.
3. **`build_summary` complete:** `pct_red`, `climate.target` from `city`, `climate.reference` from the artifact's `phoenix_city`, `driving_side`, `feature_comparison` with one row per `HEX_FEATURES` entry (median target vs median Phoenix), `osm_completeness`, `novel_city`, plus `city`, `slug`, `center`, `radius_km`, `n_hexes`.
4. Run New York and London from `cache/`. New York should be high `pct_red` with intersection, signal, crosswalk and transit features on top. London should show `"left_hand_traffic"` in `novel_city` and `driving_side: "left"`. Write these numbers down; they are slide material.

Done when: P1's `pipeline.py` produces a `result.json` for one city that P3 renders without errors, and the why panel numbers match what you see in the DataFrame.

---

## Phase 4: hours 8 to 12 · checkpoint "scenario rules + city summary"

Goal: every scenario card in the UI shows exactly what triggered it.

1. **`model/scenarios.py`**: implement the ten rules in contract 4.7 as ten small functions that each return either `None` or a card dict. A driver runs all ten, drops `None`, sorts by `priority` descending. Priority formula per contract. `triggered_by` is a list of short strings with real numbers ("intersection_density z > 2 in 31 hexes", "rain_days_per_year 3.6x reference"). `description` is a template per `id` filled with the same numbers.
2. z-values needed by the rules come from `hexes[].top_features` only when the feature is in the top 3, which is not enough. Compute the full z matrix once inside `scoring.py`, expose it as a helper `z_matrix(features) -> DataFrame` (hex rows, modeled-feature columns) and call it from `scenarios.py`. This stays inside your directory.
3. Run all four validation cities. Expect: Phoenix produces few or no cards; Tucson few; New York many with `rain_dense_intersection`, `crosswalk_wide_arterial`, `bus_in_lane`, `snow_traction` near the top; London adds `left_hand_traffic` and likely `roundabout_or_tunnel`. If Phoenix produces many cards, a threshold is off; record it and raise it at the hour-12 sync rather than tuning alone.
4. **`scripts/validate.py`**: for each slug given on the command line, load `result.json` and print one row: city, n_hexes, pct_red, top 3 city-level feature shifts by median ratio, novel_city, number of scenario cards, top card title. Also print Phoenix self-score. Output as a Markdown table so it pastes straight into a slide.
5. **Slides, first pass** in `pitch/`: follow the demo script in SOURCE-PLAN.md section 10 exactly (hook, Phoenix as reference, judge names a city, heatmap and red hex, comparison, cards, tagline). One slide per beat, mostly screenshots P3 will supply later. Add the Q&A answers from SOURCE-PLAN.md section 11 as speaker notes.

Done when: P3 shows scenario cards for New York that each list their `triggered_by`, and `validate.py` prints a table for the four cities.

---

## Phase 5: hours 12 to 14 (all three) · checkpoint "validation numbers ready"

- Run `validate.py` on Phoenix, Tucson, New York, London. Paste the table into the slides. The story the numbers must tell: Phoenix ≈ 5% red; Tucson low; New York and London high; London has left-hand traffic as a city-level novel flag.
- If a number breaks the story, diagnose with P1 (data) before touching thresholds. Any threshold change is a team decision and is written into `CHANGE_REQUESTS.md`.
- Bug fixes only. No new rules.

---

## Last 4 hours (all three) · checkpoint "submitted"

- Feature freeze. Final slides with real screenshots from P3. Speaker notes for the four Q&A answers in SOURCE-PLAN.md section 11, word for word.
- Write the Devpost description: the framing sentence from the contract header, the tagline, the data sources, the "5% red by construction" line.
- Rehearse the 2.5-minute pitch three times with the team, once with the backup path (cached city).

---

## Hand-offs at a glance

| Hour | You give | To | You get | From |
|------|----------|----|---------|------|
| 2 | Importable `score_city`, stub `build_summary`, stub `build_scenarios` | P1 | | |
| 4 | | | Real Phoenix `features.csv` + `city.json` | P1 |
| 6 | Committed reference artifact | All | Tucson, New York, London caches | P1 |
| 8 | Real `build_summary`, full `hexes[]` | P1 → P3 | | |
| 12 | Real `build_scenarios`, `validate.py` | P1 → P3 | Screenshots for slides | P3 |
| 14 | Validation table | All | | |
