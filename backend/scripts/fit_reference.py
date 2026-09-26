"""Fit and save a Phoenix reference artifact from CSV and city JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from app.model.reference import (
    DEFAULT_REFERENCE_DIR,
    FIXTURE_CREATED_AT,
    fit_reference,
    save_reference,
)
from app.schemas import REFERENCE_SLUG


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument("--city", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing artifact in --out")
    args = parser.parse_args()

    city = json.loads(args.city.read_text(encoding="utf-8"))
    slug = str(city.get("slug", ""))
    is_fixture = city.get("created_at") == FIXTURE_CREATED_AT
    target_is_committed_path = args.out.resolve() == DEFAULT_REFERENCE_DIR.resolve()

    # Everything loads this artifact as "the Phoenix reference", so fitting it on
    # another city silently rescales every score. Refuse rather than warn.
    if slug != REFERENCE_SLUG:
        print(f"error: --city slug is {slug!r}, not {REFERENCE_SLUG!r}. The reference must be "
              "fitted on the reference city (contract 3, REFERENCE_SLUG).", file=sys.stderr)
        return 2

    existing = args.out / "phoenix_reference.joblib"
    if existing.exists() and not args.force:
        print(f"error: {existing} already exists. Re-run with --force to replace it.", file=sys.stderr)
        return 2

    if is_fixture and target_is_committed_path and not args.force:
        print(f"error: refusing to write fixture-fitted data to the committed artifact path "
              f"{args.out}. Fit fixtures to tests/fixtures/reference instead, or pass --force.",
              file=sys.stderr)
        return 2

    features = pd.read_csv(args.features)
    artifact = fit_reference(features, city)
    save_reference(artifact, args.out)
    print(f"saved reference to {args.out}")
    print(f"  n_hexes={len(artifact['phoenix_raw'])}  modeled={len(artifact['feature_order'])}")
    print(f"  rare={artifact['rare_features']}")
    if is_fixture:
        print("  source: FIXTURE data, not real Phoenix -- do not commit this artifact")
        if target_is_committed_path:
            print(f"  WARNING: {args.out} is the committed artifact path.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
