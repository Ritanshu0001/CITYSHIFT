"""Generate small deterministic feature tables for local model development."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import h3
import numpy as np
import pandas as pd

from app.schemas import FEATURE_CSV_COLUMNS, H3_RES, REFERENCE_CENTER

# A grid_disk of radius 9 is 3*9*9 + 3*9 + 1 = 271 cells, which matches the
# hex count contract 4.3 shows for an 8 km radius at H3 resolution 8.
GRID_RADIUS = 9
TARGET_CENTER = {"lat": 40.7128, "lng": -74.0060}  # a second real center, so ids differ


def _cells(center: dict, n_rows: int) -> list[str]:
    """Real H3 v4 cell ids around a center, ordered deterministically."""
    origin = h3.latlng_to_cell(center["lat"], center["lng"], H3_RES)
    cells = sorted(h3.grid_disk(origin, GRID_RADIUS))
    if len(cells) < n_rows:
        raise ValueError(f"grid_disk({GRID_RADIUS}) gave {len(cells)} cells, need {n_rows}")
    return cells[:n_rows]


def _table(rng: np.random.Generator, n_rows: int, target: bool = False) -> pd.DataFrame:
    cells = _cells(TARGET_CENTER if target else REFERENCE_CENTER, n_rows)
    data: dict[str, object] = {
        "h3": cells,
        "area_km2": [h3.cell_area(cell, unit="km^2") for cell in cells],
        "road_km": rng.lognormal(np.log(1.2), 0.25, n_rows),
        "intersection_density": rng.lognormal(np.log(30 if not target else 68), 0.35, n_rows),
        "road_density": rng.lognormal(np.log(12), 0.3, n_rows),
        "arterial_share": rng.beta(3, 8, n_rows),
        "motorway_share": rng.beta(1.5, 15, n_rows),
        "oneway_share": rng.beta(3, 5, n_rows),
        "signal_density": rng.lognormal(np.log(4 if not target else 9), 0.4, n_rows),
        "crosswalk_density": rng.lognormal(np.log(6 if not target else 12), 0.4, n_rows),
        "bike_lane_density": rng.lognormal(np.log(2 if not target else 7), 0.5, n_rows),
        "transit_stop_density": rng.lognormal(np.log(3 if not target else 10), 0.45, n_rows),
        "school_density": rng.lognormal(np.log(1.2), 0.55, n_rows),
        "nightlife_density": rng.lognormal(np.log(1.5 if not target else 8), 0.6, n_rows),
        "tourism_density": rng.lognormal(np.log(1.0), 0.55, n_rows),
        "bridge_count": np.zeros(n_rows),
        "movable_bridge_count": np.zeros(n_rows),
        "tunnel_count": np.zeros(n_rows),
        "roundabout_count": np.zeros(n_rows),
        "stadium_count": np.zeros(n_rows),
        "avg_lanes": rng.uniform(1.5, 3.5, n_rows),
    }
    if not target:
        data["movable_bridge_count"] = (rng.random(n_rows) < 0.003).astype(float)
        data["tunnel_count"] = (rng.random(n_rows) < 0.003).astype(float)
        data["roundabout_count"] = (rng.random(n_rows) < 0.003).astype(float)
    else:
        for name, count in (("movable_bridge_count", 4), ("tunnel_count", 3), ("roundabout_count", 5), ("stadium_count", 2)):
            data[name] = np.zeros(n_rows)
            data[name][:count] = 1
    return pd.DataFrame(data, columns=FEATURE_CSV_COLUMNS)


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    output.mkdir(parents=True, exist_ok=True)
    phoenix = _table(np.random.default_rng(42), 270)
    target = _table(np.random.default_rng(43), 270, target=True)
    phoenix.to_csv(output / "fake_phoenix_features.csv", index=False)
    target.to_csv(output / "fake_target_features.csv", index=False)
    city = {
        "name": "Phoenix, AZ, USA", "slug": "phoenix-az-usa", "lat": 33.4484, "lng": -112.0740,
        "radius_km": 8, "country_code": "US", "driving_side": "right",
        "rain_days_per_year": 33.0, "heavy_rain_days_per_year": 0.6, "snow_days_per_year": 0.0,
        "osm_completeness": 0.71, "n_hexes_total": 270, "n_hexes_kept": 270, "created_at": "fixture",
    }
    (output / "fake_city.json").write_text(json.dumps(city, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(phoenix)} phoenix rows and {len(target)} target rows to {output}")
    print(f"  phoenix h3[0]={phoenix['h3'].iloc[0]}  area_km2={phoenix['area_km2'].iloc[0]:.3f}")


if __name__ == "__main__":
    main()
