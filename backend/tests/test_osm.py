"""Overpass fallback: per-attempt servers, early fallback when the default hangs, first success wins.

The download function is faked; it reads the server the way OSMnx does, through
osmnx._overpass.settings. Nothing touches the network.
"""
from __future__ import annotations

import sys
import json
import threading
import time
from pathlib import Path

import osmnx as ox
import pytest
import requests
from geopandas.testing import assert_geodataframe_equal

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.data import osm
from osmnx import _overpass

DEFAULT, FALLBACK = osm.DEFAULT_OVERPASS_URL, osm.FALLBACK_OVERPASS_URL
THIRD = osm.OVERPASS_URLS[2]
OSMNX_REQUEST = osm._overpass_request


@pytest.fixture(autouse=True)
def fast_limits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CITYSHIFT_OVERPASS_URLS", raising=False)
    monkeypatch.setattr(osm, "HEDGE_AFTER_S", 0.2)
    monkeypatch.setattr(osm, "ATTEMPT_TIMEOUT_S", 3)
    monkeypatch.setattr(osm, "RETRY_PAUSE_S", 0.01)
    monkeypatch.setattr(osm, "RATE_LIMIT_PAUSE_S", 0.01)
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


def test_all_servers_failing_raises_readable_error():
    def fn():
        raise ConnectionError(f"{_server()} refused")

    with pytest.raises(osm.OSMError, match="all 3 Overpass servers") as info:
        osm._with_fallback("roads", fn)
    assert all(server in str(info.value) for server in osm.OVERPASS_URLS)


def test_insufficient_response_is_not_retried():
    servers = []

    def fn():
        servers.append(_server())
        raise osm.InsufficientResponseError("no features")

    with pytest.raises(osm.InsufficientResponseError):
        osm._with_fallback("infrastructure", fn)
    assert servers == [DEFAULT]


def test_third_server_recovers_when_first_two_fail():
    servers = []

    def fn():
        servers.append(_server())
        if _server() != THIRD:
            raise requests.ConnectionError("Failed to resolve host")
        return "graph"

    assert osm._with_fallback("roads", fn) == ("graph", THIRD)
    assert servers == list(osm.OVERPASS_URLS)


def test_preferred_server_goes_first_then_the_usual_order():
    servers = []

    def fn():
        servers.append(_server())
        if _server() == THIRD:
            raise requests.ConnectionError("Failed to resolve host")
        return "graph"

    # The server that answered a city's analysis holds its OSMnx cache entry, so it's tried first.
    assert osm._with_fallback("roads", fn, prefer=FALLBACK) == ("graph", FALLBACK)
    assert osm._with_fallback("roads", fn, prefer=THIRD) == ("graph", DEFAULT)
    assert osm._with_fallback("roads", fn, prefer="https://unknown.example/api") == ("graph", DEFAULT)
    assert servers == [FALLBACK, THIRD, DEFAULT, DEFAULT]


def test_all_hung_servers_have_a_deadline(monkeypatch):
    monkeypatch.setattr(osm, "ATTEMPT_TIMEOUT_S", 0.1)
    monkeypatch.setattr(osm, "HEDGE_AFTER_S", 0.02)
    release = threading.Event()
    attempts = []

    def fn():
        attempts.append(osm._current.attempt)
        release.wait(3)
        return "late graph"

    started = time.monotonic()
    try:
        with pytest.raises(osm.OSMError, match="all 3 Overpass servers"):
            osm._with_fallback("roads", fn)
        assert time.monotonic() - started < 1
        assert len(attempts) == 3
        assert all(a.abandoned.is_set() for a in attempts)
    finally:
        release.set()


def test_configured_servers_replace_defaults_and_are_deduplicated(monkeypatch):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS",
                       " https://custom.example/api/interpreter/, https://custom.example/api, ")
    assert osm._servers() == ("https://custom.example/api",)
    assert osm._with_fallback("roads", lambda: "graph") == ("graph", "https://custom.example/api")


@pytest.mark.parametrize("value", [" , ", "ftp://example.com/api", "example.com/api"])
def test_invalid_server_configuration_is_readable(monkeypatch, value):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", value)
    with pytest.raises(osm.OSMError, match="comma-separated HTTP"):
        osm._servers()


def _response(status=200, body='{"elements": []}'):
    response = requests.Response()
    response.status_code = status
    response.reason = "Service Unavailable" if status != 200 else "OK"
    response.url = "https://example.com/api/interpreter"
    response._content = body.encode()
    response._content_consumed = True
    return response


def test_status_connection_failure_falls_back_without_sixty_second_sleep(monkeypatch):
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "use_cache", False)
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["timeout"] == (osm.CONNECT_TIMEOUT_S, osm.STATUS_TIMEOUT_S)
        raise requests.ConnectionError("connection refused")

    def post(url, **kwargs):
        calls.append(url)
        assert kwargs["timeout"][0] == osm.CONNECT_TIMEOUT_S
        assert 0 < kwargs["timeout"][1] <= osm.ATTEMPT_TIMEOUT_S
        assert kwargs["headers"]["User-Agent"].startswith("CityShift/")
        assert kwargs["data"]["data"].startswith("[out:json][timeout:180]")
        return _response()

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    started = time.monotonic()
    result = osm._with_fallback("roads", lambda: _overpass._overpass_request(
        {"data": _overpass._make_overpass_settings() + ";node(1);out;"}))
    assert result == ({"elements": []}, FALLBACK)
    assert time.monotonic() - started < 1
    assert calls == [DEFAULT + "/status", FALLBACK + "/interpreter"]


@pytest.mark.parametrize("status", [429, 504, 503])
def test_http_errors_have_bounded_retries_before_next_server(monkeypatch, status):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", f"{FALLBACK},{THIRD}")
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "use_cache", False)
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _response(status if url.startswith(FALLBACK) else 200)

    monkeypatch.setattr(requests, "post", post)
    assert osm._with_fallback("roads", lambda: _overpass._overpass_request({"data": "test"})) == (
        {"elements": []}, THIRD)
    assert calls == [FALLBACK + "/interpreter"] * osm.HTTP_ATTEMPTS + [THIRD + "/interpreter"]


@pytest.mark.parametrize("body", [
    '<html>Upstream unavailable</html>',
    '{"remark":"runtime error: Query timed out", "elements":[]}',
    '{"remark":"runtime error: Query timed out", "elements":[{"type":"node","id":1}]}',
    '{}',
    '[]',
])
def test_invalid_or_partial_response_tries_another_server_instead_of_empty_features(monkeypatch, body):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", f"{FALLBACK},{THIRD}")
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "use_cache", False)

    def post(url, **kwargs):
        return _response(body=body) if url.startswith(FALLBACK) else _response()

    monkeypatch.setattr(requests, "post", post)
    assert osm._with_fallback("infrastructure", lambda: _overpass._overpass_request({"data": "test"})) == (
        {"elements": []}, THIRD)


def test_invalid_response_is_not_cached_after_server_recovers(monkeypatch, tmp_path):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", FALLBACK)
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "use_cache", True)
    monkeypatch.setattr(ox.settings, "cache_folder", str(tmp_path))
    replies = iter([_response(body='{}'), _response()])
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: next(replies))
    download = lambda: _overpass._overpass_request({"data": "test"})
    with pytest.raises(osm.OSMError, match="invalid response"):
        osm._with_fallback("roads", download)
    assert list(tmp_path.iterdir()) == []
    assert osm._with_fallback("roads", download) == ({"elements": []}, FALLBACK)
    # The third attempt must hit cache: no mocked HTTP replies remain.
    assert osm._with_fallback("roads", download) == ({"elements": []}, FALLBACK)


def test_abandoned_attempt_cannot_keep_polling_status_or_send_query(monkeypatch):
    attempt = osm._Attempt("roads", DEFAULT, {})
    attempt.abandoned.set()
    monkeypatch.setattr(osm._current, "attempt", attempt, raising=False)
    for method in (_overpass.requests.get, _overpass.requests.post):
        with pytest.raises(osm._Abandoned):
            method(DEFAULT)


def test_temporary_gateway_timeout_recovers_on_same_server(monkeypatch):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", FALLBACK)
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "use_cache", False)
    replies = iter([_response(504), _response()])
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: next(replies))
    assert osm._with_fallback("roads", lambda: _overpass._overpass_request({"data": "test"})) == (
        {"elements": []}, FALLBACK)


def test_retry_after_beyond_deadline_does_not_send_another_request(monkeypatch):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", FALLBACK)
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "use_cache", False)
    response = _response(429)
    response.headers["Retry-After"] = "60"
    replies = iter([response])
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: next(replies))
    started = time.monotonic()
    with pytest.raises(osm.OSMError, match="HTTP 429"):
        osm._with_fallback("roads", lambda: _overpass._overpass_request({"data": "test"}))
    assert time.monotonic() - started < 1


def test_abandonment_interrupts_retry_backoff(monkeypatch):
    monkeypatch.setattr(osm, "RETRY_PAUSE_S", 1)
    attempt = osm._Attempt("roads", FALLBACK, {})
    monkeypatch.setattr(osm._current, "attempt", attempt, raising=False)
    replies = iter([_response(504)])
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: next(replies))
    timer = threading.Timer(0.02, attempt.abandoned.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(osm._Abandoned):
            _overpass.requests.post(FALLBACK)
        assert time.monotonic() - started < 0.5
    finally:
        timer.cancel()


def _feature_response():
    return {"elements": [
        {"type": "node", "id": 1, "lat": 0, "lon": 0, "tags": {"highway": "crossing"}},
        {"type": "node", "id": 2, "lat": 0, "lon": 0.002},
        {"type": "node", "id": 3, "lat": 0.002, "lon": 0.002},
        {"type": "node", "id": 4, "lat": 0.002, "lon": 0},
        {"type": "way", "id": 5, "nodes": [1, 2, 3, 4, 1], "tags": {"amenity": "school"}},
        {"type": "node", "id": 6, "lat": 1, "lon": 1, "tags": {"amenity": "school"}},
        {"type": "relation", "id": 7, "members": [{"type": "way", "ref": 5, "role": "outer"}],
         "tags": {"type": "multipolygon", "leisure": "stadium"}},
    ]}


def test_compact_query_preserves_osmnx_geometry_and_tag_filtering(monkeypatch):
    monkeypatch.setattr(osm, "_overpass_request", lambda data: _feature_response())
    original = ox.features_from_point((0, 0), osm.TAGS, dist=osm.DIST_M)
    compact = osm._features_from_point(0, 0)
    assert_geodataframe_equal(compact, original)
    assert set(compact.index) == {("node", 1), ("way", 5), ("relation", 7)}


def test_feature_query_matches_all_categories_without_partial_value_matches():
    import json
    import re
    query = osm._features_query((-1, -2, 3, 4), 25, 64 * 1024**2)
    selectors = re.findall(r'nwr\[("[^"]+")(=|~)("[^"]+")\]\(([^)]+)\);', query)
    assert len(selectors) == len(osm.TAGS)
    for key, values in osm.TAGS.items():
        selector = next(s for s in selectors if json.loads(s[0]) == key)
        _, operator, encoded, bounds = selector
        assert bounds == "-2.000000,-1.000000,4.000000,3.000000"
        expression = json.loads(encoded)
        candidates = values + ["not_" + value for value in values] + [value + "_other" for value in values]
        matched = [value for value in candidates
                   if (value == expression if operator == "=" else re.search(expression, value))]
        assert matched == values


def test_dense_area_retries_larger_budget_without_reducing_area(monkeypatch):
    queries = []

    def download(data):
        queries.append(data["data"])
        if len(queries) == 1:
            return {"elements": [], "remark": "runtime error: Query timed out"}
        return _feature_response()

    monkeypatch.setattr(osm, "_overpass_request", download)
    result = osm._features_from_point(0, 0)
    assert len(result) == 3
    assert "[timeout:25][maxsize:67108864]" in queries[0]
    assert "[timeout:180][maxsize:536870912]" in queries[1]
    assert queries[0].split(";", 1)[1] == queries[1].split(";", 1)[1]


def test_empty_valid_feature_response_remains_valid(monkeypatch):
    features, server = osm.osm_features(0, 0)
    assert features.empty
    assert str(features.crs) == "EPSG:4326"


def _road_response():
    return {"elements": [
        {"type": "node", "id": 1, "lat": 0, "lon": -0.01},
        {"type": "node", "id": 2, "lat": 0, "lon": 0},
        {"type": "node", "id": 3, "lat": 0, "lon": 0.01},
        {"type": "way", "id": 4, "nodes": [1, 2, 3], "tags": {"highway": "residential"}},
    ]}


def test_road_budget_preserves_area_filters_transport_and_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", FALLBACK)
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "cache_folder", str(tmp_path))
    queries = []

    def post(url, **kwargs):
        queries.append(kwargs["data"]["data"])
        assert kwargs["timeout"][0] == osm.CONNECT_TIMEOUT_S
        assert 0 < kwargs["timeout"][1] <= osm.ATTEMPT_TIMEOUT_S
        return _response(body=json.dumps(_road_response()))

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(ox.settings, "use_cache", False)
    original, _ = osm._with_fallback("roads", lambda: ox.graph_from_point(
        (0, 0), dist=osm.DIST_M, network_type="drive"))
    monkeypatch.setattr(ox.settings, "use_cache", True)
    smaller, server = osm.drive_graph(0, 0)
    cached, cached_server = osm.drive_graph(0, 0, prefer=server)
    assert len(queries) == 2  # the repeat uses the same cache key as the successful batch
    assert queries[0].startswith("[out:json][timeout:180];")
    assert queries[1].startswith("[out:json][timeout:60][maxsize:134217728];")
    assert queries[0].split(";", 1)[1] == queries[1].split(";", 1)[1]
    assert set(original.nodes) == set(smaller.nodes) == set(cached.nodes) == {1, 3}
    assert set(original.edges) == set(smaller.edges) == set(cached.edges)
    assert server == cached_server == FALLBACK
    assert ox.settings.requests_timeout == 180
    assert _overpass._make_overpass_settings() == "[out:json][timeout:180]"


@pytest.mark.parametrize("remark", ["runtime error: Query timed out", "runtime error: out of memory"])
def test_road_capacity_retry_rejects_partial_data_and_keeps_full_area(monkeypatch, tmp_path, remark):
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", FALLBACK)
    monkeypatch.setattr(osm, "_overpass_request", OSMNX_REQUEST)
    monkeypatch.setattr(ox.settings, "cache_folder", str(tmp_path))
    queries = []

    def post(url, **kwargs):
        queries.append(kwargs["data"]["data"])
        data = _road_response()
        if len(queries) == 1:
            data["remark"] = remark
        return _response(body=json.dumps(data))

    monkeypatch.setattr(requests, "post", post)
    graph, server = osm.drive_graph(0, 0)
    assert server == FALLBACK
    assert set(graph.nodes) == {1, 3}
    assert len(queries) == 2
    assert queries[0].startswith("[out:json][timeout:60][maxsize:134217728];")
    assert queries[1].startswith("[out:json][timeout:180][maxsize:536870912];")
    assert queries[0].split(";", 1)[1] == queries[1].split(";", 1)[1]
    assert len(list(tmp_path.glob("*.json"))) == 1  # partial responses never enter the cache


def test_dense_road_failure_can_recover_on_next_mirror(monkeypatch):
    calls = []

    def graph(*args, **kwargs):
        calls.append((_server(), _overpass._make_overpass_settings()))
        if _server() == DEFAULT:
            raise osm._QueryCapacityError("out of memory")
        return "graph"

    monkeypatch.setattr(ox, "graph_from_point", graph)
    assert osm.drive_graph(0, 0) == ("graph", FALLBACK)
    assert calls == [
        (DEFAULT, "[out:json][timeout:60][maxsize:134217728]"),
        (DEFAULT, "[out:json][timeout:180][maxsize:536870912]"),
        (FALLBACK, "[out:json][timeout:60][maxsize:134217728]"),
    ]


def test_road_budget_is_isolated_from_concurrent_infrastructure(monkeypatch):
    both_running = threading.Barrier(2, timeout=2)
    seen = {}

    def graph(*args, **kwargs):
        both_running.wait()
        seen["roads"] = _overpass._make_overpass_settings()
        return "graph"

    def features(*args):
        both_running.wait()
        seen["infrastructure"] = _overpass._make_overpass_settings()
        return "features"

    monkeypatch.setattr(ox, "graph_from_point", graph)
    monkeypatch.setattr(osm, "_features_from_point", features)
    road = threading.Thread(target=lambda: osm.drive_graph(0, 0))
    road.start()
    assert osm.osm_features(0, 0) == ("features", DEFAULT)
    road.join(3)
    assert not road.is_alive()
    assert seen == {
        "roads": "[out:json][timeout:60][maxsize:134217728]",
        "infrastructure": "[out:json][timeout:180]",
    }


@pytest.mark.parametrize("header", [
    "[out:json][timeout:180]",
    "[out:json][timeout:60][maxsize:134217728]",
    "[out:json][timeout:180][maxsize:536870912]",
])
@pytest.mark.parametrize("server", [DEFAULT, FALLBACK])
def test_road_download_reused_across_budgets_and_servers(monkeypatch, tmp_path, header, server):
    monkeypatch.setattr(ox.settings, "cache_folder", str(tmp_path))
    queries = []

    def capture(data):
        queries.append(data["data"])
        return _road_response()

    monkeypatch.setattr(osm, "_overpass_request", capture)
    osm.drive_graph(0, 0)
    body = queries[0].split(";", 1)[1]
    url = requests.Request("GET", server + "/interpreter",
                           params={"data": header + ";" + body}).prepare().url
    ox._http._save_to_cache(url, _road_response(), True)

    def no_network(*args, **kwargs):
        pytest.fail("A complete local road download must be used before contacting a server")

    monkeypatch.setattr(osm, "_overpass_request", no_network)
    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    graph, source = osm.drive_graph(0, 0, prefer=THIRD)
    assert source == server  # provenance must name the cached response's actual server
    assert set(graph.nodes) == {1, 3}


@pytest.mark.parametrize("different_query", [
    '[out:json][timeout:60][maxsize:134217728];way["highway"](1,1,2,2);out;',
    '[out:json][timeout:60][maxsize:134217728];way["railway"](0,0,1,1);out;',
    '[out:json][timeout:60][maxsize:134217728][date:"2020-01-01T00:00:00Z"];way["highway"](0,0,1,1);out;',
])
def test_cache_reuse_never_changes_area_filters_or_snapshot(monkeypatch, tmp_path, different_query):
    monkeypatch.setattr(ox.settings, "cache_folder", str(tmp_path))
    cached_query = '[out:json][timeout:180];way["highway"](0,0,1,1);out;'
    url = requests.Request("GET", DEFAULT + "/interpreter", params={"data": cached_query}).prepare().url
    ox._http._save_to_cache(url, _road_response(), True)
    sent = []

    def download(data):
        sent.append(data["data"])
        return {"elements": []}

    monkeypatch.setattr(osm, "_overpass_request", download)
    result, _ = osm._with_fallback("roads", lambda: _overpass._overpass_request({"data": different_query}))
    assert result == {"elements": []}
    assert sent == [different_query]


def test_road_cache_lookup_respects_configured_server_list(monkeypatch, tmp_path):
    monkeypatch.setattr(ox.settings, "cache_folder", str(tmp_path))
    monkeypatch.setenv("CITYSHIFT_OVERPASS_URLS", DEFAULT)
    query = '[out:json][timeout:60][maxsize:134217728];way["highway"](0,0,1,1);out;'
    url = requests.Request("GET", FALLBACK + "/interpreter", params={"data": query}).prepare().url
    ox._http._save_to_cache(url, _road_response(), True)
    sent = []

    def download(data):
        sent.append(data["data"])
        return {"elements": []}

    monkeypatch.setattr(osm, "_overpass_request", download)
    assert osm._with_fallback("roads", lambda: _overpass._overpass_request({"data": query})) == (
        {"elements": []}, DEFAULT)
    assert sent == [query]
