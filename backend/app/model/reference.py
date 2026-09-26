"""Fit and persist the reference model.

CR-010: the reference is Waymo's established cities (REFERENCE_SLUGS), pooled with
equal weight per hex. The phoenix_* artifact keys and the phoenix_reference.joblib
file name are kept so nothing that reads them has to change; they now hold the
pooled reference.
"""

from __future__ import annotations

import json
import os
import threading
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from app.schemas import HEX_FEATURES, ISOFOREST_SEED, RARE_PRESENCE_THRESHOLD

DEFAULT_REFERENCE_DIR = Path(__file__).parent / "reference"
REFERENCE_DIR_ENV = "CITYSHIFT_REFERENCE_DIR"
FIXTURE_CREATED_AT = "fixture"  # created_at written by scripts/make_fake_features.py
CLIMATE_KEYS = ("rain_days_per_year", "heavy_rain_days_per_year", "snow_days_per_year")

_CACHE: dict | None = None
_CACHE_LOCK = threading.Lock()


def sanitize_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Return a finite, non-negative copy of modeled feature values.

    Every column in HEX_FEATURES is a count, a density or a 0-1 share, so a
    missing cell means "nothing of this kind is mapped here" and a negative one
    is impossible. Substituting 0 keeps log1p, the scaler and the IsolationForest
    on finite input, which is what stops a single blank cell from turning into a
    NaN token in result.json (invalid JSON for the frontend) or into a hex that
    scores red purely because a value was absent.

    avg_lanes is deliberately not passed through here: it is never modeled,
    contract 4.3 allows it to be empty, and a missing lane tag must not become a
    zero-lane road in the median comparison.
    """
    return raw.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)


def library_versions() -> dict[str, str]:
    """Versions that decide whether a pickled artifact loads and scores the same."""
    return {
        "scikit-learn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "joblib": joblib.__version__,
    }


def fit_reference(features: pd.DataFrame, city: dict) -> dict:
    """Fit a single-city reference (fixtures and tests). Same artifact shape as the pooled fit."""
    return fit_pooled_reference([features], [city])


def fit_pooled_reference(frames: list[pd.DataFrame], cities: list[dict]) -> dict:
    """Fit the deterministic reference on several cities pooled with equal weight per hex (CR-010).

    Rare detection, the scaler, the IsolationForest, percentiles, z, pct and
    ref_median all see the pooled hexes. The climate reference is the per-metric
    max across the cities: the car already drives in the wettest of them.
    Callers must pass the cities in a fixed order (REFERENCE_SLUGS): the pooled
    row order feeds the IsolationForest, so it decides the fitted model.
    """
    if not frames or len(frames) != len(cities):
        raise ValueError(f"need one city dict per feature table, got {len(frames)} tables and {len(cities)} cities")
    features = pd.concat(frames, ignore_index=True)
    raw = sanitize_features(features.loc[:, HEX_FEATURES].astype(float))
    if "avg_lanes" in features.columns:
        # Kept unsanitized and unmodeled: feature_comparison needs a reference
        # median for it when both cities have lane tags (contract 4.3).
        raw["avg_lanes"] = pd.to_numeric(features["avg_lanes"], errors="coerce")
    presence = (raw.loc[:, HEX_FEATURES] > 0).mean()
    rare_features = [name for name in HEX_FEATURES if presence[name] < RARE_PRESENCE_THRESHOLD]
    feature_order = [name for name in HEX_FEATURES if name not in rare_features]
    log_values = np.log1p(raw.loc[:, feature_order].to_numpy())
    scaler = StandardScaler().fit(log_values)
    scaled = scaler.transform(log_values)
    iforest = IsolationForest(random_state=ISOFOREST_SEED).fit(scaled)
    scores = -iforest.score_samples(scaled)

    return {
        "feature_order": feature_order,
        "rare_features": rare_features,
        "scaler": scaler,
        "iforest": iforest,
        "phoenix_scores_sorted": np.sort(scores),
        "phoenix_log_mean": scaler.mean_,
        # StandardScaler already substitutes 1.0 for a zero-variance column,
        # so scale_ is safe to divide by as-is.
        "phoenix_log_std": np.asarray(scaler.scale_, dtype=float),
        "phoenix_raw": raw,
        "phoenix_city": dict(cities[0]),
        "reference_slugs": [str(city.get("slug", "")) for city in cities],
        "reference_cities": [dict(city) for city in cities],
        "reference_hex_counts": [int(len(frame)) for frame in frames],
        # max() keeps the first city on ties, so the source is deterministic.
        "reference_climate": {key: max(float(city[key]) for city in cities) for key in CLIMATE_KEYS},
        "reference_climate_source": {
            key: str(max(cities, key=lambda city: float(city[key]))["name"]) for key in CLIMATE_KEYS
        },
    }


def save_reference(artifact: dict, directory: str | Path) -> None:
    """Write the fitted artifact and a readable metadata companion."""
    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output_dir / "phoenix_reference.joblib")
    raw = artifact["phoenix_raw"]
    cities = reference_cities(artifact)
    metadata = {
        "feature_order": list(artifact["feature_order"]),
        "rare_features": list(artifact["rare_features"]),
        "phoenix_city": artifact["phoenix_city"],
        "reference_slugs": [str(city.get("slug", "")) for city in cities],
        "reference_sources": [
            {"slug": str(city.get("slug", "")), "created_at": str(city.get("created_at", "")), "n_hexes": count}
            for city, count in zip(cities, artifact.get("reference_hex_counts", [len(raw)]))
        ],
        "reference_climate": reference_climate(artifact)[0],
        "reference_climate_source": reference_climate(artifact)[1],
        "phoenix_log_mean": [float(value) for value in artifact["phoenix_log_mean"]],
        "phoenix_log_std": [float(value) for value in artifact["phoenix_log_std"]],
        "phoenix_scores_sorted": [float(value) for value in artifact["phoenix_scores_sorted"]],
        "fit_timestamp": datetime.now(timezone.utc).isoformat(),
        "n_hexes": int(len(raw)),
        # Provenance: makes a fixture-fitted artifact self-identifying instead of
        # looking like a real fit (plan phase 1.3 forbids committing that one),
        # and lets load_reference flag the version drift that silently changes
        # scores across laptops (contract D4). Per-city slugs and created_at are
        # in reference_sources above.
        "fixture_fit": _is_fixture_fit(artifact),
        "library_versions": library_versions(),
    }
    (output_dir / "reference_meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def reference_cities(artifact: dict) -> list[dict]:
    """The city.json dicts the reference was fitted on (one for a pre-CR-010 artifact)."""
    return list(artifact.get("reference_cities") or [artifact.get("phoenix_city", {})])


def reference_climate(artifact: dict) -> tuple[dict, dict]:
    """(per-metric max climate, name of the city holding each max) for the reference.

    A pre-CR-010 artifact has no reference_climate; it falls back to its single
    city, which is exactly what the max over one city is.
    """
    if "reference_climate" in artifact:
        return dict(artifact["reference_climate"]), dict(artifact["reference_climate_source"])
    city = artifact.get("phoenix_city", {})
    return ({key: float(city.get(key, 0.0)) for key in CLIMATE_KEYS},
            {key: str(city.get("name", "reference")) for key in CLIMATE_KEYS})


def _is_fixture_fit(artifact: dict) -> bool:
    return any(city.get("created_at") == FIXTURE_CREATED_AT for city in reference_cities(artifact))


def _warn_on_version_drift(meta_path: Path) -> None:
    """Warn when the artifact was pickled by different library versions."""
    if not meta_path.exists():
        return
    try:
        recorded = json.loads(meta_path.read_text(encoding="utf-8")).get("library_versions") or {}
    except (json.JSONDecodeError, OSError):
        return
    current = library_versions()
    drift = {name: (was, current.get(name)) for name, was in recorded.items() if current.get(name) != was}
    if drift:
        detail = ", ".join(f"{name} {was} -> {now}" for name, (was, now) in sorted(drift.items()))
        warnings.warn(
            f"Reference artifact was fitted with different libraries ({detail}). Contract D4 "
            "requires identical scoring on every laptop; pin these versions or refit.",
            RuntimeWarning,
            stacklevel=3,
        )


def reference_dir(directory: str | Path | None = None) -> Path:
    """Resolve where the artifact lives: explicit arg, env override, then default."""
    if directory is not None:
        return Path(directory)
    override = os.environ.get(REFERENCE_DIR_ENV)
    return Path(override) if override else DEFAULT_REFERENCE_DIR


def load_reference(directory: str | Path | None = None) -> dict:
    """Load a saved reference artifact, raising a useful error when absent."""
    resolved_dir = reference_dir(directory)
    artifact_path = resolved_dir / "phoenix_reference.joblib"
    if not artifact_path.exists():
        raise FileNotFoundError(
            f"Reference artifact not found at {artifact_path}. "
            "Fit it from the cached reference cities (REFERENCE_SLUGS) with "
            "`python scripts/fit_reference.py --out app/model/reference` from backend/, "
            f"or point {REFERENCE_DIR_ENV} at a fixture-fitted reference for local development."
        )
    artifact = joblib.load(artifact_path)
    if _is_fixture_fit(artifact):
        warnings.warn(
            f"Reference artifact at {artifact_path} was fitted on the fake fixture, not on the real "
            "reference cities. Every shift_score is meaningless until it is refit with "
            "scripts/fit_reference.py.",
            RuntimeWarning,
            stacklevel=2,
        )
    _warn_on_version_drift(resolved_dir / "reference_meta.json")
    return artifact


def cached_reference() -> dict:
    """Load the artifact once per process and reuse it for every later call.

    The plan requires one lazy load cached in a module-level variable. Keeping
    the cache here rather than in scoring means summary and scenarios share the
    same artifact instance, so they can never disagree about feature_order.
    """
    global _CACHE
    if _CACHE is None:
        with _CACHE_LOCK:
            if _CACHE is None:
                _CACHE = load_reference()
    return _CACHE


def reset_reference_cache() -> None:
    """Drop the cached artifact; used after a refit in the same process."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
