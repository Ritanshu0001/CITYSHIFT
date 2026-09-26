# CityShift — Devpost submission

Owner: P2. Paste into the Devpost fields; headings match their form.

**Tagline:** Waymax tests the scenario. CityShift finds the scenario worth testing.

> Numbers are the committed results at `519fd30`. Refresh after the CR-011 terrain refit.

---

## What it does

Enter any city. CityShift measures how that city's driving environment differs from the
cities with **established autonomous operations** — Phoenix, San Francisco, Los Angeles,
Austin and Atlanta — and turns the differences into prioritized candidate test
scenarios. It uses only public data, so it works for cities nobody has driven yet.

You get four things:

1. **A hexagon heatmap**, each hex colored by how unlike the reference cities it is.
2. **A "why" panel** for any hex: the top three features driving its score, each with
   the reference median and percentile, plus Street View.
3. **A city-vs-reference comparison**: climate, driving side, OSM completeness and the
   largest median feature shifts.
4. **Ranked scenario cards**, each showing exactly what triggered it.

The reference pool scored against itself comes out at **5.0% red across 1,153 hexes**,
which is the honest-scale check: red is *defined* as the top 5% of the reference's own
distribution. Tucson lands at **3.2%**, in among the reference cities. London lands at
**46.3%**.

## How we built it

**Geometry is held constant so the comparison is fair.** Every city is an 8 km circle,
gridded into H3 resolution-8 hexagons, with hexes under 0.5 km of road dropped. The
reference cities go through the identical pipeline.

**Data**, all public and worldwide:
- OpenStreetMap via OSMnx — drive network plus one combined features query
- Open-Meteo Historical Weather API — five years of daily precipitation and snowfall
  (2020-01-01 to 2024-12-31)
- **Elevation: Copernicus DEM GLO-90 via Open-Meteo** — per-hex percent grade
- Google Maps JavaScript API — Places search, map and Street View

**Features:** 18 per-hex signals across seven groups — network, road mix, control,
vulnerable road users, activity, infrastructure and terrain — plus city-level climate
and driving side.

**Model:** `log1p` → `StandardScaler` → `IsolationForest(random_state=42)`, fitted over
all five reference cities pooled with equal weight per hex. A hex's `shift_score` is the
percentile of its anomaly score against that pooled distribution. Features too rare in
the reference to model become **novel** flags instead. The climate reference is the
per-metric max across the five cities — the car already drives in the wettest of them.

**Scenarios:** eleven deterministic rules, ranked by `mean |z| × hexes affected`. There
is **no LLM in the core path** — every card carries its own trigger evidence.

**Architecture:** a Python 3.11 FastAPI backend and a Next.js App Router frontend. Files
on disk are the integration seam, which let three people build in parallel from hour
zero. The cache directory is the source of truth, so the backup demo runs offline.

## Challenges we ran into

**A green test suite hid a completely broken runtime.** We added a terrain feature to the
schema, and every model test passed — because the tests always fit a fresh reference from
fixtures. The *committed* artifact still predated the feature, so every real city died on
a bare `KeyError` five frames deep inside the summary builder. The API, the validator and
the rescore tool were all down while CI was green. The fix was a guard that checks the
saved artifact still covers the feature list and says which feature is missing and which
command refits it. The lesson stuck: tests assert what you thought to check, and the
thing they set up for you is the thing they can never catch.

**The reference model is a pickle, and pickles are version-sensitive.** Our first fit was
built on a machine whose libraries were older than the project's pins. Because we fitted
and loaded in the same environment, every test passed and all cities scored correctly —
the problem was invisible locally and would only have surfaced for a teammate on the
pinned requirements, where a DataFrame pickled across a pandas major version might not
load at all. The artifact now records the libraries it was pickled with, so any mismatch
warns loudly instead of silently rescaling scores.

**Elevation data includes buildings.** The DEM is a *surface* model, so downtown towers
read as terrain. Chicago's five steepest hexes are all in the Loop, on ground that is
famously flat. We measured the gate before trusting the card: it lands at 6.54% against
Chicago's steepest 4.40%, so the Loop stays quiet, while San Francisco's 40 hexes and
San Diego's canyon hexes fire correctly.

**One reference city was the wrong baseline.** Scoring against Phoenix alone made every
dense city look extreme — London came out at 73% red, which flatters the tool more than
it informs anyone. Pooling five real operating environments roughly halved every score
and asks a sharper question: is this unlike *anywhere* the cars already run?

**Rare-feature logic cuts both ways.** Features present in under 1% of reference hexes
become "novel" flags. That works for movable bridges. It failed for roundabouts and
tunnels, which are common enough to model and so never qualified as novel — meaning a
rule keyed to their novelty could never fire at all. A rule can be perfectly implemented
against its spec and still be unreachable.

## What we learned

Anchoring a score to real reference cities makes it auditable. 5.0% against itself is not
a lucky result, it is the definition working, and a judge can check us in one sentence.

Verifying in the same environment that produced an artifact proves almost nothing. Every
real defect we found — the version drift, the unreachable thresholds, the stale artifact —
passed the tests and produced plausible numbers.

Determinism is worth more than sophistication in a live demo. No LLM in the core path
means every card is explainable, reproducible and impossible to embarrass us on stage.

## What's next

- Land the crosswalk trigger fix, so every scenario rule can fire.
- Ship the card-ranking change that subtracts the rate the reference itself fires at, so
  a card that is merely common stops outranking one that is genuinely concentrated.
- Re-specify the roundabout/tunnel trigger as `count > 0`, which is what its z > 2 bar
  already amounts to on such sparse counts.
- Separate terrain from buildings with a bare-earth DEM.
- GTFS transit frequency; scenario export as JSON for a simulator to consume.

## Honest limitations

The shift score measures how *unlike the reference cities* an area is. Unusual is not the
same as dangerous, and we do not claim otherwise. OSM completeness and counting
conventions vary, so we surface completeness as a number rather than hiding it. Elevation
includes buildings. One card currently behaves as a presence signal rather than an
unusualness signal, and one cannot fire yet — both are measured, filed and visible in our
change log rather than papered over.

## Try it

Thirteen cities are pre-cached — Phoenix, Tucson, Austin, Atlanta, Miami, Boston,
Chicago, New York, Los Angeles, San Francisco, San Diego, London and Tokyo — so the
project runs from a fresh clone with no network access and no model refit.
