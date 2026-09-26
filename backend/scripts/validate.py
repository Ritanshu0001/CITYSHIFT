"""Print validation cities as a Markdown table."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from app.model.scenarios import build_scenarios
from app.model.scoring import score_city
from app.model.summary import build_summary
from app.schemas import REFERENCE_LABEL, REFERENCE_SLUGS


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


REPO_ROOT = Path(__file__).resolve().parents[2]


def _baseline_result(ref: str, slug: str) -> dict | None:
    """The committed result.json for a slug at a git ref, or None if absent.

    Reads from git rather than re-scoring with the old artifact on purpose: a
    pre-CR-011 artifact no longer covers HEX_FEATURES, so loading it raises. The
    committed result.json is also the more honest "before" - it is what the team
    actually shipped at that point.
    """
    done = subprocess.run(["git", "show", f"{ref}:cache/{slug}/result.json"],
                          cwd=REPO_ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        return None
    return json.loads(done.stdout)


def _before_after(ref: str, cache: Path, slugs: list[str], recompute: bool) -> None:
    print()
    print()
    print(f"### Before/after vs `{ref}`")
    print()
    print("| City | Red before | Red after | Change | Cards added | Cards removed |")
    print("|---|---:|---:|---:|---|---|")
    for slug in slugs:
        before = _baseline_result(ref, slug)
        after, _ = _result(cache, slug, recompute)
        name = after["summary"]["city"]
        if before is None:
            print(f"| {name} | -- | {after['summary']['pct_red']:.1f}% | new city | -- | -- |")
            continue
        was, now = before["summary"]["pct_red"], after["summary"]["pct_red"]
        old_ids = {card["id"] for card in before.get("scenarios", [])}
        new_ids = {card["id"] for card in after.get("scenarios", [])}
        added = ", ".join(f"+{i}" for i in sorted(new_ids - old_ids)) or "--"
        removed = ", ".join(f"-{i}" for i in sorted(old_ids - new_ids)) or "--"
        delta = now - was
        print(f"| {name} | {was:.1f}% | {now:.1f}% | {delta:+.1f} | {added} | {removed} |")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("slugs", nargs="+", help="cache slugs to validate")
    parser.add_argument("--cache", type=Path, default=Path(__file__).resolve().parents[2] / "cache")
    parser.add_argument("--recompute", action="store_true",
                        help="ignore any cached result.json and score from features.csv")
    parser.add_argument("--baseline", metavar="GIT_REF",
                        help="also print a before/after table against the committed "
                             "result.json at this git ref, e.g. v1-phoenix-reference")
    args = parser.parse_args()

    print("| City | Hexes | Red | Top median shifts | Novel | Scenarios | Top card |")
    print("|---|---:|---:|---|---|---:|---|")
    sources = []
    for slug in args.slugs:
        result, source = _result(args.cache, slug, args.recompute)
        sources.append((slug, source))
        print(_row(result["summary"], result.get("scenarios", [])))

    # The reference self-score is the answer to "does the score mean anything",
    # so it is always reported. CR-010: it is pooled over the reference cities,
    # which together land at about 5% red by construction.
    red = total = 0
    per_city = []
    for slug in REFERENCE_SLUGS:
        if not ((args.cache / slug / "features.csv").exists() or (args.cache / slug / "result.json").exists()):
            print(f"\nReference self-score: {slug} is not in {args.cache}; run it through the pipeline first.")
            break
        result, source = _result(args.cache, slug, args.recompute)
        if slug not in args.slugs:
            sources.append((slug, source))
        n_red = sum(item["band"] == "red" for item in result["hexes"])
        red, total = red + n_red, total + len(result["hexes"])
        per_city.append(f"{result['summary']['city']} {result['summary']['pct_red']:.1f}%")
    else:
        print(f"\nReference self-score ({REFERENCE_LABEL}, pooled): {red / total * 100:.1f}% red over "
              f"{total} hexes (contract 4.6 expects about 5).")
        print("Per reference city: " + ", ".join(per_city))

    # Provenance goes to stderr so stdout stays a paste-ready Markdown table.
    if args.baseline:
        _before_after(args.baseline, args.cache, args.slugs, args.recompute)

    for slug, source in sources:
        print(f"{slug}: {source}", file=sys.stderr)


if __name__ == "__main__":
    main()
