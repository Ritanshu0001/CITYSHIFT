"""build_city_data with elevation in the background, and Open-Meteo budget priority.

Every download is faked and cache/ is redirected to tmp_path; nothing touches the network.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from pathlib import Path

import geopandas as gpd
import h3
import networkx as nx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import cache, pipeline
from app.cancellation import AnalysisCancelled
from app.data import openmeteo

CLIMATE = {"rain_days_per_year": 100.0, "heavy_rain_days_per_year": 5.0, "snow_days_per_year": 2.0}
CELL = h3.latlng_to_cell(51.5, -0.12, 8)
LAT, LNG = h3.cell_to_latlng(CELL)
NAME = "Test Town"
SLUG = cache.slugify(NAME)


def _star_graph() -> nx.MultiDiGraph:
    """Three 200 m spokes from the center of CELL: 0.6 road km, enough to keep the hex."""
    G = nx.MultiDiGraph(crs="EPSG:4326")
    G.add_node(0, x=LNG, y=LAT, street_count=3)
    d = 200 / 111_000
    for i, (dy, dx) in enumerate([(d, 0.0), (-d, 0.0), (0.0, d * 1.6)], start=1):
        G.add_node(i, x=LNG + dx, y=LAT + dy, street_count=1)
        G.add_edge(0, i, key=0, osmid=i, length=200.0, highway="residential", oneway=True)
    return G


@pytest.fixture
def fake_downloads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(cache, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "drive_graph", lambda lat, lng: (_star_graph(), "test-overpass"))
    monkeypatch.setattr(pipeline, "osm_features",
                        lambda lat, lng: (gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), "test-overpass"))
    monkeypatch.setattr(pipeline, "climate_for", lambda lat, lng, cancel_event=None: dict(CLIMATE))


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


def test_background_elevation_does_not_hold_up_the_city(fake_downloads, monkeypatch):
    release = threading.Event()

    def slow_slopes(hex_ids, stats, cancel_event=None, background=False):
        assert background
        release.wait(5)
        stats.update(points=7, requests=1)
        return {h: 2.5 for h in hex_ids}

    monkeypatch.setattr(pipeline, "terrain_slopes", slow_slopes)
    _, city, meta = pipeline.build_city_data(NAME, LAT, LNG, "GB", background_elevation=True)

    assert city["n_hexes_kept"] == 1
    assert meta["elevation"]["status"] == "pending"
    assert cache.read_features(SLUG)["terrain_slope_pct"].isna().all()

    release.set()
    _wait_for(lambda: cache.read_json(SLUG, "meta.json")["elevation"]["status"] == "done")
    assert cache.read_features(SLUG)["terrain_slope_pct"].tolist() == [2.5]
    meta = cache.read_json(SLUG, "meta.json")
    assert meta["elevation"]["points"] == 7
    assert "elevation" in meta["timings_s"]


def test_background_elevation_failure_leaves_slope_empty_but_keeps_the_city(fake_downloads, monkeypatch):
    def failing_slopes(hex_ids, stats, cancel_event=None, background=False):
        raise openmeteo.OpenMeteoQuotaError("Open-Meteo quota exceeded (429): hourly")

    monkeypatch.setattr(pipeline, "terrain_slopes", failing_slopes)
    pipeline.build_city_data(NAME, LAT, LNG, "GB", background_elevation=True)

    # Whether the failure landed before or after the files were written, it ends up in meta.json.
    _wait_for(lambda: cache.read_json(SLUG, "meta.json")["elevation"]["status"].startswith("failed"))
    assert cache.read_features(SLUG)["terrain_slope_pct"].isna().all()


def test_late_elevation_is_dropped_when_a_newer_run_replaced_the_city(fake_downloads, monkeypatch):
    release = threading.Event()
    done = threading.Event()

    def slow_slopes(hex_ids, stats, cancel_event=None, background=False):
        release.wait(5)
        return {h: 2.5 for h in hex_ids}

    monkeypatch.setattr(pipeline, "terrain_slopes", slow_slopes)
    original_fill = pipeline._fill_slopes_later

    def fill_then_signal(*args):
        try:
            original_fill(*args)
        finally:
            done.set()

    monkeypatch.setattr(pipeline, "_fill_slopes_later", fill_then_signal)
    pipeline.build_city_data(NAME, LAT, LNG, "GB", background_elevation=True)
    city = cache.read_json(SLUG, "city.json")
    cache.write_json(SLUG, "city.json", {**city, "created_at": "2099-01-01T00:00:00Z"})

    release.set()
    assert done.wait(5)
    assert cache.read_features(SLUG)["terrain_slope_pct"].isna().all()
    assert cache.read_json(SLUG, "meta.json")["elevation"]["status"] == "pending"


def test_foreground_elevation_failure_still_fails_the_city(fake_downloads, monkeypatch):
    def failing_slopes(hex_ids, stats, cancel_event=None, background=False):
        assert not background
        raise openmeteo.OpenMeteoError("elevation down")

    monkeypatch.setattr(pipeline, "terrain_slopes", failing_slopes)
    with pytest.raises(pipeline.StepError, match="weather failed: elevation"):
        pipeline.build_city_data(NAME, LAT, LNG, "GB")
    assert not (cache.city_dir(SLUG) / "features.csv").exists()


def test_foreground_run_waits_for_elevation(fake_downloads, monkeypatch):
    def slopes(hex_ids, stats, cancel_event=None, background=False):
        time.sleep(0.2)
        return {h: 1.25 for h in hex_ids}

    monkeypatch.setattr(pipeline, "terrain_slopes", slopes)
    _, _, meta = pipeline.build_city_data(NAME, LAT, LNG, "GB")
    assert meta["elevation"]["status"] == "done"
    assert cache.read_features(SLUG)["terrain_slope_pct"].tolist() == [1.25]


def test_background_requests_leave_room_for_a_weather_request(monkeypatch):
    used = openmeteo.MINUTE_BUDGET - openmeteo.FOREGROUND_RESERVE
    monkeypatch.setattr(openmeteo, "_window", deque([(time.monotonic(), used)]))

    openmeteo._wait_for_budget(130.5)  # foreground: fits at once

    event = threading.Event()
    timer = threading.Timer(0.05, event.set)
    timer.start()
    try:
        with pytest.raises(AnalysisCancelled):
            openmeteo._wait_for_budget(1, event, background=True)
    finally:
        timer.cancel()
