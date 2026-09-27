"""OpenStreetMap pulls via OSMnx 2.x, with bounded Overpass failover."""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import urlsplit

import geopandas as gpd
import networkx as nx
import osmnx as ox
import requests
from osmnx import _overpass
from osmnx import utils as ox_utils
from osmnx._errors import InsufficientResponseError

from app import joblog
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
FALLBACK_OVERPASS_URL = "https://gall.openstreetmap.de/api"
OVERPASS_URLS = (DEFAULT_OVERPASS_URL, FALLBACK_OVERPASS_URL,
                 "https://lambert.openstreetmap.de/api")
# These were public global mirrors and can still appear in saved-city metadata or
# existing OSMnx cache keys. They are no longer current defaults, but cached road
# responses from them remain valid and should stay reusable without networking.
_LEGACY_OVERPASS_URLS = (
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
)
# The round-robin endpoint performs the normal slot check. Direct-host fallbacks
# skip it so a broken /status route cannot prevent an interpreter request; HTTP
# 429 still moves immediately to the next host.
_NO_SLOT_LIMIT = {FALLBACK_OVERPASS_URL, OVERPASS_URLS[2]}

# Before every request OSMnx pins the Overpass hostname to one IP from gethostbyname.
# overpass-api.de round-robins two machines; on 2026-09-26 one refused connections and
# every pinned request to it failed. Unpinned, urllib3 tries each A record in turn.
ox._http._config_dns = lambda _url: None

ox.settings.use_cache = True
ox.settings.cache_folder = str(Path(__file__).resolve().parents[2] / "osmnx_cache")
ox.settings.requests_timeout = 180
ox.settings.log_console = True
ox.settings.http_user_agent = f"CityShift/1.0 (public city road-network analysis; OSMnx/{ox.__version__})"

# Bound the whole attempt as well as individual HTTP calls, including status polling.
# Leave room for a busy mirror and a larger-budget retry. This is separate from
# the smaller processing allowance declared in each query.
ATTEMPT_TIMEOUT_S = 300
# Healthy default-server runs in the cached cities' meta.json took 10-40 s including graph
# building. With no answer after this long, the fallback starts alongside; first to finish wins.
HEDGE_AFTER_S = 30
CONNECT_TIMEOUT_S = 5
STATUS_TIMEOUT_S = 10
HTTP_ATTEMPTS = 3
RETRY_PAUSE_S = 5
# Allow a little transport overhead beyond the timeout declared in an Overpass
# query. A server that never replies must not hold an interactive analysis for the
# full five-minute attempt deadline.
RESPONSE_GRACE_S = 15

T = TypeVar("T")


class OSMError(RuntimeError):
    """Overpass could not supply complete data. The message is readable in the UI."""


class _Abandoned(RuntimeError):
    """Stops a losing or timed-out attempt at its next Overpass request."""


class _QueryCapacityError(OSMError):
    """A valid Overpass reply says the query exceeded its time or memory budget."""


class _Attempt:
    def __init__(self, what: str, server: str, overrides: dict) -> None:
        self.what = what
        self.server = server
        self.source_server = server
        self.overrides = overrides
        self.started = time.perf_counter()
        self.answered = threading.Event()  # an Overpass response arrived; the rest is local work
        self.abandoned = threading.Event()
        self.response_deadline: float | None = None
        self.outcome: str | None = None


_current = threading.local()


def _servers() -> tuple[str, ...]:
    """An explicit list replaces the public defaults (also supports a private server)."""
    configured = os.environ.get("CITYSHIFT_OVERPASS_URLS")
    if not configured:
        return OVERPASS_URLS
    servers = tuple(dict.fromkeys(s.strip().rstrip("/").removesuffix("/interpreter")
                                 for s in configured.split(",") if s.strip()))
    if not servers or any(urlsplit(s).scheme not in {"http", "https"} or not urlsplit(s).netloc
                          for s in servers):
        raise OSMError("CITYSHIFT_OVERPASS_URLS must contain comma-separated HTTP(S) API URLs")
    return servers


class _OverpassHTTP:
    """Bound transport waits without changing OSMnx's numeric query timeout.

    Only Overpass uses this adapter; weather and other requests are unaffected.
    Status connection errors must escape OSMnx's automatic 60-second sleep.
    HTTP failures must reach our bounded failover instead of its recursive retries.
    """

    def __getattr__(self, name: str):
        return getattr(requests, name)

    def get(self, url, **kwargs):
        attempt = getattr(_current, "attempt", None)
        if attempt is not None and attempt.abandoned.is_set():
            raise _Abandoned(attempt.server)
        kwargs["timeout"] = (CONNECT_TIMEOUT_S, STATUS_TIMEOUT_S)
        try:
            response = requests.get(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise OSMError(f"Overpass status check failed: {_failure_reason(exc)}") from exc

    def post(self, url, **kwargs):
        attempt = getattr(_current, "attempt", None)
        requested_timeout = kwargs.get("timeout", ox.settings.requests_timeout)
        query = str(kwargs.get("data", {}).get("data", ""))
        match = re.search(r"\[timeout:(\d+)\]", query)
        query_timeout = int(match.group(1)) if match else requested_timeout
        for number in range(HTTP_ATTEMPTS):
            read_timeout = requested_timeout
            if attempt is not None:
                remaining = ATTEMPT_TIMEOUT_S - (time.perf_counter() - attempt.started)
                if attempt.abandoned.is_set() or remaining <= 0:
                    raise _Abandoned(attempt.server)
                read_timeout = min(read_timeout, remaining)
                attempt.response_deadline = min(
                    attempt.started + ATTEMPT_TIMEOUT_S,
                    time.perf_counter() + query_timeout + RESPONSE_GRACE_S,
                )
            kwargs["timeout"] = (CONNECT_TIMEOUT_S, read_timeout)
            response = requests.post(url, **kwargs)
            # A 429 means this server has no capacity for us. Trying another
            # server now is both faster and gentler than repeating the same query.
            if response.status_code == 429:
                break
            if response.status_code not in {502, 503, 504} or number == HTTP_ATTEMPTS - 1:
                break
            pause = _retry_pause(response, number)
            if attempt is not None and time.perf_counter() - attempt.started + pause >= ATTEMPT_TIMEOUT_S:
                response.raise_for_status()
            log.warning("%s: Overpass returned HTTP %d; retrying in %.1f s (%d/%d)",
                        attempt.what if attempt else "download", response.status_code, pause,
                        number + 2, HTTP_ATTEMPTS)
            response.close()
            if attempt is not None and attempt.abandoned.wait(pause):
                raise _Abandoned(attempt.server)
            if attempt is None:
                time.sleep(pause)
        response.raise_for_status()
        # Validate before OSMnx writes to its HTTP cache, so a broken HTTP-200
        # response cannot poison subsequent runs after the server recovers.
        try:
            payload = response.json()
        except ValueError as exc:
            raise OSMError("Overpass returned an invalid response") from exc
        _validate_response(payload)
        return response


def _retry_pause(response: requests.Response, number: int) -> float:
    pause = RETRY_PAUSE_S * (number + 1)
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            seconds = float(retry_after)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                seconds = 0
        pause = max(pause, seconds)
    return pause


def _validate_response(response) -> None:
    if not isinstance(response, dict) or not isinstance(response.get("elements"), list):
        raise OSMError("Overpass returned an invalid response")
    if response.get("remark"):
        # Overpass can return partial/empty data with HTTP 200 after a query timeout.
        remark = str(response["remark"])
        if any(reason in remark.lower() for reason in ("timed out", "out of memory")):
            raise _QueryCapacityError(f"Overpass query exceeded its resource budget: {remark}")
        raise OSMError(f"Overpass query failed: {response['remark']}")


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, requests.Timeout):
        return "request timed out"
    if isinstance(exc, requests.ConnectionError):
        return "DNS lookup failed" if "Failed to resolve" in str(exc) else "could not connect"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code} {exc.response.reason}"
    return str(exc)[:200] or type(exc).__name__


_overpass.requests = _OverpassHTTP()


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


def _cached_road_response(data, attempt: _Attempt):
    """Reuse identical road queries across mirrors and our old/new resource budgets.

    OSMnx includes the server URL and resource declarations in its cache key.
    Neither changes which roads a complete query returns. Keep every selection
    clause intact and only check the known headers we have used, before networking.
    """
    if attempt.what != "roads" or not ox.settings.use_cache:
        return None
    query = data.get("data", "")
    header, separator, body = query.partition(";")
    if not separator or not re.fullmatch(r"\[out:json\]\[timeout:\d+\](?:\[maxsize:\d+\])?", header):
        return None
    queries = dict.fromkeys((
        query,
        f"[out:json][timeout:60][maxsize:134217728];{body}",
        f"[out:json][timeout:180];{body}",
        f"[out:json][timeout:180][maxsize:536870912];{body}",
    ))
    servers = dict.fromkeys((attempt.server, *_servers(), *_LEGACY_OVERPASS_URLS))
    for server in servers:
        for candidate in queries:
            url = requests.Request("GET", server.rstrip("/") + "/interpreter",
                                   params={**data, "data": candidate}).prepare().url
            try:
                response = ox._http._retrieve_from_cache(url)
                if response is None:
                    continue
                _validate_response(response)
            except (OSError, ValueError, OSMError) as exc:
                log.warning("roads: ignoring unusable cached response from %s: %s", server, exc)
                continue
            attempt.source_server = server
            log.info("roads: reusing complete cached download from %s", server)
            return response
    return None


def _tracked_overpass_request(data):
    attempt = getattr(_current, "attempt", None)
    if attempt is not None and attempt.abandoned.is_set():
        raise _Abandoned(attempt.server)
    if attempt is not None:
        attempt.answered.clear()
        attempt.response_deadline = time.perf_counter() + STATUS_TIMEOUT_S + CONNECT_TIMEOUT_S
    try:
        response = _cached_road_response(data, attempt) if attempt is not None else None
        if response is None:
            if attempt is not None:
                attempt.source_server = attempt.server
            response = _overpass_request(data)
    except InsufficientResponseError as exc:
        # Invalid HTTP-200 JSON is a server failure, not a valid area with no features.
        raise OSMError("Overpass returned an invalid response") from exc
    _validate_response(response)
    if attempt is not None:
        if attempt.abandoned.is_set():
            raise _Abandoned(attempt.server)
        attempt.response_deadline = None
        attempt.answered.set()
    return response


# Track successful downloads and reject incomplete data before graph construction.
_overpass._overpass_request = _tracked_overpass_request

# OSMnx prints its own messages instead of using logging. These explain a slow download
# (rate-limit pauses, retries, response size, cache hits); the rest is noise, and "Post"
# carries the whole query URL.
_OSMNX_FORWARD = ("Pausing", "Downloaded", "Retrieved response from cache", "Unable to", "Unrecognized",
                  "Encountered gaierror")
_OSMNX_FORWARD_ANYWHERE = (" responded", " remarked", " returned HTTP status")
_osmnx_log = ox_utils.log


def _forward_osmnx_log(message: str, level: int | None = None, name: str | None = None,
                       filename: str | None = None) -> None:
    _osmnx_log(message, level=level, name=name, filename=filename)
    attempt = getattr(_current, "attempt", None)
    level = ox.settings.log_level if level is None else level
    if attempt is None or not (level >= logging.WARNING or message.startswith(_OSMNX_FORWARD)
                               or any(s in message for s in _OSMNX_FORWARD_ANYWHERE)):
        return
    log.log(max(level, logging.INFO), "%s via %s: %s", attempt.what, attempt.server, message)


ox_utils.log = _forward_osmnx_log


def _with_fallback(what: str, fn: Callable[[], T], prefer: str | None = None) -> tuple[T, str]:
    """Try each server, with at most two attempts running. First complete success wins.

    `prefer` (one of the configured servers) goes first. Road downloads check matching
    cached queries across all configured servers before making any network request.
    """
    finished: queue.Queue = queue.Queue()
    attempts: list[_Attempt] = []
    errors: list[str] = []
    order = _servers()
    if prefer in order:
        order = (prefer, *(s for s in order if s != prefer))
    servers = iter(order)
    next_server = next(servers, None)

    def start(server: str) -> None:
        attempt = _Attempt(what, server, {"overpass_url": server,
                                         "overpass_rate_limit": server not in _NO_SLOT_LIMIT})
        attempts.append(attempt)
        log.info("%s: querying %s (%d m radius, %d s limit)", what, server, DIST_M, ATTEMPT_TIMEOUT_S)

        def target() -> None:
            _current.attempt = attempt
            try:
                finished.put((attempt, True, fn()))
            except BaseException as exc:  # noqa: BLE001 - handed back to the caller's thread
                finished.put((attempt, False, exc))

        threading.Thread(target=joblog.in_context(target), name=f"overpass-{what}", daemon=True).start()

    def abandon_all() -> None:
        for attempt in attempts:
            attempt.abandoned.set()

    while True:
        now = time.perf_counter()
        for attempt in attempts:
            response_timed_out = (attempt.response_deadline is not None
                                  and now >= attempt.response_deadline
                                  and not attempt.answered.is_set())
            if attempt.outcome is None and (now - attempt.started >= ATTEMPT_TIMEOUT_S
                                            or response_timed_out):
                attempt.outcome = "timeout"
                attempt.abandoned.set()
                limit = (round(now - attempt.started) if response_timed_out else ATTEMPT_TIMEOUT_S)
                errors.append(f"{attempt.server} did not answer within {limit} s")
                log.warning("%s: %s", what, errors[-1])
        running = [a for a in attempts if a.outcome is None]
        if next_server is not None and len(running) < 2 and (
            not running or (not any(a.answered.is_set() for a in running)
                            and (attempts[-1].outcome is not None
                                 or now >= attempts[-1].started + HEDGE_AFTER_S))
        ):
            if running:
                log.warning("%s: still waiting for an Overpass response; also trying %s", what, next_server)
            start(next_server)
            next_server = next(servers, None)
            continue
        if not running:
            abandon_all()
            raise OSMError(f"OpenStreetMap download failed on all {len(attempts)} Overpass servers. "
                           f"Please retry shortly or configure CITYSHIFT_OVERPASS_URLS. {'; '.join(errors)}")
        # Poll the response events too: a subdivided query may begin another download.
        deadlines = [a.started + ATTEMPT_TIMEOUT_S for a in running]
        deadlines.extend(a.response_deadline for a in running if a.response_deadline is not None)
        wake = min(now + 0.2, *deadlines)
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
            log.info("%s answered by %s in %.1f s", what, attempt.source_server, elapsed)
            return value, attempt.source_server
        if isinstance(value, InsufficientResponseError):
            abandon_all()
            raise value
        attempt.outcome = "error"
        errors.append(f"{attempt.server}: {_failure_reason(value)}")
        log.warning("%s failed on %s after %.1f s: %s", what, attempt.server, elapsed, value)


def drive_graph(lat: float, lng: float, prefer: str | None = None) -> tuple[nx.MultiDiGraph, str]:
    """Drive network within DIST_M of the center. Returns (graph, overpass server used).

    Pass the server from the city's meta.json as `prefer` to reuse this machine's cached download.
    """
    return _with_fallback(
        "roads",
        lambda: _drive_graph_from_point(lat, lng),
        prefer,
    )


def _drive_graph_from_point(lat: float, lng: float) -> nx.MultiDiGraph:
    """Request the full road network with a modest initial server resource budget."""
    attempt = _current.attempt

    def download(timeout: int, memory: int) -> nx.MultiDiGraph:
        # Only this attempt sees the query budget. Keep the HTTP read timeout
        # unchanged and avoid changing concurrent road or infrastructure queries.
        attempt.overrides["overpass_settings"] = ox.settings.overpass_settings.format(
            timeout=timeout, maxsize=f"[maxsize:{memory}]",
        )
        return ox.graph_from_point((lat, lng), dist=DIST_M, network_type="drive")

    try:
        try:
            # Matches the successful saved-city batch, including its HTTP cache keys.
            return download(60, 128 * 1024**2)
        except _QueryCapacityError:
            log.warning("roads: query needs a larger resource budget; retrying the full area")
            return download(180, 512 * 1024**2)
    finally:
        attempt.overrides.pop("overpass_settings", None)


def osm_features(lat: float, lng: float, prefer: str | None = None) -> tuple[gpd.GeoDataFrame, str]:
    """All TAGS features within DIST_M. An area with none of them returns an empty frame."""
    try:
        return _with_fallback("infrastructure", lambda: _features_from_point(lat, lng), prefer)
    except InsufficientResponseError:
        log.warning("no OSM features matched TAGS near (%s, %s)", lat, lng)
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), ox.settings.overpass_url


def _features_query(bbox: tuple[float, float, float, float], timeout: int, memory: int) -> str:
    """Same tag union and bounding box as OSMnx, with one shared recursion.

    OSMnx's generic query repeats the polygon and member recursion for every
    tag value and element type (45 branches for TAGS). Grouping exact values
    by key gives six branches, and the Overpass bbox index avoids polygon work.
    """
    west, south, east, north = bbox
    bounds = f"({south:.6f},{west:.6f},{north:.6f},{east:.6f})"
    selectors = []
    for key, values in TAGS.items():
        if len(values) == 1:
            tag = f"[{json.dumps(key)}={json.dumps(values[0])}]"
        else:
            pattern = "^(" + "|".join(re.escape(value) for value in values) + ")$"
            tag = f"[{json.dumps(key)}~{json.dumps(pattern)}]"
        selectors.append(f"nwr{tag}{bounds};")
    settings = ox.settings.overpass_settings.format(timeout=timeout, maxsize=f"[maxsize:{memory}]")
    return f"{settings};({''.join(selectors)});(._;>;);out;"


def _features_from_point(lat: float, lng: float) -> gpd.GeoDataFrame:
    bbox = ox.utils_geo.bbox_from_point((lat, lng), dist=DIST_M)
    polygon = ox.utils_geo.bbox_to_poly(bbox)
    # Small declarations are admitted more readily on busy public servers.
    # Dense cities can retry with the original 180 s / 512 MiB resource budget.
    try:
        response = _overpass._overpass_request({"data": _features_query(bbox, 25, 64 * 1024**2)})
    except _QueryCapacityError:
        log.warning("infrastructure: query needs a larger resource budget; retrying the full area")
        response = _overpass._overpass_request({"data": _features_query(bbox, 180, 512 * 1024**2)})
    return ox.features._create_gdf([response], polygon, TAGS)
