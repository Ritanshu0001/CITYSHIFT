"""Overpass fallback: per-attempt servers, early fallback when the default hangs, first success wins.

The download function is faked; it reads the server the way OSMnx does, through
osmnx._overpass.settings. Nothing touches the network.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import osmnx as ox
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.data import osm
from osmnx import _overpass

DEFAULT, FALLBACK = osm.DEFAULT_OVERPASS_URL, osm.FALLBACK_OVERPASS_URL


@pytest.fixture(autouse=True)
def fast_limits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(osm, "HEDGE_AFTER_S", 0.2)
    monkeypatch.setattr(osm, "ATTEMPT_TIMEOUT_S", 3)
    monkeypatch.setattr(osm, "_overpass_request", lambda data: {"elements": []})


def _server() -> str:
    return _overpass.settings.overpass_url


def test_settings_read_through_outside_an_attempt():
    assert _overpass.settings.overpass_url == ox.settings.overpass_url
    assert _overpass.settings.requests_timeout == ox.settings.requests_timeout


def test_default_server_used_when_healthy():
    servers = []

    def fn():
        servers.append(_server())
        return "graph"

    assert osm._with_fallback("roads", fn) == ("graph", DEFAULT)
    assert servers == [DEFAULT]


def test_fast_failure_goes_straight_to_fallback_without_rate_limit_check():
    def fn():
        if _server() == DEFAULT:
            raise ConnectionError("refused")
        assert _overpass.settings.overpass_rate_limit is False
        return "graph"

    started = time.perf_counter()
    assert osm._with_fallback("roads", fn) == ("graph", FALLBACK)
    assert time.perf_counter() - started < osm.HEDGE_AFTER_S


def test_hung_default_starts_fallback_early_and_is_abandoned():
    release_default = threading.Event()
    default_outcome = []

    def fn():
        if _server() == DEFAULT:
            release_default.wait(3)
            try:
                _overpass._overpass_request({})
            except osm._Abandoned:
                default_outcome.append("abandoned")
                raise
            default_outcome.append("finished")
            return "late"
        return "graph"

    started = time.perf_counter()
    assert osm._with_fallback("roads", fn) == ("graph", FALLBACK)
    assert time.perf_counter() - started < osm.ATTEMPT_TIMEOUT_S
    release_default.set()
    deadline = time.monotonic() + 2
    while not default_outcome and time.monotonic() < deadline:
        time.sleep(0.01)
    assert default_outcome == ["abandoned"]


def test_no_fallback_once_default_has_answered():
    servers = []

    def fn():
        servers.append(_server())
        _overpass._overpass_request({})
        time.sleep(osm.HEDGE_AFTER_S * 2)  # building the graph locally
        return "graph"

    assert osm._with_fallback("roads", fn) == ("graph", DEFAULT)
    assert servers == [DEFAULT]


def test_roads_and_infrastructure_fall_back_at_the_same_time():
    both_on_fallback = threading.Barrier(2, timeout=2)
    results = {}

    def fn():
        if _server() == DEFAULT:
            raise ConnectionError("refused")
        both_on_fallback.wait()  # breaks if the fallbacks run one after the other
        return "ok"

    def run(what):
        results[what] = osm._with_fallback(what, fn)

    threads = [threading.Thread(target=run, args=(w,)) for w in ("roads", "infrastructure")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert results == {"roads": ("ok", FALLBACK), "infrastructure": ("ok", FALLBACK)}


def test_both_servers_failing_raises_readable_error():
    def fn():
        raise ConnectionError(f"{_server()} refused")

    with pytest.raises(osm.OSMError, match="both Overpass servers") as info:
        osm._with_fallback("roads", fn)
    assert DEFAULT in str(info.value) and FALLBACK in str(info.value)


def test_insufficient_response_is_not_retried():
    servers = []

    def fn():
        servers.append(_server())
        raise osm.InsufficientResponseError("no features")

    with pytest.raises(osm.InsufficientResponseError):
        osm._with_fallback("infrastructure", fn)
    assert servers == [DEFAULT]
