"""OpenStreetMap pulls via OSMnx 2.x, with one Overpass fallback server."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, TypeVar

import geopandas as gpd
import networkx as nx
import osmnx as ox
from osmnx._errors import InsufficientResponseError

from app.schemas import RADIUS_KM

if not ox.__version__.startswith("2."):
    raise ImportError(f"CityShift needs osmnx 2.x, found {ox.__version__} (CONTRACTS.md D11)")

log = logging.getLogger(__name__)

DIST_M = RADIUS_KM * 1000

# Combined features query, SOURCE-PLAN.md section 3.
TAGS = {
    "highway": ["traffic_signals", "crossing", "bus_stop", "cycleway"],
    "public_transport": ["platform", "station"],
    "railway": ["station", "tram_stop"],
    "amenity": ["school", "bar", "pub", "nightclub"],
    "leisure": ["stadium"],
    "tourism": ["hotel", "attraction"],
}

DEFAULT_OVERPASS_URL = ox.settings.overpass_url
# Checked 2026-09-26: kumi.systems and private.coffee were hanging; maps.mail.ru answered in 4 s.
FALLBACK_OVERPASS_URL = "https://maps.mail.ru/osm/tools/overpass/api"

# Before every request OSMnx pins the Overpass hostname to one IP from gethostbyname.
# overpass-api.de round-robins two machines; on 2026-09-26 one refused connections and
# every pinned request to it failed. Unpinned, urllib3 tries each A record in turn.
ox._http._config_dns = lambda _url: None

ox.settings.use_cache = True
ox.settings.cache_folder = str(Path(__file__).resolve().parents[2] / "osmnx_cache")
ox.settings.requests_timeout = 180
ox.settings.log_console = True

# OSMnx retries 429/504 forever (55 s apart) and waits 60 s when a server's /status is
# unreachable, so an overloaded server never raises. Each attempt gets a wall-clock limit.
# Uncached London takes ~90 s on a healthy server.
ATTEMPT_TIMEOUT_S = 150

# ox.settings is process-global; only one thread may swap the Overpass URL at a time.
_url_lock = threading.Lock()

T = TypeVar("T")


class OSMError(RuntimeError):
    """Both Overpass servers failed. The message is readable in the UI."""


def _call_with_timeout(fn: Callable[[], T], server: str) -> T:
    """Run fn on a daemon thread. On timeout the thread is abandoned (it can't be killed)."""
    box: dict = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = exc

    t = threading.Thread(target=target, name="overpass", daemon=True)
    t.start()
    t.join(ATTEMPT_TIMEOUT_S)
    if t.is_alive():
        raise TimeoutError(f"{server} did not answer within {ATTEMPT_TIMEOUT_S} s")
    if "error" in box:
        raise box["error"]
    return box["result"]


def _with_fallback(what: str, fn: Callable[[], T]) -> tuple[T, str]:
    """Run fn on the default Overpass server, then once on the fallback. Returns (result, server)."""
    server = ox.settings.overpass_url
    log.info("%s: querying %s (%d m radius, %d s limit)", what, server, DIST_M, ATTEMPT_TIMEOUT_S)
    t = time.perf_counter()
    try:
        result = _call_with_timeout(fn, server)
        log.info("%s answered by %s in %.1f s", what, server, time.perf_counter() - t)
        return result, server
    except InsufficientResponseError:
        raise
    except Exception as first:  # noqa: BLE001
        log.warning("%s failed on %s after %.1f s: %s; retrying on %s",
                    what, server, time.perf_counter() - t, first, FALLBACK_OVERPASS_URL)
    with _url_lock:
        ox.settings.overpass_url = FALLBACK_OVERPASS_URL
        # Servers without per-IP limits print no "slots available" line in /status, and
        # OSMnx then re-polls /status every 5 s forever. Skip that check on the fallback.
        ox.settings.overpass_rate_limit = False
        t = time.perf_counter()
        try:
            result = _call_with_timeout(fn, FALLBACK_OVERPASS_URL)
            log.info("%s answered by %s in %.1f s", what, FALLBACK_OVERPASS_URL, time.perf_counter() - t)
            return result, FALLBACK_OVERPASS_URL
        except InsufficientResponseError:
            raise
        except Exception as second:  # noqa: BLE001
            raise OSMError(f"OpenStreetMap download failed on both Overpass servers: {second}") from second
        finally:
            ox.settings.overpass_url = DEFAULT_OVERPASS_URL
            ox.settings.overpass_rate_limit = True


def drive_graph(lat: float, lng: float) -> tuple[nx.MultiDiGraph, str]:
    """Drive network within DIST_M of the center. Returns (graph, overpass server used)."""
    return _with_fallback(
        "roads",
        lambda: ox.graph_from_point((lat, lng), dist=DIST_M, network_type="drive"),
    )


def osm_features(lat: float, lng: float) -> tuple[gpd.GeoDataFrame, str]:
    """All TAGS features within DIST_M. An area with none of them returns an empty frame."""
    try:
        return _with_fallback("infrastructure", lambda: ox.features_from_point((lat, lng), TAGS, dist=DIST_M))
    except InsufficientResponseError:
        log.warning("no OSM features matched TAGS near (%s, %s)", lat, lng)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), ox.settings.overpass_url
