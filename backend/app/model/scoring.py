"""Score city feature rows against the saved reference (pooled established cities, CR-010)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas import HEX_FEATURES, TOP_FEATURES_N, band_for
from .reference import cached_reference, sanitize_features

# Reference-side statistics derived from the artifact. They do not change while the
# artifact does not, so they are computed once instead of once per hex per
# feature, and re-derived only if a refit swaps the cached artifact out.
_STATS: dict | None = None


def _reference_stats(artifact: dict) -> dict:
    global _STATS
    if _STATS is None or _STATS["artifact"] is not artifact:
        reference = artifact["phoenix_raw"]
        modeled = artifact["feature_order"]
        _STATS = {
            "artifact": artifact,
            "medians": [round(float(reference[name].median()), 2) for name in modeled],
            # Sorted reference columns turn each percentile into a binary search.
            "sorted_columns": [np.sort(reference[name].to_numpy()) for name in modeled],
            "n_reference": len(reference),
        }
    return _STATS


def _z_from_log(log_modeled: np.ndarray, artifact: dict) -> np.ndarray:
    return (log_modeled - artifact["phoenix_log_mean"]) / artifact["phoenix_log_std"]


def z_matrix(features: pd.DataFrame) -> pd.DataFrame:
    """Return per-feature log-space z values aligned with ``features`` rows."""
    artifact = cached_reference()
    modeled = artifact["feature_order"]
    raw = sanitize_features(features.loc[:, modeled].astype(float))
    z_values = _z_from_log(np.log1p(raw.to_numpy()), artifact)
    return pd.DataFrame(z_values, index=features.index, columns=modeled)


def score_city(features: pd.DataFrame, city: dict) -> list[dict]:
    """Return contract-shaped hex scores and explanations."""
    artifact = cached_reference()
    modeled = artifact["feature_order"]
    rare = artifact["rare_features"]
    raw = sanitize_features(features.loc[:, HEX_FEATURES].astype(float))
    if raw.empty:
        return []

    values = raw.loc[:, modeled].to_numpy()
    log_modeled = np.log1p(values)  # one pass, shared by the z values and the scaler
    z_values = _z_from_log(log_modeled, artifact)
    anomaly_scores = -artifact["iforest"].score_samples(artifact["scaler"].transform(log_modeled))
    phoenix_scores = artifact["phoenix_scores_sorted"]
    percentiles = np.searchsorted(phoenix_scores, anomaly_scores, side="left") / len(phoenix_scores) * 100

    stats = _reference_stats(artifact)
    # pct: share of reference raw values at or below this one, per contract 4.2.
    percentile_of_raw = np.column_stack([
        np.searchsorted(column, values[:, index], side="right") / stats["n_reference"] * 100
        for index, column in enumerate(stats["sorted_columns"])
    ])
    # Ranked on exact |z| before rounding, so two features that round to the same
    # displayed z keep their true order; the stable sort leaves real ties in
    # HEX_FEATURES order.
    ranking = np.argsort(-np.abs(z_values), axis=1, kind="stable")[:, :TOP_FEATURES_N]
    rare_values = raw.loc[:, rare].to_numpy() if rare else np.empty((len(raw), 0))
    h3_ids = features["h3"].astype(str).to_numpy()

    hexes = []
    for row in range(len(raw)):
        score = round(float(percentiles[row]), 1)
        hexes.append({
            "h3": str(h3_ids[row]),
            "shift_score": score,
            "band": band_for(score),
            "top_features": [
                {
                    "name": modeled[column],
                    "value": round(float(values[row, column]), 2),
                    "ref_median": stats["medians"][column],
                    "z": round(float(z_values[row, column]), 2),
                    "pct": round(float(percentile_of_raw[row, column]), 1),
                }
                for column in ranking[row]
            ],
            "novel": [name for index, name in enumerate(rare) if rare_values[row, index] > 0],
        })
    return hexes
