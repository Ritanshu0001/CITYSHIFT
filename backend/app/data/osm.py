"""OpenStreetMap pulls via OSMnx 2.x, with one Overpass fallback server."""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable, TypeVar

import geopandas as gpd
import networkx as nx
import osmnx as ox
from osmnx import _overpass
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
# Healthy default-server runs in the cached cities' meta.json took 10-40 s including graph
# building. With no answer after this long, the fallback starts alongside; first to finish wins.
HEDGE_AFTER_S = 30

T = TypeVar("T")


class OSMError(RuntimeError):
    """Both Overpass servers failed. The message is readable in the UI."""


class _Abandoned(RuntimeError):
    """Stops a losing or timed-out attempt at its next Overpass request."""


class _Attempt:
    def __init__(self, server: str, overrides: dict) -> None:
        self.server = server
        self.overrides = overrides
        self.started = time.perf_counter()
        self.answered = threading.Event()  # an Overpass response arrived; the rest is local work
        self.abandoned = threading.Event()
        self.outcome: str | None = None


_current = threading.local()


class _PerAttemptSettings:
    """osmnx.settings as osmnx._overpass sees it: each download thread's attempt picks its
    own server, so two attempts (or roads and infrastructure) can use different servers
    at the same time. Everything else reads through to ox.settings."""

    def __getattr__(self, name: str):
        attempt = getattr(_current, "attempt", None)
        if attempt is not None and name in attempt.overrides:
            return attempt.overrides[name]
        return getattr(ox.settings, name)


_overpass.settings = _PerAttemptSettings()
_overpass_request = _overpass._overpass_request


def _tracked_overpass_request(data):
    attempt = getattr(_current, "attempt", None)
    if attempt is not None and attempt.abandoned.is_set():
        raise _Abandoned(attempt.server)
    response = _overpass_request(data)
    if attempt is not None:
        if attempt.abandoned.is_set():
            raise _Abandoned(attempt.server)
        attempt.answered.set()
    return response


# OSMnx's 429 retry calls the module global, so an abandoned attempt stops there too.
_overpass._overpass_request = _tracked_overpass_request


def _with_fallback(what: str, fn: Callable[[], T]) -> tuple[T, str]:
    """Run fn on the default Overpass server; start the fallback as well if the default fails,
    times out, or has not answered within HEDGE_AFTER_S. First success wins. Returns (result, server)."""
    finished: queue.Queue = queue.Queue()
    attempts: list[_Attempt] = []
    errors: list[str] = []

    def start(server: str, overrides: dict) -> None:
        attempt = _Attempt(server, {"overpass_url": server, **overrides})
        attempts.append(attempt)
        log.info("%s: querying %s (%d m radius, %d s limit)", what, server, DIST_M, ATTEMPT_TIMEOUT_S)

        def target() -> None:
            _current.attempt = attempt
            try:
                finished.put((attempt, True, fn()))
            except BaseException as exc:  # noqa: BLE001 - handed back to the caller's thread
                finished.put((attempt, False, exc))

        threading.Thread(target=target, name=f"overpass-{what}", daemon=True).start()

    def abandon_all() -> None:
        for attempt in attempts:
            attempt.abandoned.set()

    start(DEFAULT_OVERPASS_URL, {})
    default = attempts[0]
    hedge_at = default.started + HEDGE_AFTER_S
    while True:
        now = time.perf_counter()
        for attempt in attempts:
            if attempt.outcome is None and now - attempt.started >= ATTEMPT_TIMEOUT_S:
                attempt.outcome = "timeout"
                attempt.abandoned.set()
                errors.append(f"{attempt.server} did not answer within {ATTEMPT_TIMEOUT_S} s")
                log.warning("%s: %s", what, errors[-1])
        if len(attempts) == 1 and (default.outcome is not None
                                   or (not default.answered.is_set() and now >= hedge_at)):
            if default.outcome is None:
                log.warning("%s: no answer from %s after %d s; also trying %s",
                            what, default.server, HEDGE_AFTER_S, FALLBACK_OVERPASS_URL)
            # Servers without per-IP limits print no "slots available" line in /status, and
            # OSMnx then re-polls /status every 5 s forever. Skip that check on the fallback.
            start(FALLBACK_OVERPASS_URL, {"overpass_rate_limit": False})
            continue
        running = [a for a in attempts if a.outcome is None]
        if not running:
            abandon_all()
            raise OSMError(f"OpenStreetMap download failed on both Overpass servers: {'; '.join(errors)}")
        wake = min(a.started + ATTEMPT_TIMEOUT_S for a in running)
        if len(attempts) == 1 and not default.answered.is_set():
            wake = min(wake, hedge_at)
        try:
            attempt, ok, value = finished.get(timeout=max(0.0, wake - now))
        except queue.Empty:
            continue
        if attempt.outcome is not None:
            continue  # already given up on as timed out
        elapsed = time.perf_counter() - attempt.started
        if ok:
            attempt.outcome = "ok"
            abandon_all()
            log.info("%s answered by %s in %.1f s", what, attempt.server, elapsed)
            return value, attempt.server
        if isinstance(value, InsufficientResponseError):
            abandon_all()
            raise value
        attempt.outcome = "error"
        errors.append(f"{attempt.server}: {value}")
        log.warning("%s failed on %s after %.1f s: %s", what, attempt.server, elapsed, value)


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
