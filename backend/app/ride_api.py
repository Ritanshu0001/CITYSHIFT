"""Rider-facing Safe Journey API (/ride/*). Separate from the admin endpoints in main.py.

A city's routing graph is built once in the background (drive network from the OSMnx
cache + crash exposure, ~20-60 s, longer if Overpass must download the roads), then
pickled to backend/route_cache/ so restarts load it in a couple of seconds.
"""
from __future__ import annotations

import logging
import pickle
import re
import threading
import time
from pathlib import Path

import osmnx as ox
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import cache, routing
from app.data.osm import drive_graph
from app.pipeline import write_crashes
from app.schemas import RADIUS_KM

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ride")

ROUTE_CACHE = Path(__file__).resolve().parents[1] / "route_cache"
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_lock = threading.Lock()
_graphs: dict[str, routing.RoutingGraph] = {}
_status: dict[str, dict] = {}  # slug -> {"status": "building" | "error", "error": str | None}


class LatLng(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    origin: LatLng
    destination: LatLng


def _city(slug: str) -> dict:
    if not _SLUG_RE.match(slug) or not (cache.city_dir(slug) / "city.json").is_file():
        raise HTTPException(status_code=404, detail="Unknown city")
    return cache.read_json(slug, "city.json")


def _crash_points(slug: str, city: dict) -> dict:
    path = cache.city_dir(slug) / "crashes.json"
    if not path.is_file():
        write_crashes(slug, city["lat"], city["lng"], city.get("country_code"))
    return cache.read_json(slug, "crashes.json")


def _pickle_path(slug: str) -> Path:
    return ROUTE_CACHE / f"{slug}.v{routing.GRAPH_VERSION}.pkl"


def _build(slug: str) -> routing.RoutingGraph:
    path = _pickle_path(slug)
    if path.is_file():
        with path.open("rb") as f:
            rg = pickle.load(f)
        if getattr(rg, "version", None) == routing.GRAPH_VERSION:
            return rg
    city = _city(slug)
    crashes = _crash_points(slug, city)
    if not crashes.get("available"):
        raise RuntimeError(crashes.get("reason") or "No crash data for this city")
    t = time.perf_counter()
    G, _ = drive_graph(city["lat"], city["lng"])
    G = ox.add_edge_speeds(G, fallback=40)
    G = ox.add_edge_travel_times(G)
    rg = routing.annotate(G, crashes["points"], slug=slug, name=city["name"], center=(city["lat"], city["lng"]))
    log.info("routing graph for %s: %d nodes, %d edges, %d crashes in %.1f s", slug,
             G.number_of_nodes(), G.number_of_edges(), len(rg.crashes), time.perf_counter() - t)
    ROUTE_CACHE.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        pickle.dump(rg, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
    return rg


def _worker(slug: str) -> None:
    try:
        rg = _build(slug)
    except Exception as exc:  # noqa: BLE001 - surfaced through /status
        log.exception("routing graph for %s failed", slug)
        with _lock:
            _status[slug] = {"status": "error", "error": str(exc)}
        return
    with _lock:
        _graphs[slug] = rg
        _status.pop(slug, None)


def _state(slug: str) -> dict:
    if slug in _graphs:
        return {"status": "ready", "error": None}
    return _status.get(slug, {"status": "idle", "error": None})


def ensure(slug: str) -> dict:
    """Start building the graph unless it's ready or already building. Returns the state."""
    with _lock:
        state = _state(slug)
        if state["status"] in ("ready", "building"):
            return state
        _status[slug] = {"status": "building", "error": None}
    threading.Thread(target=_worker, args=(slug,), name=f"route-graph-{slug}", daemon=True).start()
    return {"status": "building", "error": None}


@router.get("/cities")
def ride_cities() -> dict:
    """Cities a rider can book in: cached, with crash data (FARS is US-only)."""
    out = []
    for item in cache.list_cities():
        city = cache.read_json(item["slug"], "city.json")
        if (city.get("country_code") or "").upper() != "US":
            continue
        with _lock:
            state = _state(item["slug"])
        out.append({
            "slug": item["slug"],
            "name": city["name"],
            "center": {"lat": city["lat"], "lng": city["lng"]},
            "radius_km": city.get("radius_km", RADIUS_KM),
            "routing": state["status"],
        })
    return {"cities": sorted(out, key=lambda c: c["name"])}


@router.post("/{slug}/prepare")
def ride_prepare(slug: str) -> dict:
    _city(slug)
    return ensure(slug)


@router.get("/{slug}/status")
def ride_status(slug: str) -> dict:
    _city(slug)
    with _lock:
        return _state(slug)


@router.post("/{slug}/routes")
def ride_routes(slug: str, req: RouteRequest) -> dict:
    city = _city(slug)
    with _lock:
        rg = _graphs.get(slug)
    if rg is None:
        state = ensure(slug)
        raise HTTPException(status_code=409, detail=f"Street network is {state['status']}; try again shortly")
    radius_m = float(city.get("radius_km", RADIUS_KM)) * 1000
    try:
        return routing.plan(rg, (req.origin.lat, req.origin.lng), (req.destination.lat, req.destination.lng), radius_m)
    except routing.RouteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
