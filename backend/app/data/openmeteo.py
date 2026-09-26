"""Open-Meteo HTTP: on-disk cache, per-minute call budget, loud errors.

Free tier: fewer than 600 calls per minute, 5,000 per hour, 10,000 per day. Open-Meteo
counts every 2 weeks of data per location as about 1 call, so one 5-year weather
request is ~130 calls, and each elevation coordinate is 1 call. Responses are cached
forever on disk: 2020-2024 history and terrain never change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

import requests

from app.cancellation import checkpoint, interruptible_wait

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "openmeteo_cache"
# Leave 20 calls of headroom under the free-tier limit. A city typically needs
# one 130-call weather request plus 8-10 100-point elevation batches. At 500,
# batch granularity left unused capacity in each window and forced a third
# minute for the final partial batch; 580 completes the same work in two.
MINUTE_BUDGET = 580.0

_lock = threading.Lock()
_window: deque[tuple[float, float]] = deque()  # (monotonic time, cost) of network calls
_run_total = 0.0


class OpenMeteoError(RuntimeError):
    """Open-Meteo did not answer usefully. The message is readable in the UI."""


class OpenMeteoQuotaError(OpenMeteoError):
    """HTTP 429 / limit exceeded. Callers stop the whole batch; never retry this."""


def weather_cost(n_days: int, n_variables: int, n_locations: int = 1) -> float:
    """Open-Meteo's fractional call count: 2 weeks and 10 variables per location per call."""
    return max(1.0, n_days / 14) * max(1.0, n_variables / 10) * n_locations


def run_total() -> float:
    """Estimated calls sent over the network by this process (cache hits cost nothing)."""
    return _run_total


def _wait_for_budget(cost: float, cancel_event: threading.Event | None = None) -> None:
    while True:
        checkpoint(cancel_event)
        with _lock:
            now = time.monotonic()
            while _window and now - _window[0][0] >= 60:
                _window.popleft()
            used = sum(c for _, c in _window)
            if not _window or used + cost <= MINUTE_BUDGET:
                _window.append((now, cost))
                return
            sleep_for = 60 - (now - _window[0][0]) + 0.1
        log.info("Open-Meteo: %.0f calls in the last minute, pausing %.0f s", used, sleep_for)
        interruptible_wait(cancel_event, sleep_for)


def _reason(resp: requests.Response) -> str:
    try:
        return str(resp.json().get("reason", "")) or resp.text[:200]
    except ValueError:
        return resp.text[:200]


def get_json(url: str, params: dict, *, cost: float, what: str,
             validate: Callable[[dict], None] | None = None,
             cancel_event: threading.Event | None = None) -> dict:
    """GET url with params, from the disk cache when possible. Raises OpenMeteoError.

    `validate` runs before anything is cached, so a garbled response raises instead
    of being stored and replayed forever.
    """
    global _run_total
    checkpoint(cancel_event)
    full_url = str(requests.Request("GET", url, params=params).prepare().url)
    path = CACHE_DIR / (hashlib.sha1(full_url.encode("utf-8")).hexdigest() + ".json")
    if path.is_file():
        log.debug("Open-Meteo %s: disk cache hit %s", what, path.name)
        return json.loads(path.read_text(encoding="utf-8"))

    _wait_for_budget(cost, cancel_event)
    t = time.perf_counter()
    try:
        resp = requests.get(full_url, timeout=60)
    except requests.RequestException as exc:
        raise OpenMeteoError(f"Open-Meteo {what} request failed: {exc}") from exc
    if resp.status_code == 429 or (resp.status_code != 200 and "limit exceeded" in resp.text.lower()):
        raise OpenMeteoQuotaError(f"Open-Meteo quota exceeded (429): {_reason(resp)}")
    if resp.status_code != 200:
        raise OpenMeteoError(f"Open-Meteo {what} returned HTTP {resp.status_code}: {_reason(resp)}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise OpenMeteoError(f"Open-Meteo {what} returned invalid JSON") from exc
    if isinstance(data, dict) and data.get("error"):
        raise OpenMeteoError(f"Open-Meteo {what} error: {data.get('reason', 'unknown')}")
    if validate is not None:
        validate(data)

    with _lock:
        _run_total += cost
        total = _run_total
    log.info("Open-Meteo %s: ~%.1f calls in %.1f s, %.0f KB (run total ~%.1f)",
             what, cost, time.perf_counter() - t, len(resp.content) / 1024, total)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(resp.text, encoding="utf-8")
    tmp.replace(path)
    return data
