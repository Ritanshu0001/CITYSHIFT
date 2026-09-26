"""Build features.csv, city.json and meta.json for one city (data half only).

    python scripts/run_city.py "Phoenix, AZ, USA" 33.4484 -112.0740 --country US
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import build_city_data  # noqa: E402
from app.schemas import HEX_FEATURES  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("lat", type=float)
    ap.add_argument("lng", type=float)
    ap.add_argument("--country", default=None, help="ISO alpha-2, e.g. US, GB")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    t0 = time.perf_counter()
    df, city, meta = build_city_data(args.name, args.lat, args.lng, args.country, progress=lambda s: print(f"-> {s}"))

    print(f"\nslug: {city['slug']}")
    print(f"hexes: {city['n_hexes_kept']} kept of {city['n_hexes_total']}")
    print(f"country: {city['country_code']}  driving_side: {city['driving_side']}")
    print(f"climate: rain {city['rain_days_per_year']}  heavy {city['heavy_rain_days_per_year']}  "
          f"snow {city['snow_days_per_year']} days/yr")
    print(f"osm_completeness: {city['osm_completeness']}")
    print("\ncolumn          mean      nonzero_share")
    for col in ["road_km", *HEX_FEATURES, "avg_lanes"]:
        s = df[col]
        print(f"  {col:24s} {s.mean():10.3f}  {(s > 0).mean():6.2f}")
    print("\ntimings (s):", meta["timings_s"], f" total {time.perf_counter() - t0:.1f}")


if __name__ == "__main__":
    main()
