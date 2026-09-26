"""Paths and read/write helpers for cache/{slug}/ (contract 4.3, D6).

cache/ is written by P1's code only. P2's scripts may use these helpers.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

from app.schemas import FEATURE_CSV_COLUMNS

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = REPO_ROOT / "cache"


def slugify(name: str) -> str:
    """Contract section 3: lowercase, runs of non-alphanumerics -> one hyphen, strip hyphens.

    Accents are folded first ("São Paulo" -> "sao-paulo") so slugs stay ASCII in URLs.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "city"


def city_dir(slug: str) -> Path:
    return CACHE_ROOT / slug


def write_json(slug: str, filename: str, data: dict) -> Path:
    path = city_dir(slug) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def read_json(slug: str, filename: str) -> dict:
    return json.loads((city_dir(slug) / filename).read_text(encoding="utf-8"))


def write_features(slug: str, df: pd.DataFrame) -> Path:
    path = city_dir(slug) / "features.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df[FEATURE_CSV_COLUMNS]
    tmp = path.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False, lineterminator="\n")
    tmp.replace(path)
    return path


def read_features(slug: str) -> pd.DataFrame:
    return pd.read_csv(city_dir(slug) / "features.csv", dtype={"h3": str})


def has_result(slug: str) -> bool:
    return (city_dir(slug) / "result.json").is_file()


def list_cities() -> list[dict]:
    """Summary rows for GET /cities, from every cache/*/result.json, sorted by name."""
    rows = []
    for result_path in CACHE_ROOT.glob("*/result.json"):
        slug = result_path.parent.name
        try:
            summary = json.loads(result_path.read_text(encoding="utf-8"))["summary"]
            city_path = result_path.parent / "city.json"
            city = json.loads(city_path.read_text(encoding="utf-8")) if city_path.is_file() else {}
            rows.append({
                "slug": slug,
                "name": summary["city"],
                "center": summary["center"],
                "n_hexes": summary["n_hexes"],
                "pct_red": summary["pct_red"],
                "created_at": city.get("created_at", ""),
            })
        except (OSError, ValueError, KeyError):
            continue  # a half-written or malformed city never breaks the list
    return sorted(rows, key=lambda r: r["name"].lower())
