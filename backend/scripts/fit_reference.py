"""Fit and save the reference artifact (CR-010: Waymo's established cities, pooled).

    python scripts/fit_reference.py --out app/model/reference            # real fit on REFERENCE_SLUGS
    python scripts/fit_reference.py --out app/model/reference --force    # replace an existing artifact
    python scripts/fit_reference.py --features tests/fixtures/fake_phoenix_features.csv \\
        --city tests/fixtures/fake_city.json --out tests/fixtures/reference   # fixture, local dev only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from app.model.reference import (
    DEFAULT_REFERENCE_DIR,
    FIXTURE_CREATED_AT,
    fit_pooled_reference,
    reference_climate,
    save_reference,
)
from app.schemas import BAND_RED, REFERENCE_SLUGS

DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "cache"


def _pooled_self_red(artifact: dict) -> float:
    """Share of the pooled reference hexes that score red against themselves (expect ~5%)."""
    log_values = np.log1p(artifact["phoenix_raw"].loc[:, artifact["feature_order"]].to_numpy())
    scores = -artifact["iforest"].score_samples(artifact["scaler"].transform(log_values))
    sorted_scores = artifact["phoenix_scores_sorted"]
    percentiles = np.round(np.searchsorted(sorted_scores, scores, side="left") / len(sorted_scores) * 100, 1)
    return float((percentiles >= BAND_RED).mean() * 100)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="cache/ holding the reference cities")
    parser.add_argument("--slugs", nargs="+", default=REFERENCE_SLUGS,
                        help="reference cities; must be exactly REFERENCE_SLUGS (any order)")
    parser.add_argument("--features", type=Path, help="fixture only: one features.csv")
    parser.add_argument("--city", type=Path, help="fixture only: its city.json")
    parser.add_argument("--force", action="store_true", help="overwrite an existing artifact in --out")
    args = parser.parse_args()

    if bool(args.features) != bool(args.city):
        parser.error("--features and --city go together")

    if args.features:
        # Single-table fits exist for fixtures only. A real reference is always the
        # pooled REFERENCE_SLUGS, so a one-city fit would silently rescale every score.
        city = json.loads(args.city.read_text(encoding="utf-8"))
        if city.get("created_at") != FIXTURE_CREATED_AT:
            print(f"error: {args.city} is not a fixture. Real references are fitted on all of "
                  f"REFERENCE_SLUGS from --cache (CR-010); drop --features/--city.", file=sys.stderr)
            return 2
        frames, cities = [pd.read_csv(args.features)], [city]
    else:
        if set(args.slugs) != set(REFERENCE_SLUGS) or len(args.slugs) != len(REFERENCE_SLUGS):
            print(f"error: reference slugs must be exactly REFERENCE_SLUGS {REFERENCE_SLUGS} "
                  f"(CR-010), got {args.slugs}.", file=sys.stderr)
            return 2
        # Always pool in REFERENCE_SLUGS order: row order feeds the IsolationForest.
        frames, cities = [], []
        for slug in REFERENCE_SLUGS:
            city_dir = args.cache / slug
            if not (city_dir / "features.csv").is_file() or not (city_dir / "city.json").is_file():
                print(f"error: {city_dir} lacks features.csv or city.json; run scripts/precache.py "
                      "--data-only first.", file=sys.stderr)
                return 2
            frames.append(pd.read_csv(city_dir / "features.csv", dtype={"h3": str}))
            cities.append(json.loads((city_dir / "city.json").read_text(encoding="utf-8")))

    is_fixture = any(city.get("created_at") == FIXTURE_CREATED_AT for city in cities)
    target_is_committed_path = args.out.resolve() == DEFAULT_REFERENCE_DIR.resolve()
    existing = args.out / "phoenix_reference.joblib"
    if existing.exists() and not args.force:
        print(f"error: {existing} already exists. Re-run with --force to replace it.", file=sys.stderr)
        return 2
    if is_fixture and target_is_committed_path and not args.force:
        print(f"error: refusing to write fixture-fitted data to the committed artifact path "
              f"{args.out}. Fit fixtures to tests/fixtures/reference instead, or pass --force.",
              file=sys.stderr)
        return 2

    artifact = fit_pooled_reference(frames, cities)
    save_reference(artifact, args.out)
    climate, source = reference_climate(artifact)
    print(f"saved reference to {args.out}")
    print(f"  cities: " + ", ".join(f"{city.get('slug')} {len(frame)}" for city, frame in zip(cities, frames)))
    print(f"  n_hexes={len(artifact['phoenix_raw'])}  modeled={len(artifact['feature_order'])}")
    print(f"  rare={artifact['rare_features']}")
    print("  climate max: " + ", ".join(f"{key} {climate[key]} ({source[key]})" for key in climate))
    print(f"  pooled self-score: {_pooled_self_red(artifact):.1f}% red (expect about 5)")
    if is_fixture:
        print("  source: FIXTURE data, not the real reference cities -- do not commit this artifact")
        if target_is_committed_path:
            print(f"  WARNING: {args.out} is the committed artifact path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
