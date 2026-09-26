# CityShift — model and scenarios (P2 slides)

Owner: P2. Covers the model, novel logic and scenario rules. P3 owns the demo video;
`demo/DEMO-SCRIPT.md` owns the live walkthrough timing.

> **Numbers status.** The reference artifact is refit with terrain at `d2e5b3c`
> (five cities, 1,153 hexes, pooled self-score **5.0%**). The red percentages in the
> table below are still the pre-terrain cached results from `519fd30` and will move
> once P1 rescores; six cities are mid-refresh. Terrain figures are from the real fit.
> **Re-run `scripts/validate.py` before the rehearsal.**

Speaker notes are the indented lines.

---

## Slide 1 — The question

> **"An autonomous car may know a city's laws. Does it know the city?"**

A car can pass every rule in a new city and still meet an environment nobody tested it
in: a multi-lane roundabout, a bridge that opens, snow on unmarked lanes, a blind crest.

> Do not claim Waymo lacks this. The question is which environments are worth testing
> first, and that is a ranking problem on public data.

---

## Slide 2 — What CityShift does

Enter any city. CityShift shows where its driving environment differs from **the cities
with established autonomous operations** — Phoenix, San Francisco, Los Angeles, Austin
and Atlanta — and turns those differences into prioritized candidate test scenarios.
Public data only.

**Tagline:** *Waymax tests the scenario. CityShift finds the scenario worth testing.*

---

## Slide 3 — One reference, one geometry, one model

Fairness comes from holding everything constant except the city:

- **8 km radius** around the city center, for every city including the reference ones.
- **H3 resolution 8** hexagons; hexes with under 0.5 km of road are dropped.
- **18 per-hex features** — network, road mix, control, vulnerable road users, activity,
  infrastructure and terrain — plus city-level climate and driving side.
- **One committed model**, fitted once over a **pooled reference of 1,153 hexes** across
  the five cities, each hex weighted equally.

> Pooling matters: a single-city reference made every dense city look extreme. Against
> five real operating environments, the score answers a sharper question — is this
> unlike *anywhere* the cars already run?

---

## Slide 4 — How a hex gets scored

1. `log1p` every modeled feature, then a fitted `StandardScaler`.
2. `IsolationForest(random_state=42)` → anomaly score.
3. **shift_score** = the percentile of that score against the pooled reference scores.
4. Bands: green under 80, yellow 80–95, **red 95+**.
5. Explanation = the top 3 features by |z|, each with its reference median and percentile.
6. Features too rare in the reference to model become **novel** flags instead.
7. Climate reference is the **per-metric max** across the five cities — the car already
   drives in the wettest of them.

---

## Slide 5 — Does the score mean anything?

The reference pool scored against itself: **5.0% red across 1,153 hexes.** The contract
predicts about 5%.

| City | Red | | City | Red |
|---|---:|---|---|---:|
| **Phoenix** (ref) | **2.2%** | | Boston | 13.2% |
| **Atlanta** (ref) | **2.8%** | | San Francisco (ref) | 13.7% |
| Tucson | 3.2% | | Miami | 18.0% |
| **Los Angeles** (ref) | **4.1%** | | Chicago | 18.2% |
| **Austin** (ref) | **5.6%** | | Tokyo | 21.9% |
| | | | New York | 30.4% |
| | | | London | 46.3% |

Tucson — a neighbouring desert grid city — lands at 3.2%, in among the reference cities.
London lands at 46.3%.

> Lead with the 5.0% pooled self-score; it is the cleanest honest-scale proof we have.
> Then Tucson, then London.

---

## Slide 6 — Differences become scenarios

Eleven deterministic rules turn per-hex and city-level differences into ranked cards.
`priority = mean |z| × hexes affected`. Every card shows its evidence in `triggered_by`.

| Card | Cities (of 12) |
|---|---:|
| Multi-lane roundabout entry; tunnel lighting change | 12 |
| Late-night pedestrian activity | 12 |
| Event crowd leaving + rideshare pickup | 12 |
| Queue at an opening bridge | 6 |
| Bus stopping in lane and pulling out | 6 |
| Reduced traction + hidden lane markings (snow) | 4 |
| Cyclist at a complex intersection | 3 |
| Mirrored turn logic (left-hand traffic) | 2 |
| Heavy rain at a dense signalized intersection | 1 |
| Steep grade with a limited sight line over the crest | 4 of 7 measured |
| Pedestrian crossing a wide arterial | 0 — open fix |

**No LLM in the core path.** Every card is a rule with a visible trigger, so output is
identical on every machine and there are no demo surprises.

---

## Slide 7 — Honest limitations

- **Elevation is a surface model, so it includes buildings.** Chicago's five steepest
  hexes are all downtown on flat ground — the Loop's towers, not a hill. We checked that
  `steep_grade` does not fire there: on the real fit the z > 2 gate is **6.54%** against
  Chicago's steepest **4.40%**. San Francisco fires 40 hexes (median grade 3.85%), San
  Diego 16 and Los Angeles 15; Phoenix, Atlanta and Chicago fire none.
- **OSM counting conventions differ.** Phoenix has a bulk sidewalk import, so it counts
  ~25,000 `highway=crossing` points including unmarked ones. That inflates one reference
  baseline and is why `crosswalk_wide_arterial` cannot fire yet; the fix is agreed and
  pending a last sign-off.
- **One card is a presence signal, not an unusualness one.** On counts as sparse as
  roundabouts and tunnels, a z > 2 bar is close to "present at all", so that card fires
  in all 12 cities and currently tops 7 of them. A ranking fix is prototyped.
- **Unusual is not dangerous.** The score measures difference from the reference cities.

> Volunteering these is the strongest move available. It shows the numbers are measured
> rather than asserted.

---

## Close

> **"Waymax tests the scenario. CityShift finds the scenario worth testing."**

---

## Appendix — data sources and reproducibility

- Roads, infrastructure and places: **OpenStreetMap** via OSMnx
- Weather, 2020-01-01 to 2024-12-31: **Open-Meteo Historical Weather API**
- **Elevation: Copernicus DEM GLO-90 via Open-Meteo**
- Map, Places and Street View: **Google Maps JavaScript API**

Terrain gate numbers (median / p95 percent grade): Phoenix 0.44 / 1.15, Chicago
0.17 / 1.18, San Diego 1.04 / 7.33, San Francisco 1.42 / 9.02.

The model is one artifact committed to the repo (D4), fitted once, loaded by everyone.
`reference_meta.json` records the four libraries it was pickled with and the five source
cities, so a version or data mismatch warns rather than silently rescaling scores.
