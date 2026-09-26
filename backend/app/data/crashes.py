"""Fatal-crash layer from NHTSA FARS (CR-017). Display only: never scored.

Reads the committed slim national extract (backend/data/fars_2020_2024_slim.csv.gz,
built by scripts/build_fars_extract.py), so it makes no network calls.
"""
from __future__ import annotations

import logging
import math
import threading
from collections import Counter
from pathlib import Path

import h3
import pandas as pd

from app.data.grid import hexes_for
from app.schemas import H3_RES, RADIUS_KM

log = logging.getLogger(__name__)

EXTRACT = Path(__file__).resolve().parents[2] / "data" / "fars_2020_2024_slim.csv.gz"
YEARS = [2020, 2021, 2022, 2023, 2024]
PRELIMINARY_YEARS = [2024]  # FARS 2024 is the initial (preliminary) release
SOURCE = "NHTSA FARS"
NOTE = "Fatal crashes only"
US_ONLY = "FARS covers US crashes only"

_df: pd.DataFrame | None = None
_lock = threading.Lock()


def _extract() -> pd.DataFrame:
    global _df
    if _df is None:
        with _lock:
            if _df is None:
                _df = pd.read_csv(EXTRACT, dtype={"st_case": "int64", "year": "int64", "month": "int64",
                                                  "hour": "Int64", "fatalities": "int64"})
    return _df


def _unavailable(slug: str, reason: str) -> dict:
    return {"slug": slug, "available": False, "reason": reason}


def crashes_for(slug: str, lat: float, lng: float, country_code: str | None) -> dict:
    """crashes.json for one city per CR-017. Non-US cities get available: false."""
    if (country_code or "").strip().upper() != "US":
        return _unavailable(slug, US_ONLY)
    if not EXTRACT.is_file():
        log.warning("FARS extract missing at %s; crash layer unavailable", EXTRACT)
        return _unavailable(slug, "crash extract not built")

    df = _extract()
    # Cheap box first, then the exact great-circle radius.
    dlat = RADIUS_KM / 110.0 * 1.05
    dlng = dlat / max(math.cos(math.radians(lat)), 0.1)
    box = df[df["lat"].between(lat - dlat, lat + dlat) & df["lng"].between(lng - dlng, lng + dlng)]
    inside = [h3.great_circle_distance((lat, lng), (a, b), unit="km") <= RADIUS_KM
              for a, b in zip(box["lat"], box["lng"])]
    rows = box[inside].sort_values(["year", "st_case"])

    points = []
    for r in rows.itertuples(index=False):
        points.append({
            "lat": round(float(r.lat), 6),
            "lng": round(float(r.lng), 6),
            "year": int(r.year),
            "month": int(r.month),
            "hour": None if pd.isna(r.hour) else int(r.hour),
            "fatalities": int(r.fatalities),
            "pedestrian": bool(r.pedestrian),
            "cyclist": bool(r.cyclist),
            "dark": bool(r.dark),
            "h3": h3.latlng_to_cell(float(r.lat), float(r.lng), H3_RES),
        })

    # pct = share of this city's hexes (its full grid, zero-crash hexes included) whose count
    # is at or below this hex's. Within this city only: counts are never compared across cities.
    counts = Counter(p["h3"] for p in points)
    population = [counts.get(cell, 0) for cell in set(hexes_for(lat, lng)) | set(counts)]
    by_hex = {
        cell: {"count": n, "pct": round(100.0 * sum(v <= n for v in population) / len(population), 1)}
        for cell, n in sorted(counts.items())
    }
    return {
        "slug": slug,
        "available": True,
        "source": SOURCE,
        "years": YEARS,
        "preliminary_years": PRELIMINARY_YEARS,
        "note": NOTE,
        "total": len(points),
        "points": points,
        "by_hex": by_hex,
    }
