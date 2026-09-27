"""Rider-facing Safe Journey API (/ride/*). Separate from the admin endpoints in main.py.

A city's routing graph is built once in the background (drive network from the OSMnx
cache + crash exposure, ~20-60 s, longer if Overpass must download the roads), then
pickled to backend/route_cache/ so restarts load it in a couple of seconds. The hex
shift scores from the city's result.json are applied on every load, not pickled.

The committed cache/{slug}/ holds the analysis but not the road network, and both
backend/osmnx_cache/ and backend/route_cache/ are per machine. So a city analysed
elsewhere downloads its roads on its first ride here, unless scripts/prebuild_routes.py
has already built the graph.
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


def _hex_scores(slug: str) -> dict[str, float]:
    """{h3: shift_score} from the city's analysis; every city on the ride list is cached."""
    if not (cache.city_dir(slug) / "result.json").is_file():
        raise RuntimeError("This city has no area analysis yet")
    return {h["h3"]: float(h["shift_score"]) for h in cache.read_json(slug, "result.json")["hexes"]}


def _load_pickle(slug: str) -> routing.RoutingGraph | None:
    path = _pickle_path(slug)
    if not path.is_file():
        return None
    with path.open("rb") as f:
        rg = pickle.load(f)
    return rg if getattr(rg, "version", None) == routing.GRAPH_VERSION else None


def _build(slug: str) -> routing.RoutingGraph:
    hex_scores = _hex_scores(slug)
    rg = _load_pickle(slug)
    if rg is not None:
        t = time.perf_counter()
        routing.score_areas(rg, hex_scores)
        log.info("area layer for %s: %d hexes in %.1f s", slug, len(hex_scores), time.perf_counter() - t)
        return rg
    return _build_fresh(slug, hex_scores)


def _build_fresh(slug: str, hex_scores: dict[str, float]) -> routing.RoutingGraph:
    """Drive network + crash exposure + area layer, pickled to route_cache/."""
    path = _pickle_path(slug)
    city = _city(slug)
    crashes = _crash_points(slug, city)
    if not crashes.get("available"):
        raise RuntimeError("No roadway risk data is available for this city")
    # The server that answered the analysis: its response may already be in this machine's OSMnx cache.
    meta_path = cache.city_dir(slug) / "meta.json"
    prefer = (cache.read_json(slug, "meta.json").get("overpass") or {}).get("roads") if meta_path.is_file() else None
    t = time.perf_counter()
    G, _ = drive_graph(city["lat"], city["lng"], prefer=prefer)
    G = ox.add_edge_speeds(G, fallback=40)
    G = ox.add_edge_travel_times(G)
    rg = routing.annotate(G, crashes["points"], slug=slug, name=city["name"], center=(city["lat"], city["lng"]),
                          hex_scores=hex_scores)
    log.info("routing graph for %s: %d nodes, %d edges, %d crashes, %d hexes in %.1f s", slug,
             G.number_of_nodes(), G.number_of_edges(), len(rg.crashes), len(hex_scores), time.perf_counter() - t)
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


def prebuild(slug: str) -> bool:
    """Build and pickle the slug's graph unless a current pickle exists; nothing stays in memory.

    Returns True if it built one. Used by scripts/prebuild_routes.py.
    """
    if _pickle_path(slug).is_file():  # the file name carries GRAPH_VERSION
        return False
    _build_fresh(slug, _hex_scores(slug))
    return True


def ride_slugs() -> list[str]:
    """Cached cities a rider can book in: US (FARS is US-only) and analysed."""
    out = []
    for item in cache.list_cities():
        city = cache.read_json(item["slug"], "city.json")
        if (city.get("country_code") or "").upper() == "US":
            out.append(item["slug"])
    return out


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
    for slug in ride_slugs():
        city = cache.read_json(slug, "city.json")
        with _lock:
            state = _state(slug)
        out.append({
            "slug": slug,
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
