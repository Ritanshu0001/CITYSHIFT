# CityShift judge Q&A card

Owner: P2. One page to hold while presenting. Read the **scripted answer** out loud;
the **presenter note** is only for when a judge pushes back.

The four scripted answers are SOURCE-PLAN.md section 11 word for word. Where an answer
is challengeable, the fallback lives in the presenter note rather than replacing the
script (CR-004).

> Numbers are the committed results at `519fd30` (pooled reference). Refresh after the
> CR-011 terrain refit.

---

## 1. "Does the score mean anything?"

**Scripted answer:** Phoenix vs. itself is about 5% red; show a similar city like Tucson
(low) against NYC and London (high).

**Show:** the reference pool scores **5.0% red across 1,153 hexes** against itself.
Tucson **3.2%**, New York **30.4%**, London **46.3%**.

**Presenter note:** the ~5% is by construction, not luck — red is defined as the 95th
percentile of the reference's own distribution, so the reference must land near 5%. That
is the point: it makes the scale auditable. The real signal is the spread between Tucson
(3.2%, sitting in among the reference cities) and London (46.3%). If asked whether we
tuned it: no. `IsolationForest(random_state=42)`, one artifact committed to the repo,
identical 8 km / H3-res-8 geometry for every city including the reference ones.

**If asked why the reference is five cities:** a single-city reference made every dense
city look extreme. Pooling Phoenix, San Francisco, Los Angeles, Austin and Atlanta —
1,153 hexes, equal weight per hex — asks the sharper question: is this unlike *anywhere*
the cars already operate? It roughly halved every score (London went 73.0% to 46.3%).

---

## 2. "Why not the Waymo Open Dataset?"

**Scripted answer:** It has no weather or infrastructure layers. Running the identical
pipeline on both cities is a fair comparison.

**Presenter note — use this if a judge corrects you.** The Waymo Open Motion Dataset
*does* ship a roadgraph with lanes, crosswalks and stop signs, so do not defend the
literal claim. Concede and pivot:

> "Fair — the Motion Dataset does have a roadgraph. The limitation we care about is
> coverage: it describes the cities it was collected in. CityShift is for ranking the
> cities nobody has collected in yet, which is why we only use data that exists
> worldwide."

Agreed by P1 and P2 at the sync (CR-004).

---

## 3. "Doesn't Waymo simulate this already?"

**Scripted answer:** This is complementary. It uses only public data to pick what's
worth simulating.

**Presenter note:** stay on the tagline. Do not claim Waymo lacks this capability and do
not suggest we teach a car to drive; SOURCE-PLAN.md section 1 rules both out.

---

## 4. "OSM quality varies."

**Scripted answer:** We show a completeness indicator, and the core features rely on
things that are almost always mapped.

**Show:** `osm_completeness` — the fraction of drive-network edges carrying a `maxspeed`
or `lanes` tag. Phoenix is **0.966**.

**Presenter note:** volunteer the counting-convention caveat, it makes us look careful.
Phoenix has a bulk sidewalk import, so it counts ~25,000 `highway=crossing` points
including `crossing=unmarked`, giving a crosswalk median near 97/km². That inflates one
reference baseline. Found, measured, documented (CR-001, CR-008).

---

## Questions not in the script

**"Where does elevation come from?"** Copernicus DEM GLO-90 via Open-Meteo. Important
caveat we volunteer: it is a *surface* model, so it includes buildings. Chicago's five
steepest hexes are all downtown — the Loop's towers on flat ground, not a hill. We
checked the `steep_grade` card does not fire there: the gate is **6.54%** and Chicago's
steepest hex is **4.40%**. San Francisco fires 40 hexes and San Diego 16, which is real
terrain; Phoenix, Atlanta and Chicago fire none.

**"How long does a new city take?"** First run is a live pull; repeats are instant
because `cache/{slug}/result.json` is the source of truth. Thirteen cities are
pre-cached, so the backup demo runs offline from a clone.

**"Is there an LLM in this?"** Not in the core path. Every card is a deterministic rule
with its trigger shown in `triggered_by`. LLM polish is a stretch goal, off by default.
No demo surprises, every card auditable.

**"What's your feature set?"** 18 per-hex features across network, road mix, control,
vulnerable road users, activity, infrastructure and terrain, plus city-level climate and
driving side.

**"Isn't a rule that fires in every city useless?"** Fair, and it applies to our
roundabout/tunnel card. On counts that sparse a z > 2 bar works out to roughly "present
at all", so it fires everywhere and currently tops 7 of 12 cities. It is honest as a
*presence* signal, but we would write it as `count > 0` rather than dress it as a
threshold. We have a ranking fix prototyped that subtracts the rate the reference itself
fires at — under it, the reference cities correctly drop to no cards.

**"What would you fix next?"** Three things, all measured rather than guessed. The
crosswalk rule cannot fire because the inflated Phoenix baseline puts its gate at 788
crossings/km²; the fix is agreed and pending sign-off. The roundabout card needs the
ranking fix above. And the terrain refit is still to land.

---

## Numbers cheat sheet

Reference pool (Phoenix, SF, LA, Austin, Atlanta): **5.0% red over 1,153 hexes.**

| City | Red | City | Red |
|---|---:|---|---:|
| Phoenix (ref) | 2.2% | Boston | 13.2% |
| Atlanta (ref) | 2.8% | San Francisco (ref) | 13.7% |
| Tucson | 3.2% | Miami | 18.0% |
| Los Angeles (ref) | 4.1% | Chicago | 18.2% |
| Austin (ref) | 5.6% | Tokyo | 21.9% |
| | | New York | 30.4% |
| | | London | 46.3% |

Geometry: 8 km radius, H3 resolution 8, hexes under 0.5 km of road dropped. Bands: green
under 80, yellow 80–95, red 95+.

Climate reference is the per-metric max across the five cities: 141.0 rain days
(Atlanta), 24.6 heavy-rain days (Atlanta), 0.8 snow days (Austin).

Terrain (median / p95 percent grade): Phoenix 0.44 / 1.15, Chicago 0.17 / 1.18,
San Diego 1.04 / 7.33, San Francisco 1.42 / 9.02.

Sources: OpenStreetMap via OSMnx; Open-Meteo Historical Weather API (2020-01-01 to
2024-12-31); **Elevation: Copernicus DEM GLO-90 via Open-Meteo**; Google Maps
JavaScript API.

---

## Do not say

- Do not say Waymo cannot do this, or that we are teaching a car to drive.
- Do not call the shift score a safety or risk score. It measures how *unlike the
  reference cities* an area is. Unusual is not the same as dangerous.
- Do not quote a number that is not on this card or in the committed `result.json`.
- Do not defend the literal "no infrastructure layers" claim about the Waymo dataset.
- Do not call a steep hex a hill without checking it is not a downtown block.
