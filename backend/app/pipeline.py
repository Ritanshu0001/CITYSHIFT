"""analyze_city orchestrator (contract D3, 4.4). P1 owns this; P2's code is called, never edited."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Callable

import h3
import osmnx as ox
import pandas as pd

from app import cache
from app.cancellation import AnalysisCancelled, checkpoint
from app.data import openmeteo
from app.data.crashes import crashes_for
from app.data.driving_side import country_for, driving_side
from app.data.elevation import terrain_slopes
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
    climate: dict | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[pd.DataFrame, dict, dict]:
    """Data half: pull OSM + weather, build features, write features.csv, city.json, meta.json.

    Returns (features, city, meta). Calls progress() for roads, infrastructure, weather.
    Pass `climate` (the three *_days_per_year values from an existing city.json) to skip
    the weather download: 2020-2024 history never changes and costs ~130 Open-Meteo calls.
    """
    slug = cache.slugify(name)
    calls_before = openmeteo.run_total()
    timings: dict[str, float] = {}

    def timed(key: str, fn, *args):
        t = time.perf_counter()
        try:
            return fn(*args)
        finally:
            timings[key] = time.perf_counter() - t

    def fetch_result(future: Future):
        while True:
            checkpoint(cancel_event)
            try:
                return future.result(timeout=0.2)
            except FutureTimeout:
                continue

    step = "roads"
    t_wall = time.perf_counter()
    # The three downloads are independent: run them together, report progress in JOB_STEPS order.
    elevation_stats: dict = {}
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fetch")
    try:
        checkpoint(cancel_event)
        hex_ids = timed("grid", hexes_for, lat, lng)
        progress("roads")
        roads_f = pool.submit(timed, "roads", drive_graph, lat, lng)
        feats_f = pool.submit(timed, "infrastructure", osm_features, lat, lng)
        weather_f = None if climate else pool.submit(timed, "weather", climate_for, lat, lng, cancel_event)
        # CR-011: elevation is part of the "weather" step (JOB_STEPS unchanged).
        elevation_f = pool.submit(timed, "elevation", terrain_slopes, hex_ids, elevation_stats, cancel_event)
        G, roads_server = fetch_result(roads_f)

        step = "infrastructure"
        progress("infrastructure")
        feats, feats_server = fetch_result(feats_f)

        step = "weather"
        progress("weather")
        climate_source = "reused from city.json" if climate else "Open-Meteo"
        climate = climate or fetch_result(weather_f)
        try:
            slopes = fetch_result(elevation_f)
        except AnalysisCancelled:
            raise
        except Exception as exc:
            raise StepError("weather", RuntimeError(f"elevation: {exc}")) from exc
        timings["downloads_wall"] = time.perf_counter() - t_wall

        checkpoint(cancel_event)
        country = country_code.strip().upper() if country_code else country_for(lat, lng)
        df, osm_completeness = timed("features", build_features, hex_ids, G, feats, slopes)
    except AnalysisCancelled:
        raise
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
        "climate_source": climate_source,
        "elevation": {"points": elevation_stats.get("points"), "requests": elevation_stats.get("requests"),
                      "source": "Copernicus DEM GLO-90 via Open-Meteo"},
        "openmeteo_calls_estimate": round(openmeteo.run_total() - calls_before, 1),
        "versions": {"osmnx": ox.__version__, "h3": h3.__version__},
    }
    checkpoint(cancel_event)
    cache.write_features(slug, df)
    cache.write_json(slug, "city.json", city)
    cache.write_json(slug, "meta.json", meta)
    write_crashes(slug, lat, lng, country)
    checkpoint(cancel_event)
    return df, city, meta


def write_crashes(slug: str, lat: float, lng: float, country_code: str | None) -> dict:
    """cache/{slug}/crashes.json (CR-017). Display only, so a failure never fails the city."""
    try:
        crashes = crashes_for(slug, lat, lng, country_code)
    except Exception as exc:  # noqa: BLE001
        log.warning("crash layer failed for %s: %s", slug, exc)
        crashes = {"slug": slug, "available": False, "reason": f"crash layer failed: {exc}"}
    cache.write_json(slug, "crashes.json", crashes)
    return crashes


def analyze_city(
    name: str,
    lat: float,
    lng: float,
    country_code: str | None,
    progress: Progress = _noop,
    cancel_event: threading.Event | None = None,
) -> None:
    """Full run: data half, then P2's score_city, build_summary, build_scenarios -> result.json."""
    build_city_data(name, lat, lng, country_code, progress, cancel_event=cancel_event)
    checkpoint(cancel_event)
    score_cached(cache.slugify(name), progress, cancel_event)


def score_cached(
    slug: str, progress: Progress = _noop, cancel_event: threading.Event | None = None
) -> dict:
    """Scoring half only: cached features.csv + city.json -> result.json. No network.

    Used after a model or scenario-rule change to rebuild results without re-downloading.
    Returns the result dict that was written.
    """
    # P2 gets exactly what is on disk.
    features = cache.read_features(slug)
    city = cache.read_json(slug, "city.json")

    progress("scoring")
    try:
        checkpoint(cancel_event)
        from app.model.scoring import score_city
        from app.model.summary import build_summary

        hexes = score_city(features, city)
        summary = build_summary(features, city, hexes)
    except AnalysisCancelled:
        raise
    except Exception as exc:
        raise StepError("scoring", exc) from exc

    progress("scenarios")
    try:
        checkpoint(cancel_event)
        from app.model.scenarios import build_scenarios

        scenarios = build_scenarios(features, city, hexes, summary)
        result = CityResult.model_validate({"hexes": hexes, "summary": summary, "scenarios": scenarios})
    except AnalysisCancelled:
        raise
    except Exception as exc:
        raise StepError("scenarios", exc) from exc

    data = result.model_dump(mode="json")
    checkpoint(cancel_event)
    cache.write_json(slug, "result.json", data)
    try:
        from app.briefing import write_briefing

        write_briefing(slug)  # CR-018; deterministic, a few ms
    except Exception as exc:  # noqa: BLE001 - the briefing never fails a city
        log.warning("briefing for %s failed: %s", slug, exc)
    return data
