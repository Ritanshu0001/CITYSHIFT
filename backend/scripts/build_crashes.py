"""Write cache/{slug}/crashes.json for every cached city (CR-017). Offline.

    python scripts/build_crashes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cache  # noqa: E402
from app.pipeline import write_crashes  # noqa: E402


def main() -> None:
    print("| City | Crashes | Pedestrian | Cyclist | Dark | Top hex (count) |")
    print("|---|---:|---:|---:|---:|---|")
    for city_dir in sorted(cache.CACHE_ROOT.iterdir()):
        if not (city_dir / "city.json").is_file():
            continue
        city = cache.read_json(city_dir.name, "city.json")
        data = write_crashes(city["slug"], city["lat"], city["lng"], city.get("country_code"))
        if not data["available"]:
            print(f"| {city['name']} | n/a | | | | {data['reason']} |")
            continue
        pts, n = data["points"], data["total"]
        share = lambda key: f"{sum(p[key] for p in pts) / n:.0%}" if n else "-"  # noqa: E731
        top = max(data["by_hex"].items(), key=lambda kv: (kv[1]["count"], kv[0]), default=None)
        top_txt = f"{top[0]} ({top[1]['count']})" if top else "-"
        print(f"| {city['name']} | {n} | {share('pedestrian')} | {share('cyclist')} | {share('dark')} | {top_txt} |")


if __name__ == "__main__":
    main()
