"""Run the demo and validation cities (CONTRACTS.md section 7) one at a time.

    python scripts/precache.py              # full analyze_city; skips cities with result.json
    python scripts/precache.py --data-only  # features.csv + city.json only (before P2's model exists)
    python scripts/precache.py --data-only --refresh-data  # rebuild data even if it exists; reuses climate
    python scripts/precache.py --rescore    # re-score cached features after a model/rule change (offline)
    python scripts/precache.py --only tokyo-japan london-uk
    python scripts/precache.py --cities data/saved_cities.json   # a JSON list of {name, lat, lng, country_code}

Names follow Google Places' formatted address so a search from the UI hits the same slug.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cache  # noqa: E402
from app.data import openmeteo  # noqa: E402
from app.pipeline import analyze_city, build_city_data, score_cached  # noqa: E402

CITIES = [
    # name, lat, lng, country_code
    ("Phoenix, AZ, USA", 33.4484, -112.0740, "US"),
    ("Tucson, AZ, USA", 32.2226, -110.9747, "US"),
    ("San Francisco, CA, USA", 37.7749, -122.4194, "US"),
    ("Los Angeles, CA, USA", 34.0522, -118.2437, "US"),
    ("San Diego, CA, USA", 32.7157, -117.1611, "US"),
    ("Austin, TX, USA", 30.2672, -97.7431, "US"),
    ("Atlanta, GA, USA", 33.7490, -84.3880, "US"),
    ("Miami, FL, USA", 25.7617, -80.1918, "US"),
    ("New York, NY, USA", 40.7128, -74.0060, "US"),
    ("Chicago, IL, USA", 41.8781, -87.6298, "US"),
    ("Boston, MA, USA", 42.3601, -71.0589, "US"),
    ("London, UK", 51.5074, -0.1278, "GB"),
    ("Tokyo, Japan", 35.6762, 139.6503, "JP"),
]


def _rescore(slug: str) -> None:
    """Re-score one cached city and print what changed: pct_red and scenario cards."""
    if not (cache.city_dir(slug) / "features.csv").is_file():
        print(f"skip  {slug:28s} no features.csv (run --data-only first)")
        return
    before = cache.read_json(slug, "result.json") if cache.has_result(slug) else None
    after = score_cached(slug)
    old_ids = {c["id"] for c in before["scenarios"]} if before else set()
    new_ids = {c["id"] for c in after["scenarios"]}
    red = after["summary"]["pct_red"]
    red_note = f"{before['summary']['pct_red']} -> {red}" if before else f"{red}"
    changes = [f"+{i}" for i in sorted(new_ids - old_ids)] + [f"-{i}" for i in sorted(old_ids - new_ids)]
    print(f"ok    {slug:28s} red {red_note}%  cards {len(new_ids)}  {' '.join(changes) or 'no card changes'}",
          flush=True)


def _known_climate(slug: str) -> dict | None:
    """Climate from an existing city.json when it is present and non-zero, else None.

    2020-2024 history never changes, so a refresh reuses it instead of spending
    ~130 Open-Meteo calls per city. Zero rain would be a failed fetch: refetch it.
    """
    path = cache.city_dir(slug) / "city.json"
    if not path.is_file():
        return None
    city = cache.read_json(slug, "city.json")
    keys = ["rain_days_per_year", "heavy_rain_days_per_year", "snow_days_per_year"]
    if any(k not in city for k in keys) or city["rain_days_per_year"] <= 0 or city["heavy_rain_days_per_year"] <= 0:
        return None
    return {k: city[k] for k in keys}


def _quota_error(exc: BaseException) -> BaseException | None:
    """The OpenMeteoQuotaError behind exc (pipeline wraps errors in StepError), if any."""
    while exc is not None:
        if isinstance(exc, openmeteo.OpenMeteoQuotaError):
            return exc
        exc = exc.__cause__
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-only", action="store_true", help="skip P2's scoring; write features.csv + city.json")
    ap.add_argument("--rescore", action="store_true",
                    help="rebuild result.json from cached features.csv + city.json (no downloads)")
    ap.add_argument("--refresh-data", action="store_true",
                    help="with --data-only: rebuild features.csv, city.json, meta.json even if they exist "
                         "(OSM from osmnx_cache; climate reused from city.json)")
    ap.add_argument("--only", nargs="*", metavar="SLUG", help="run just these slugs")
    ap.add_argument("--cities", type=Path, metavar="FILE",
                    help="JSON list of {name, lat, lng, country_code} to run instead of the demo cities")
    args = ap.parse_args()
    if args.rescore and args.data_only:
        ap.error("--rescore and --data-only are opposites; pick one")
    if args.refresh_data and not args.data_only:
        ap.error("--refresh-data goes with --data-only (then --rescore once the model is refit)")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    failed = 0
    cities = CITIES
    if args.cities:
        rows = json.loads(args.cities.read_text(encoding="utf-8"))
        cities = [(r["name"], r["lat"], r["lng"], r["country_code"]) for r in rows]
    todo = [c for c in cities if not args.only or cache.slugify(c[0]) in args.only]
    for index, (name, lat, lng, cc) in enumerate(todo):
        slug = cache.slugify(name)
        if args.rescore:
            try:
                _rescore(slug)
            except Exception as exc:  # noqa: BLE001 - keep going; report at the end
                failed += 1
                print(f"FAIL  {slug:28s} {exc}", flush=True)
            continue
        if args.data_only and not args.refresh_data and (cache.city_dir(slug) / "features.csv").is_file():
            print(f"skip  {slug:28s} features.csv exists")
            continue
        if not args.data_only and cache.has_result(slug):
            print(f"skip  {slug:28s} result.json exists")
            continue
        t = time.perf_counter()
        try:
            if args.data_only:
                known = _known_climate(slug) if args.refresh_data else None
                _, city, meta = build_city_data(name, lat, lng, cc, climate=known)
                detail = (f"{city['n_hexes_kept']} hexes, driving {city['driving_side']}, "
                          f"climate {meta['climate_source']}, ~{meta['openmeteo_calls_estimate']:.0f} Open-Meteo calls")
            else:
                analyze_city(name, lat, lng, cc)
                summary = cache.read_json(slug, "result.json")["summary"]
                detail = f"{summary['n_hexes']} hexes, {summary['pct_red']}% red"
            print(f"ok    {slug:28s} {detail}  ({time.perf_counter() - t:.0f}s)", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep going; report at the end
            failed += 1
            print(f"FAIL  {slug:28s} {exc}  ({time.perf_counter() - t:.0f}s)", flush=True)
            if _quota_error(exc):
                # Retrying against a quota error only burns more of it: stop the batch now.
                left = [cache.slugify(c[0]) for c in todo[index + 1:]]
                print(f"STOP  Open-Meteo quota exceeded; not attempted: {', '.join(left) or 'none'}", flush=True)
                break
    print(f"Open-Meteo: ~{openmeteo.run_total():.0f} calls sent this run (cache hits are free)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
