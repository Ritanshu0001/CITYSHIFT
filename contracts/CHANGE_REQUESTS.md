# Change requests

Append only. Resolved together at the sync checkpoints (hours 0.5, 4, 6, 8, 12, 14). See CONTRACTS.md section 6.

Format:

```
## CR-001  (P3, 06:40)  Need hex center lat/lng in hexes[]
Why: Street View needs a position.
Workaround: computing it client-side with h3-js cellToLatLng.
Status: open
```

---

## CR-001  (P1, hour 4)  Clarifications of contract 4.3 as implemented (no shape change)
Why: P2 and P3 should know how P1 read the ambiguous parts before fitting Phoenix.
- Row counts: Phoenix keeps 229 of 235 hexes, not ~270. H3 res-8 cell area varies with latitude (Phoenix ~0.86 km², London ~0.67 km²), so an 8 km circle holds 230 to 300 cells. Grid code follows the contract exactly.
- `road_km` and every edge count use each physical road once: the drive graph's u->v / v->u copies of two-way streets are deduped. Without this, two-way streets count double and `oneway_share` is biased low.
- OSM list tags: OSMnx builds them with list(set(...)), whose order changes per process, so "first value" is taken after sorting. Phoenix re-runs are byte-identical.
- `transit_stop_density`: a feature carrying several transit tags (bus_stop + platform) counts once.
- `crosswalk_density` counts every `highway=crossing` point, including `crossing=unmarked`. Phoenix has ~25k of them (sidewalk import), so its median is ~97/km².
- Slugs fold accents before the contract rule ("São Paulo, Brazil" -> `sao-paulo-brazil`).
- P3: send Google Places' formatted address as `name` ("New York, NY, USA", "London, UK", "Tokyo, Japan") so searches hit the pre-cached slugs.
Status: info

## CR-002  (P2, hour 8)  Pin the four libraries the reference artifact is pickled with
Why: `backend/app/model/reference/phoenix_reference.joblib` is a pickle of a fitted
StandardScaler and IsolationForest. D4 says scoring must be identical on every laptop,
but requirements.txt is unpinned, so a teammate resolving a different scikit-learn gets
an InconsistentVersionWarning at best and an unpickle failure at worst.
Workaround: P2 appended `scikit-learn==1.7.2`, `numpy==2.2.6`, `pandas==2.3.3`,
`joblib==1.6.0` to requirements.txt (append-only is all D13 allows P2). pip merges the
duplicate names without error, but the file now lists each of those four twice.
Ask: P1 folds them into one pinned line each when replacing the file with pip freeze.
`save_reference` records `library_versions` in reference_meta.json and `load_reference`
raises a RuntimeWarning on drift, so a mismatch is loud rather than silent either way.
Status: open

## CR-003  (P2, hour 12)  .gitignore excludes the pitch deliverables
Why: `.gitignore` ends with `*.md` / `!README.md` for planning docs (team decision), but
that also swallows `pitch/DEVPOST.md`, `pitch/P2-MODEL-SCENARIOS-PITCH.md` and
`pitch/Q&A.md`, which section 2 lists as P2 deliverables. A teammate cloning the repo
gets no deck, no Q&A card and no Devpost text, and the backup-demo machine has no pitch.
Workaround: the files exist locally and are shared directly, like CONTRACTS.md.
Ask: P1 adds `!pitch/*.md` (or unignores `pitch/`) since .gitignore is P1-owned.
Status: open

## CR-004  (P2, hour 12)  One scripted Q&A answer is factually challengeable
Why: SOURCE-PLAN.md section 11 answers "Why not the Waymo Open Dataset?" with "It has no
weather or infrastructure layers." The Waymo Open Motion Dataset does include a roadgraph
with lanes, crosswalks and stop signs, so a Waymo judge can correct us mid-pitch. The plan
tells P2 to use section 11 word for word, so P2 has not changed it.
Workaround: pitch/Q&A.md keeps the scripted wording and adds a presenter note with a
defensible fallback (the dataset covers cities it was collected in; CityShift ranks cities
nobody has collected in yet).
Ask: all three agree either the original wording or the fallback before the rehearsal.
Status: open

## CR-005  (P1 + P2, hour 12)  roundabout_or_tunnel cannot fire on real Phoenix
Why: P1 reports that on the real caches only `movable_bridge_count` falls under
RARE_PRESENCE_THRESHOLD; tunnel, roundabout and stadium counts are all above 1%.
Contract 4.7 phrases the rule as "any hex with roundabout_count or tunnel_count in
novel", and novel only ever holds rare features, so the card can never be produced.
`stadium_event` is unaffected because 4.7 defines it on `stadium_count > 0`.
Workaround: none in code. P2 will not retune a threshold alone (contract section 5
rule 6), so the rule currently produces nothing on real data.
Ask: change the 4.7 trigger to `roundabout_count z > 2 OR tunnel_count z > 2`, which
keeps it on modeled features and keeps priority on the real z magnitude rather than
NOVEL_Z_EQUIVALENT. Needs all three at the sync; P2 ships it the same hour.
Status: open

## CR-006  (P1, hour 12)  Contract 4.3 example city.json is stale; use the real Phoenix numbers
Why: The 4.3 example lists Phoenix as rain 33.0, heavy 0.6, 271 -> 248 hexes, completeness 0.71. The committed cache (and the reference artifact, 325e85c) has rain 29.0, heavy 3.4, 235 -> 229 hexes, completeness 0.966. Sanity-check against cache/phoenix-az-usa/city.json, not the example.
Effect: the 4.7 "much rainier" threshold is 2 x 29.0 = 58.0 rain days, not 66.0. 8 of 12 cached cities clear it; SF (55.2) is under both, so no scenario card changes. Section 3 constants are unaffected.
Proposed: at the next sync, replace the example values in 4.3 with the real ones (all three present, since CONTRACTS.md is frozen).
Status: open

## CR-007  (P1, hour 12)  P1 responses to CR-002, CR-003, CR-005
- CR-002: done. requirements.txt was replaced with `pip freeze` on Python 3.11 and has one pin each: scikit-learn 1.9.1, numpy 2.4.6, pandas 3.0.6, joblib 1.6.0. These match `library_versions` in the committed reference_meta.json (325e85c). The P2 duplicate lines are gone; only `pytest` is appended. Proposed status: resolved.
- CR-003: done. `.gitignore` on main now ignores only `/contracts/` and `/plans/`; `*.md` is no longer ignored, so `pitch/*.md` and `demo/*.md` are tracked (checked with `git check-ignore`). Proposed status: resolved.
- CR-005: P1 confirms the data. Phoenix presence (share of 229 hexes with value > 0): movable_bridge_count 0.0%, stadium_count 2.6%, tunnel_count 5.7%, roundabout_count 7.0%, bridge_count 34.5%. Only movable_bridge_count is rare. P1 supports the proposed z > 2 trigger; no data or API change needed on P1's side.
Status: info

## CR-008  (P2, hour 13)  crosswalk_wide_arterial also cannot fire on real data
Why: CR-005 found one dead rule in 4.7; there is a second, with a different cause.
`crosswalk_wide_arterial` fires in 0 of the 12 committed result.json files. This is not a
code bug: scenarios.py implements the trigger exactly as 4.7 states it,
`(crosswalk_density z > 2) & (arterial_share z > 1)`. The `arterial_share` half is
healthy (6 to 38 hexes per city). The `crosswalk_density` half is unsatisfiable.
Cause: this is CR-001's unmarked-crossing note biting the scoring side. Phoenix counts
every `highway=crossing` including `crossing=unmarked`, so the reference's own
crosswalk_density is median 97.4/km² with a log1p mean 4.215 and std 1.228. z > 2
therefore means a raw value above 788.5 crossings/km². The highest crosswalk z in any hex
of any of the 12 cities is 1.79 (Atlanta); Phoenix itself tops out at 1.49. Because
Phoenix is the reference, its inflated baseline raises the bar for every target city.
Measured, hexes with `arterial_share z > 1` AND crosswalk z above each threshold:
  z > 2.0 -> 0 hexes,  0 of 12 cities  (current spec)
  z > 1.5 -> 10 hexes, 5 of 12 cities
  z > 1.0 -> 88 hexes, 11 of 12 cities  (Phoenix itself only 1 hex)
  z > 0.5 -> 138 hexes, 12 of 12 cities (Phoenix 8 hexes; too loose)
Ask: change the 4.7 trigger to `crosswalk_density z > 1 AND arterial_share z > 1`. At
z > 1 the card appears in 11 of 12 cities while the reference city stays effectively
quiet, which is the behaviour the rule was written for.
Alternative, if the team prefers not to move a threshold: exclude `crossing=unmarked`
from `crosswalk_density` in P1's feature code. That addresses the root cause but is a
feature-definition change, and it forces a Phoenix refit plus a re-run of all 12 caches.
P2 will not retune alone (section 5 rule 6), so this needs all three like CR-005.
Status: open

## CR-009  (P2, hour 13)  P2 responses to CR-002, CR-003, CR-004, CR-005, CR-006, CR-007
- CR-002: verified resolved. requirements.txt has one pin each and no duplicate names at
  all (checked with uniq -d over the whole file); the four match `library_versions` in the
  committed reference_meta.json exactly. Agreed: resolved.
- CR-003: the .gitignore half is verified resolved (`git check-ignore` clears
  pitch/DEVPOST.md, pitch/Q&A.md and demo/SCRIPT.md; only /contracts/ and /plans/ are
  ignored). But the CR cannot close yet: `pitch/` on main contains only `.gitkeep`, and
  the three deliverables do not exist on P2's machine either, so there is nothing to
  commit. The "files exist locally and are shared directly" workaround is not true as
  written. P2 must author pitch/DEVPOST.md, pitch/P2-MODEL-SCENARIOS-PITCH.md and
  pitch/Q&A.md before this is resolved. Proposed status: unblocked, pending P2 authoring.
- CR-004: agreed, use the fallback wording. With P1's vote that is 2 of 3; needs P3.
- CR-005: P2 confirms P1's presence data independently from the committed artifact, to
  the decimal: movable_bridge_count 0.0%, stadium_count 2.6%, tunnel_count 5.7%,
  roundabout_count 7.0%, bridge_count 34.5%. Only movable_bridge_count is under the 1%
  threshold. Confirmed dead in practice: `roundabout_or_tunnel` appears in 0 of 12
  result.json files, while `movable_bridge` appears in 6, so the novel mechanism itself
  works and only the roundabout/tunnel wiring is wrong. P2 is ready to ship the
  `z > 2` trigger; still waiting on P3 per this CR's own "needs all three".
- CR-006: agreed, no action on P2's side. The artifact already carries the real values
  (`phoenix_city` in the artifact is byte-equal to cache/phoenix-az-usa/city.json).
- CR-007: all three P1 claims independently verified by P2. Slide numbers confirmed two
  ways: the committed result.json files and a full --recompute give an identical table
  (Phoenix 4.8, Tucson 5.9, Atlanta 8.4, LA 9.4, Austin 12.1, SF 32.9, Miami 34.3,
  Boston 36.1, Chicago 37.1, Tokyo 38.4, NY 58.1 +snow, London 73.0 +left_hand_traffic).
Status: info

## CR-010  (all, sync)  Multi-city reference: Waymo's established cities
(Proposed as "CR-008"; renumbered because CR-008 is the crosswalk trigger.)
Why: One 8 km Phoenix circle understates what the car knows. Waymo's longest-running
paid markets are Phoenix, San Francisco, Los Angeles, Austin and Atlanta, all already cached.
Decision:
- Reference = phoenix-az-usa, san-francisco-ca-usa, los-angeles-ca-usa, austin-tx-usa,
  atlanta-ga-usa, pooled: ~1,153 hexes, equal weight per hex (no mileage weighting in v1).
- Rare = present in < 1% of pooled hexes. Percentile, z, pct, ref_median all use the pooled hexes.
- Climate reference = per-metric MAX across the 5 cities (the car already drives in Atlanta's rain).
  "Much rainier" = target rain_days_per_year > max reference (replaces 2x Phoenix).
  Snow novel = target snow >= 2 AND max reference snow < 1. Left-hand traffic unchanged.
- CityResult JSON shape unchanged. summary.climate.reference now holds the per-metric max.
- UI label: "Waymo's established cities" replaces "Phoenix".
- New constants: REFERENCE_SLUGS (list of 5), REFERENCE_LABEL. REFERENCE_SLUG stays for compatibility.
- Phoenix-only results are tagged v1-phoenix-reference (3644f92) for the before/after slide.
Status: approved at sync

## CR-011  (P3, hour 14)  P3 decisions on CR-004 and CR-008
- CR-004: approved. Use the defensible fallback wording: the Waymo Open Dataset does
  include roadgraph and infrastructure information, but it covers locations already
  collected; CityShift uses public data to rank and prepare candidate cities before a
  dedicated Waymo collection exists.
- CR-008: approved. Change the trigger to `crosswalk_density z > 1 AND arterial_share
  z > 1`. P3 rechecked the rule after CR-010 against the pooled five-city reference:
  z > 2 still fires in 0 of 12 cached cities, while z > 1 fires in 11 of 12 and affects
  only one Phoenix hex. P3 will verify the re-scored scenario cards in the UI after P2
  ships the rule.
Status: approved by P3
