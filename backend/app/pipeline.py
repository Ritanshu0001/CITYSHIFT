"""analyze_city orchestrator (contract D3, 4.4). P1 owns this; P2's code is called, never edited."""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from typing import Callable

import h3
import osmnx as ox
import pandas as pd

from app import cache, joblog
from app.cancellation import AnalysisCancelled, checkpoint
from app.data import openmeteo
from app.data.crashes import crashes_for
from app.data.driving_side import country_for, driving_side
from app.data.features import build_features
from app.data.grid import hexes_for
from app.data.osm import drive_graph, osm_features
from app.data.weather import climate_for
from app.schemas import CITY_JSON_KEYS, H3_RES, MIN_ROAD_KM, RADIUS_KM, CityResult

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


def _climate_text(climate: dict) -> str:
    return (f"rain {climate['rain_days_per_year']}, heavy rain {climate['heavy_rain_days_per_year']}, "
            f"snow {climate['snow_days_per_year']} days/yr")


def _feature_totals(df: pd.DataFrame) -> str:
    """City totals over the kept hexes, for the log. Counts come back from density * hex area."""
    def total(col: str) -> float:
        return float((df[col] * df["area_km2"]).sum())

    road_km = float(df["road_km"].sum())
    arterial_km = float((df["arterial_share"] * df["road_km"]).sum())
    motorway_km = float((df["motorway_share"] * df["road_km"]).sum())
    return (
        f"{road_km:,.0f} road km ({arterial_km:,.0f} arterial, {motorway_km:,.0f} motorway), "
        f"{total('intersection_density'):,.0f} intersections, {total('signal_density'):,.0f} signals, "
        f"{total('crosswalk_density'):,.0f} crossings, {total('transit_stop_density'):,.0f} transit stops, "
        f"{total('bike_lane_density'):,.0f} cycleway km, {total('school_density'):,.0f} schools, "
        f"{total('nightlife_density'):,.0f} nightlife, {total('tourism_density'):,.0f} tourism, "
        f"{int(df['bridge_count'].sum())} bridges ({int(df['movable_bridge_count'].sum())} movable), "
        f"{int(df['tunnel_count'].sum())} tunnels, {int(df['roundabout_count'].sum())} roundabouts, "
        f"{int(df['stadium_count'].sum())} stadiums"
    )


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
    t_start = time.perf_counter()
    log.info("[%s] loading %s at (%.5f, %.5f), %s km radius, country %s",
             slug, name, lat, lng, RADIUS_KM, country_code or "to be reverse geocoded")

    def timed(key: str, fn, *args, describe: Callable | None = None):
        """Run fn, record its time in meta.json's timings_s, log how long it took and what it returned."""
        t = time.perf_counter()
        try:
            result = fn(*args)
        except AnalysisCancelled:
            raise
        except Exception as exc:
            log.warning("[%s] %s failed after %.1f s: %s", slug, key, time.perf_counter() - t, exc)
            raise
        finally:
            timings[key] = time.perf_counter() - t
        log.info("[%s] %s done in %.1f s%s", slug, key, timings[key], f": {describe(result)}" if describe else "")
        return result

    def fetch_result(future: Future):
        while True:
            checkpoint(cancel_event)
            try:
                return future.result(timeout=0.2)
            except FutureTimeout:
                continue

    step = "roads"
    t_wall = time.perf_counter()
    # Weather is independent and can run beside OSM. Keep the two Overpass queries
    # sequential: public servers reject concurrent requests from one client with 429.
    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="fetch")
    try:
        checkpoint(cancel_event)
        hex_ids = timed("grid", hexes_for, lat, lng,
                        describe=lambda ids: f"{len(ids)} res-{H3_RES} hexes within {RADIUS_KM} km")
        progress("roads")
        if climate:
            log.info("[%s] weather: reusing climate from city.json (%s)", slug, _climate_text(climate))
        log.info("[%s] downloading roads%s; infrastructure follows on the same Overpass server",
                 slug, "" if climate else " and weather in parallel")
        roads_f = pool.submit(joblog.in_context(timed), "roads", drive_graph, lat, lng, describe=lambda r: (
            f"{r[0].number_of_nodes():,} nodes, {r[0].number_of_edges():,} edges from {r[1]}"))
        weather_f = None if climate else pool.submit(joblog.in_context(timed), "weather", climate_for, lat, lng,
                                                     cancel_event, describe=_climate_text)
        G, roads_server = fetch_result(roads_f)

        step = "infrastructure"
        progress("infrastructure")
        feats_f = pool.submit(joblog.in_context(timed), "infrastructure", osm_features, lat, lng, roads_server,
                              describe=lambda r: f"{len(r[0]):,} tagged OSM features from {r[1]}")
        feats, feats_server = fetch_result(feats_f)

        step = "weather"
        progress("weather")
        climate_source = "reused from city.json" if climate else "Open-Meteo"
        climate = climate or fetch_result(weather_f)
        timings["downloads_wall"] = time.perf_counter() - t_wall
        log.info("[%s] all downloads finished in %.1f s wall", slug, timings["downloads_wall"])

        checkpoint(cancel_event)
        country = country_code.strip().upper() if country_code else country_for(lat, lng)
        log.info("[%s] country %s (%s), drives on the %s", slug, country or "unknown",
                 "from request" if country_code else "reverse geocoded", driving_side(country))
        df, osm_completeness = timed("features", build_features, hex_ids, G, feats, describe=lambda r: (
            f"kept {len(r[0])} of {len(hex_ids)} hexes with >= {MIN_ROAD_KM} road km, "
            f"osm_completeness {r[1]}"))
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
    log.info("[%s] feature totals: %s", slug, _feature_totals(df))

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
        "openmeteo_calls_estimate": round(openmeteo.run_total() - calls_before, 1),
        "versions": {"osmnx": ox.__version__, "h3": h3.__version__},
    }
    checkpoint(cancel_event)
    cache.write_features(slug, df)
    cache.write_json(slug, "city.json", city)
    cache.write_json(slug, "meta.json", meta)
    log.info("[%s] wrote features.csv, city.json, meta.json to %s", slug, cache.city_dir(slug))
    write_crashes(slug, lat, lng, country)
    checkpoint(cancel_event)
    log.info("[%s] city data ready in %.1f s (~%.0f Open-Meteo calls over the network)",
             slug, time.perf_counter() - t_start, meta["openmeteo_calls_estimate"])
    return df, city, meta


def write_crashes(slug: str, lat: float, lng: float, country_code: str | None) -> dict:
    """cache/{slug}/crashes.json (CR-017). Display only, so a failure never fails the city."""
    t = time.perf_counter()
    try:
        crashes = crashes_for(slug, lat, lng, country_code)
    except Exception as exc:  # noqa: BLE001
        log.warning("crash layer failed for %s: %s", slug, exc)
        crashes = {"slug": slug, "available": False, "reason": f"crash layer failed: {exc}"}
    else:
        if crashes["available"]:
            log.info("[%s] crashes: %d fatal crashes in %d hexes from %s (%.1f s)", slug, crashes["total"],
                     len(crashes["by_hex"]), crashes["source"], time.perf_counter() - t)
        else:
            log.info("[%s] crashes: not available (%s)", slug, crashes["reason"])
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
    log.info("[%s] scoring %d hexes against the reference cities", slug, len(features))
    t = time.perf_counter()
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
    bands = Counter(h["band"] for h in hexes)
    log.info("[%s] scoring done in %.1f s: %d red, %d yellow, %d green (%.1f%% red)", slug,
             time.perf_counter() - t, bands["red"], bands["yellow"], bands["green"], summary["pct_red"])

    progress("scenarios")
    t = time.perf_counter()
    try:
        checkpoint(cancel_event)
        from app.model.scenarios import build_scenarios

        scenarios = build_scenarios(features, city, hexes, summary)
        result = CityResult.model_validate({"hexes": hexes, "summary": summary, "scenarios": scenarios})
    except AnalysisCancelled:
        raise
    except Exception as exc:
        raise StepError("scenarios", exc) from exc
    log.info("[%s] scenarios done in %.1f s: %d cards (%s)", slug, time.perf_counter() - t, len(scenarios),
             ", ".join(s["id"] for s in scenarios) or "none")

    data = result.model_dump(mode="json")
    checkpoint(cancel_event)
    cache.write_json(slug, "result.json", data)
    log.info("[%s] wrote result.json", slug)
    try:
        from app.briefing import write_briefing

        write_briefing(slug)  # CR-018; deterministic, a few ms
        log.info("[%s] wrote briefing.json and briefing.md", slug)
    except Exception as exc:  # noqa: BLE001 - the briefing never fails a city
        log.warning("briefing for %s failed: %s", slug, exc)
    return data
