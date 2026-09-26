> Original team plan, saved verbatim on 2026-09-26 as `contracts/SOURCE-PLAN.md`. Background only: where this differs from `CONTRACTS.md`, `CONTRACTS.md` wins. The three deliberate differences (single response shape for `POST /analyze`, `slug` and `novel_city` in the summary, optional `country_code`) are listed in `CONTRACTS.md` section 1.

# CityShift: full plan

## 1. What it is
**One-liner:** Enter any city. CityShift shows where its driving environment differs from Phoenix, a city Waymo already knows well, and turns those differences into prioritized test scenarios. It uses only public data.

**How to frame it:** "CityShift uses public data to find driving environments that differ from a reference city, and turns those differences into candidate test scenarios." Don't claim Waymo lacks this or that you teach Waymo to drive.

**Tagline:** *Waymax tests the scenario. CityShift finds the scenario worth testing.*

**What the user sees:**
1. A search box to pick any city.
2. A progress screen while it analyzes.
3. A heatmap of hexagons colored by how different each area is from Phoenix.
4. Clicking a hex shows why it's different, plus Street View.
5. A city-vs-Phoenix comparison.
6. Scenario cards.

## 2. How it works: `analyze_city(name, lat, lng)`
1. **Area:** an 8 km circle around the city center. It's the same size for every city, including Phoenix.
2. **Grid:** H3 hexagons at resolution 8, about 0.74 km² each, so roughly 270 per city. Drop hexes with almost no road (water, parks).
3. **Pull data:** the OSM road network, one combined OSM features query, and 5 years of daily weather from Open-Meteo.
4. **Features:** compute per-hex features plus city-level climate and driving side.
5. **Score:** load the saved Phoenix model and compute shift scores, explanations and novel features.
6. **Scenarios:** apply the rules to produce ranked scenario cards.
7. **Cache:** save everything to `cache/{city_slug}/`. A repeat request is instant.

## 3. Data sources (all work worldwide)

| Data | Source | How |
|---|---|---|
| Road network, intersections, lanes, one-ways, bridges, tunnels, roundabouts | OpenStreetMap | `ox.graph_from_point(center, dist=8000, network_type="drive")`: bridge, tunnel and junction info come on the road segments for free |
| Signals, crossings, bike lanes, transit stops, places | OpenStreetMap | One `ox.features_from_point` call with combined tags (below) |
| Rain days, heavy-rain days, snow days | Open-Meteo Historical API | Daily `precipitation_sum`, `snowfall_sum` for 2020–2024; free, no key |
| City search → coordinates | Google Places Autocomplete | Frontend |
| Map + Street View | Google Maps JS API + deck.gl `H3HexagonLayer` | Frontend |
| Driving side | Small country lookup table | Backend |
| *Bonus:* transit frequency | GTFS via Mobility Database | Only where a feed exists |

```python
TAGS = {
  "highway": ["traffic_signals", "crossing", "bus_stop", "cycleway"],
  "public_transport": ["platform", "station"],
  "railway": ["station", "tram_stop"],
  "amenity": ["school", "bar", "pub", "nightclub"],
  "leisure": ["stadium"],
  "tourism": ["hotel", "attraction"],
}
```

## 4. Features

**Per hex (normalized per km²):**

| Group | Features |
|---|---|
| Network | intersection density (nodes with 3+ streets), road density |
| Road mix | arterial share, motorway share, one-way share |
| Control | traffic signal density, crosswalk density |
| Vulnerable road users | bike lane density, transit stop density |
| Activity | schools, nightlife, tourism places (hotels + attractions) |
| Infrastructure (usually rare) | bridges, **movable bridges**, tunnels, roundabouts |
| Optional | average lanes, only where tagged |

**Per city:** rain days per year (≥1 mm), heavy-rain days (≥20 mm), snow days, driving side, and OSM completeness (% of roads with speed limit or lane tags).

## 5. Scoring
- **Reference (fit once, saved):** Phoenix feature distributions after `log1p`, a StandardScaler, an Isolation Forest (fixed seed), and Phoenix's own Isolation Forest scores for calibration.
- **Rare features, detected automatically:** any feature present in under 1% of Phoenix hexes skips the z-score and model. When a target hex has one, it's flagged **novel** and gets a ⚠ marker on the map.
- **Shift score (0–100):** the hex's Isolation Forest anomaly score as a percentile of Phoenix's own scores, i.e. "more unusual than X% of Phoenix areas."
- **Map colors:** green below 80, yellow 80–95, red 95 and up.
- **"Why" panel:** the top 3 features by |z| (computed on log values), showing the raw value, the Phoenix median and the percentile.
- **City level:** % of hexes that are red, a per-feature median comparison, climate ratios vs. Phoenix, and city-level novel flags (snow, left-hand traffic).
- **Built-in sanity check:** Phoenix scored against itself comes out about 5% red by construction.

## 6. Scenario rules (deterministic; an LLM only polishes the wording)

| Trigger | Scenario |
|---|---|
| Movable bridge (novel) | Queue at an opening bridge + adjacent lane change |
| Much rainier city + intersection z > 2 | Heavy rain at a dense signalized intersection with a pedestrian crossing |
| Crosswalk z > 2 + arterial share z > 1 | Pedestrian crossing a wide arterial |
| Bike lane z > 2 + intersection z > 2 | Cyclist at a complex intersection (right-hook risk: car turning across a cyclist) |
| Nightlife z > 2 | Late-night pedestrian activity |
| Stadium present | Event crowd leaving + rideshare pickup congestion |
| Transit stop z > 2 | Bus stopping in lane and pulling out |
| Snow days (novel) | Reduced traction + hidden lane markings |
| Left-hand traffic | Mirrored turn logic; turns across oncoming traffic |
| Roundabout / tunnel (novel) | Multi-lane roundabout entry / GPS loss and lighting change in a tunnel |

**Priority** = size of the z-score (or novel) × number of hexes affected.

## 7. Stack and API
- **Backend:** Python, FastAPI, osmnx, geopandas, h3, scikit-learn. A background thread runs each job; results are cached to disk.
- **Frontend:** Next.js, Google Maps JS API, deck.gl `GoogleMapsOverlay` + `H3HexagonLayer`, Places Autocomplete, Street View panel.
- **Endpoints:**
  - `POST /analyze {name, lat, lng}` → returns a job ID, or the cached result immediately
  - `GET /jobs/{id}` → status + progress steps (roads, infrastructure, weather, scoring, scenarios)
  - `GET /cities` → list of cached cities
  - `GET /cities/{slug}` → `{hexes, summary, scenarios}`
- **Hosting:** run on a laptop for the demo. Deploying is optional.

**Data contracts:**
```
hexes[]:   h3, shift_score, band, top_features[{name, value, ref_median, z, pct}], novel[]
summary:   city, center, radius_km, n_hexes, pct_red, climate{target, reference},
           driving_side, feature_comparison[{name, target, reference}], osm_completeness
scenarios: id, priority, title, description, triggered_by[], hex_ids[], scope (hex|city)
```

## 8. Team

| Person | Owns |
|---|---|
| **P1: Data + API** | Hex grid, OSM + Open-Meteo pulls, feature table, FastAPI + job progress, cache, backup Overpass server (the service OSMnx downloads from) |
| **P2: Model + scenarios + pitch** | Reference model, scoring, novel logic, explanations, scenario rules, validation runs, slides |
| **P3: Frontend** | Search, progress screen, hex map, "why" panel + Street View, comparison view, scenario cards, demo video |

## 9. Timeline (work backward from your submission deadline)

| Hours | P1 | P2 | P3 | Checkpoint |
|---|---|---|---|---|
| 0–0.5 | All: lock contracts, features, radius, repo setup | | | |
| 0.5–4 | Pipeline on Phoenix + 1 city | Scoring on fake features | Map on fake hexes | Real features for Phoenix |
| 4–6 | Speed tuning, 3 random cities | Fit reference, real scores | "Why" panel + search | **3 cities through the data pipeline** |
| 6–8 | API + job progress + cache | Explanations + novel logic | Progress screen, wired to API | **1 city end-to-end from the UI** |
| 8–12 | Overpass fallback, pre-cache 8–10 cities | Scenario rules + city summary | Comparison view + scenario cards | Full flow works |
| 12–14 | All: validation runs (Phoenix, Tucson, NYC, London), bug fixes | | | |
| Last 4 | All: feature freeze, demo video, Devpost write-up, rehearse 3× | | | |

## 10. Demo (about 2.5 min)
1. **Hook:** "An autonomous car may know a city's laws. Does it know the city?"
2. Show Phoenix as the reference city.
3. Ask a judge: "Name any city." Let the progress steps tick while you explain the pipeline.
4. The heatmap appears. Click a red hex: top 3 reasons with percentiles, Street View, any ⚠ novel feature.
5. City comparison: climate, driving side, biggest shifts.
6. Scenario cards, each showing what triggered it.
7. Close with the tagline.

**Backup:** if the live run is slow, say "here's one we ran earlier" and open a cached city.

## 11. Answers to likely judge questions
- **"Does the score mean anything?"** Phoenix vs. itself is about 5% red; show a similar city like Tucson (low) against NYC and London (high).
- **"Why not the Waymo Open Dataset?"** It has no weather or infrastructure layers. Running the identical pipeline on both cities is a fair comparison.
- **"Doesn't Waymo simulate this already?"** This is complementary. It uses only public data to pick what's worth simulating.
- **"OSM quality varies."** We show a completeness indicator, and the core features rely on things that are almost always mapped.

## 12. Cuts and stretch goals
- **Cut first:** GTFS, extra place categories, Street View, comparison-view polish.
- **Never cut:** search → heatmap → "why" panel → scenario cards.
- **Stretch:**
  - Multi-city reference (Phoenix + SF + LA = "everywhere Waymo drives")
  - GTFS transit frequency
  - Exporting scenarios as JSON
  - LLM-polished scenario text
