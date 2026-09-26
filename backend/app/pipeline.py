"""analyze_city orchestrator (contract D3, 4.4). P1 owns this; P2's code is called, never edited."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

import h3
import osmnx as ox
import pandas as pd

from app import cache
from app.data.driving_side import country_for, driving_side
from app.data.features import build_features
from app.data.grid import hexes_for
from app.data.osm import drive_graph, osm_features
from app.data.weather import climate_for
from app.schemas import CITY_JSON_KEYS, RADIUS_KM, CityResult

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


def _noop(_step: str) -> None:
    pass


class StepError(RuntimeError):
    """An exception tagged with the JOB_STEPS entry it happened in, e.g. 'scoring failed: ...'."""

    def __init__(self, step: str, exc: BaseException):
        self.step = step
        super().__init__(f"{step} failed: {exc}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_city_data(
    name: str,
    lat: float,
    lng: float,
    country_code: str | None = None,
    progress: Progress = _noop,
) -> tuple[pd.DataFrame, dict, dict]:
    """Data half: pull OSM + weather, build features, write features.csv, city.json, meta.json.

    Returns (features, city, meta). Calls progress() for roads, infrastructure, weather.
    """
    slug = cache.slugify(name)
    timings: dict[str, float] = {}

    def timed(key: str, fn, *args):
        t = time.perf_counter()
        try:
            return fn(*args)
        finally:
            timings[key] = time.perf_counter() - t

    step = "roads"
    t_wall = time.perf_counter()
    # The three downloads are independent: run them together, report progress in JOB_STEPS order.
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="fetch")
    try:
        hex_ids = timed("grid", hexes_for, lat, lng)
        progress("roads")
        roads_f = pool.submit(timed, "roads", drive_graph, lat, lng)
        feats_f = pool.submit(timed, "infrastructure", osm_features, lat, lng)
        weather_f = pool.submit(timed, "weather", climate_for, lat, lng)
        G, roads_server = roads_f.result()

        step = "infrastructure"
        progress("infrastructure")
        feats, feats_server = feats_f.result()

        step = "weather"
        progress("weather")
        climate = weather_f.result()
        timings["downloads_wall"] = time.perf_counter() - t_wall

        country = country_code.strip().upper() if country_code else country_for(lat, lng)
        df, osm_completeness = timed("features", build_features, hex_ids, G, feats)
    except StepError:
        raise
    except Exception as exc:
        raise StepError(step, exc) from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if df.empty:
        raise StepError(step, ValueError(f"no hex within {RADIUS_KM} km has enough drivable road"))

    created_at = _utc_now()
    city = {
        "name": name,
        "slug": slug,
        "lat": lat,
        "lng": lng,
        "radius_km": RADIUS_KM,
        "country_code": country,
        "driving_side": driving_side(country),
        **climate,
        "osm_completeness": osm_completeness,
        "n_hexes_total": len(hex_ids),
        "n_hexes_kept": len(df),
        "created_at": created_at,
    }
    city = {k: city[k] for k in CITY_JSON_KEYS}
    meta = {
        "slug": slug,
        "created_at": created_at,
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
        "overpass": {"roads": roads_server, "infrastructure": feats_server},
        "n_graph_nodes": G.number_of_nodes(),
        "n_graph_edges": G.number_of_edges(),
        "n_osm_features": len(feats),
        "versions": {"osmnx": ox.__version__, "h3": h3.__version__},
    }
    cache.write_features(slug, df)
    cache.write_json(slug, "city.json", city)
    cache.write_json(slug, "meta.json", meta)
    return df, city, meta


def analyze_city(
    name: str,
    lat: float,
    lng: float,
    country_code: str | None,
    progress: Progress = _noop,
) -> None:
    """Full run: data half, then P2's score_city, build_summary, build_scenarios -> result.json."""
    slug = cache.slugify(name)
    build_city_data(name, lat, lng, country_code, progress)

    # P2 gets exactly what is on disk.
    features = cache.read_features(slug)
    city = cache.read_json(slug, "city.json")

    progress("scoring")
    try:
        from app.model.scoring import score_city
        from app.model.summary import build_summary

        hexes = score_city(features, city)
        summary = build_summary(features, city, hexes)
    except Exception as exc:
        raise StepError("scoring", exc) from exc

    progress("scenarios")
    try:
        from app.model.scenarios import build_scenarios

        scenarios = build_scenarios(features, city, hexes, summary)
        result = CityResult.model_validate({"hexes": hexes, "summary": summary, "scenarios": scenarios})
    except Exception as exc:
        raise StepError("scenarios", exc) from exc

    cache.write_json(slug, "result.json", result.model_dump(mode="json"))
