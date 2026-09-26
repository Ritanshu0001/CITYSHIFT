"""Build the city summary from scored hexes and reference statistics."""

from __future__ import annotations

import pandas as pd

from app.schemas import HEX_FEATURES, UNSCORED_FEATURES
from .reference import CLIMATE_KEYS, cached_reference, reference_climate, sanitize_features

def _median(values: pd.Series) -> float:
    """Median as a finite rounded float; 0.0 when there is nothing to take it of."""
    value = values.median()
    return 0.0 if pd.isna(value) else round(float(value), 2)


def _has_values(frame: pd.DataFrame, name: str) -> bool:
    """True when this frame carries at least one numeric value for a column."""
    if name not in frame.columns:
        return False
    return bool(pd.to_numeric(frame[name], errors="coerce").notna().any())


def _has_lane_data(frame: pd.DataFrame) -> bool:
    """True when this city carries at least one numeric avg_lanes value."""
    return _has_values(frame, "avg_lanes")


def _driving_side(city: dict) -> str:
    """Coerce P1's value to the contract's two allowed literals, defaulting right."""
    return "left" if str(city.get("driving_side", "right")).strip().lower() == "left" else "right"


def build_summary(features: pd.DataFrame, city: dict, hexes: list[dict]) -> dict:
    artifact = cached_reference()
    # CR-010: per-metric max across the reference cities, not one city's values.
    climate_reference, _ = reference_climate(artifact)
    target = sanitize_features(features.loc[:, HEX_FEATURES].astype(float))
    reference = artifact["phoenix_raw"]  # pooled reference hexes
    pct_red = sum(item["band"] == "red" for item in hexes) / len(hexes) * 100 if hexes else 0.0
    driving_side = _driving_side(city)
    novel_city = []
    if float(city.get("snow_days_per_year", 0)) >= 2 and climate_reference["snow_days_per_year"] < 1:
        novel_city.append("snow")
    if driving_side == "left":
        novel_city.append("left_hand_traffic")

    feature_comparison = [
        {"name": name, "target": _median(target[name]), "reference": _median(reference[name])}
        for name in HEX_FEATURES
    ]
    # CR-014: terrain_slope_pct is collected but not scored. It still earns a
    # comparison row so the number stays visible, on the same terms as avg_lanes:
    # only when both sides actually have values, never faked from a missing
    # column. Placed before avg_lanes to match FEATURE_CSV_COLUMNS order.
    for name in UNSCORED_FEATURES:
        if _has_values(features, name) and _has_values(reference, name):
            feature_comparison.append({
                "name": name,
                "target": _median(pd.to_numeric(features[name], errors="coerce")),
                "reference": _median(pd.to_numeric(reference[name], errors="coerce")),
            })

    # Contract 4.3: avg_lanes is never modeled and appears here only when both
    # cities have lane tags. A reference fitted before avg_lanes was retained
    # simply has no column, so the row is omitted rather than faked.
    if _has_lane_data(features) and _has_lane_data(reference):
        feature_comparison.append({
            "name": "avg_lanes",
            "target": _median(pd.to_numeric(features["avg_lanes"], errors="coerce")),
            "reference": _median(pd.to_numeric(reference["avg_lanes"], errors="coerce")),
        })

    return {
        "city": str(city["name"]),
        "slug": str(city["slug"]),
        "center": {"lat": float(city["lat"]), "lng": float(city["lng"])},
        "radius_km": float(city["radius_km"]),
        "n_hexes": int(len(features)),
        "pct_red": round(float(pct_red), 1),
        "climate": {
            "target": {key: float(city[key]) for key in CLIMATE_KEYS},
            "reference": {key: float(climate_reference[key]) for key in CLIMATE_KEYS},
        },
        "driving_side": driving_side,
        "feature_comparison": feature_comparison,
        "osm_completeness": float(city.get("osm_completeness", 0.0)),
        "novel_city": novel_city,
    }
