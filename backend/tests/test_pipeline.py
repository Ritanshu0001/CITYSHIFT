"""build_city_data with faked downloads (CR-020: no elevation download).

Every download is faked and cache/ is redirected to tmp_path; nothing touches the network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import h3
import networkx as nx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import cache, pipeline
from app.data import openmeteo
from app.schemas import FEATURE_CSV_COLUMNS

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
                        lambda lat, lng, prefer=None: (
                            gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), prefer or "test-overpass"))
    monkeypatch.setattr(pipeline, "climate_for", lambda lat, lng, cancel_event=None: dict(CLIMATE))


def test_city_data_is_written_without_any_elevation_download(fake_downloads):
    _, city, meta = pipeline.build_city_data(NAME, LAT, LNG, "GB")

    assert city["n_hexes_kept"] == 1
    assert "elevation" not in meta and "elevation" not in meta["timings_s"]
    features = cache.read_features(SLUG)
    assert list(features.columns) == FEATURE_CSV_COLUMNS
    assert features["terrain_slope_pct"].isna().all()
    assert features["road_km"].round(3).tolist() == [0.6]


def test_weather_failure_still_fails_the_city(fake_downloads, monkeypatch):
    def no_weather(lat, lng, cancel_event=None):
        raise openmeteo.OpenMeteoQuotaError("Open-Meteo quota exceeded (429): hourly")

    monkeypatch.setattr(pipeline, "climate_for", no_weather)
    with pytest.raises(pipeline.StepError, match="weather failed: Open-Meteo quota exceeded"):
        pipeline.build_city_data(NAME, LAT, LNG, "GB")
    assert not (cache.city_dir(SLUG) / "features.csv").exists()


def test_known_climate_skips_the_weather_download(fake_downloads, monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("weather should be reused, not downloaded")

    monkeypatch.setattr(pipeline, "climate_for", unexpected)
    _, city, meta = pipeline.build_city_data(NAME, LAT, LNG, "GB", climate=dict(CLIMATE))
    assert meta["climate_source"] == "reused from city.json"
    assert city["rain_days_per_year"] == CLIMATE["rain_days_per_year"]


def test_infrastructure_starts_after_roads_and_reuses_its_server(fake_downloads, monkeypatch):
    events = []

    def roads(lat, lng):
        events.extend(["roads-start", "roads-finish"])
        return _star_graph(), "working-overpass"

    def infrastructure(lat, lng, prefer=None):
        events.append(("infrastructure-start", prefer))
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"), prefer

    monkeypatch.setattr(pipeline, "drive_graph", roads)
    monkeypatch.setattr(pipeline, "osm_features", infrastructure)
    pipeline.build_city_data(NAME, LAT, LNG, "GB")

    assert events == [
        "roads-start",
        "roads-finish",
        ("infrastructure-start", "working-overpass"),
    ]
