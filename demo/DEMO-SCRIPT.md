# CityShift demo script

Target length: about 2.5 minutes.

## 0:00–0:20 — Hook

“An autonomous car may know a city's laws. Does it know the city?”

Open CityShift on the homepage. Explain that the reference pools Waymo's established cities—Phoenix, San Francisco, Los Angeles, Austin, and Atlanta—and that every city is measured over the same 8 km area.

## 0:20–0:45 — Pick a city

Ask for a city, select it in search, and start the analysis. While the five progress steps advance, explain that CityShift combines public road, infrastructure, place, and five-year weather data.

If the live request is slow, use the cached-city row and say: “Here’s one we ran earlier.”

## 0:45–1:25 — Read the map

Point out the legend: green is within the established-city baseline, yellow is notable, and red means the area is more unusual than at least 95% of the pooled reference areas.

Select a red hex. Read its score sentence and the top three signals. If the selected area has a novel-feature warning, call it out. Show Street View when available.

## 1:25–1:55 — Compare the cities

Open Compare. Show climate days, driving side, OSM completeness, novel conditions, and the largest median feature shifts. Explain that feature comparisons use the pooled five-city reference, while climate uses the maximum across those cities.

## 1:55–2:25 — Candidate scenarios

Open Scenarios and select the highest-priority card. Show how its affected hexes highlight on the map and read the “Triggered by” evidence. Mention that scenario rules are deterministic; no LLM is in the core path.

## 2:25–2:30 — Close

“Waymax tests the scenario. CityShift finds the scenario worth testing.”

## Recording checklist

- Use a cached New York or London result for the clean take.
- Confirm New York shows 30.4% strong shift and London shows 46.3%.
- For London, confirm the top card is “Mirrored turn logic; turns across oncoming traffic.”
- Confirm the Maps key and Street View before recording.
- Hide development tools and notifications.
- Record a live path once and a cached backup once; keep the cleaner take.
