"""Build the Safe Journey routing graph for every ride city, so each opens without a download.

    python scripts/prebuild_routes.py               # every US city with result.json; skips built ones
    python scripts/prebuild_routes.py --only boston-ma-usa chicago-il-usa
    python scripts/prebuild_routes.py --rebuild     # rebuild even if a graph exists

The committed cache/{slug}/ has the analysis but not the road network. A city analysed on
this machine reads its roads from backend/osmnx_cache/ (no network); one analysed elsewhere
downloads them from Overpass once (~15-60 s). Graphs land in backend/route_cache/ (per machine,
gitignored). Cities run one at a time; don't run this alongside precache.py, which also uses Overpass.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import ride_api  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", metavar="SLUG", help="build just these slugs")
    ap.add_argument("--rebuild", action="store_true", help="replace existing graphs")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    slugs = ride_api.ride_slugs()
    if args.only:
        unknown = sorted(set(args.only) - set(slugs))
        if unknown:
            sys.exit(f"not a ride city (US, with result.json): {', '.join(unknown)}")
        slugs = [s for s in slugs if s in args.only]

    built = skipped = failed = 0
    for slug in slugs:
        if args.rebuild:
            ride_api._pickle_path(slug).unlink(missing_ok=True)
        t = time.perf_counter()
        try:
            if ride_api.prebuild(slug):
                built += 1
                print(f"ok    {slug:28s} ({time.perf_counter() - t:.0f}s)", flush=True)
            else:
                skipped += 1
                print(f"skip  {slug:28s} graph exists", flush=True)
        except Exception as exc:  # noqa: BLE001 - one failed city shouldn't stop the rest
            failed += 1
            print(f"FAIL  {slug:28s} {exc}  ({time.perf_counter() - t:.0f}s)", flush=True)
    print(f"{built} built, {skipped} already built, {failed} failed")


if __name__ == "__main__":
    main()
