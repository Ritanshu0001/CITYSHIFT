"""Print validation cities as a Markdown table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from app.model.scenarios import build_scenarios
from app.model.scoring import score_city
from app.model.summary import build_summary
from app.schemas import REFERENCE_SLUG


def _result(cache: Path, slug: str, recompute: bool) -> tuple[dict, str]:
    """Return the city result and where it came from.

    A cached result.json predates any model change made since it was written, so
    the source is always reported and --recompute forces a fresh scoring pass.
    """
    city_dir = cache / slug
    result_path = city_dir / "result.json"
    if result_path.exists() and not recompute:
        return json.loads(result_path.read_text(encoding="utf-8")), f"cached {result_path}"
    features = pd.read_csv(city_dir / "features.csv")
    city = json.loads((city_dir / "city.json").read_text(encoding="utf-8"))
    hexes = score_city(features, city)
    summary = build_summary(features, city, hexes)
    scenarios = build_scenarios(features, city, hexes, summary)
    return {"hexes": hexes, "summary": summary, "scenarios": scenarios}, f"recomputed from {city_dir}"


def _ratio(row: dict) -> float:
    """Target-to-Phoenix median ratio, infinite when Phoenix has none of it.

    A feature Phoenix's median is zero for is the largest shift there is, so it
    sorts first rather than collapsing to 0 and dropping out of the top three.
    """
    if row["reference"]:
        return row["target"] / row["reference"]
    return float("inf") if row["target"] else 0.0


def _shift_text(ratio: float, name: str) -> str:
    return f"{name} new vs 0" if ratio == float("inf") else f"{name} {ratio:.1f}x"


def _row(summary: dict, cards: list[dict]) -> str:
    ratios = sorted(((_ratio(row), row["name"]) for row in summary["feature_comparison"]), reverse=True)[:3]
    shifts = ", ".join(_shift_text(ratio, name) for ratio, name in ratios)
    title = cards[0]["title"] if cards else "None"
    novel = ", ".join(summary["novel_city"]) or "None"
    return (f"| {summary['city']} | {summary['n_hexes']} | {summary['pct_red']:.1f}% | {shifts} "
            f"| {novel} | {len(cards)} | {title} |")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("slugs", nargs="+", help="cache slugs to validate")
    parser.add_argument("--cache", type=Path, default=Path(__file__).resolve().parents[2] / "cache")
    parser.add_argument("--recompute", action="store_true",
                        help="ignore any cached result.json and score from features.csv")
    parser.add_argument("--reference-slug", default=REFERENCE_SLUG,
                        help="slug of the reference city whose self-score is reported")
    args = parser.parse_args()

    print("| City | Hexes | Red | Top median shifts | Novel | Scenarios | Top card |")
    print("|---|---:|---:|---|---|---:|---|")
    sources = []
    for slug in args.slugs:
        result, source = _result(args.cache, slug, args.recompute)
        sources.append((slug, source))
        print(_row(result["summary"], result.get("scenarios", [])))

    # The reference self-score is the answer to "does the score mean anything",
    # so it is always reported even when it is not one of the requested slugs.
    reference = args.reference_slug
    if reference in args.slugs:
        print(f"\n{reference} is in the table above; contract 4.6 expects about 5% red.")
    elif (args.cache / reference / "features.csv").exists() or (args.cache / reference / "result.json").exists():
        result, source = _result(args.cache, reference, args.recompute)
        sources.append((reference, source))
        summary = result["summary"]
        print(f"\nReference self-score: {summary['city']} {summary['pct_red']:.1f}% red "
              f"over {summary['n_hexes']} hexes (contract 4.6 expects about 5).")
    else:
        print(f"\nReference self-score: {reference} is not in {args.cache}; "
              "run it through the pipeline to get the number.")

    # Provenance goes to stderr so stdout stays a paste-ready Markdown table.
    for slug, source in sources:
        print(f"{slug}: {source}", file=sys.stderr)


if __name__ == "__main__":
    main()
