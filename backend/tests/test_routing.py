"""Safe Journey routing on a synthetic grid: no network, no cache.

    row 1:  o---o---o---o---o      detour row, 2 extra 200 m legs
                |   |   |
    row 0:  A---o---X---o---B      direct row; X is a fatal-crash site
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import networkx as nx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import routing

LAT0, LNG0 = 40.70, -74.00
STEP_M = 200.0
DLAT = STEP_M / 110_540.0
DLNG = STEP_M / (111_320.0 * math.cos(math.radians(LAT0)))


def node(r: int, c: int) -> int:
    return r * 10 + c


def latlng(r: int, c: int) -> tuple[float, float]:
    return LAT0 + r * DLAT, LNG0 + c * DLNG


def grid() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for r in range(2):
        for c in range(5):
            lat, lng = latlng(r, c)
            G.add_node(node(r, c), y=lat, x=lng)
    pairs = [(node(r, c), node(r, c + 1), f"Row {r} St") for r in range(2) for c in range(4)]
    # Avenues on columns 1-3 only, so exactly one detour (up Col 1, down Col 3) avoids X.
    pairs += [(node(0, c), node(1, c), f"Col {c} Ave") for c in range(1, 4)]
    for u, v, name in pairs:
        for a, b in ((u, v), (v, u)):
            G.add_edge(a, b, length=STEP_M, travel_time=STEP_M / 10.0, name=name, highway="residential")
    return G


@pytest.fixture
def rg() -> routing.RoutingGraph:
    lat, lng = latlng(0, 2)
    crash = {"lat": lat, "lng": lng, "year": 2023, "month": 5, "hour": 18, "fatalities": 2,
             "pedestrian": True, "cyclist": False, "dark": False, "h3": "x"}
    return routing.annotate(grid(), [crash], slug="test", name="Testville, ZZ", center=(LAT0, LNG0))


def test_exposure_concentrates_on_streets_near_the_crash(rg):
    G = rg.G
    near = G[node(0, 1)][node(0, 2)][0]["exposure"]
    far = G[node(1, 0)][node(1, 1)][0]["exposure"]
    assert near > 1.0
    assert far < near / 100
    assert rg.crashes[0]["street"] in {"Row 0 St", "Col 2 Ave"}


def test_fastest_goes_through_the_crash_and_safe_journey_detours(rg):
    plan = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)
    routes = {r["id"]: r for r in plan["routes"]}
    fastest, safe = routes[plan["fastest_id"]], routes[plan["recommended_id"]]

    assert fastest["label"] == "Fastest"
    assert fastest["crash_sites"] == [0]
    assert fastest["distance_m"] == 800

    assert safe["label"] == "Safe Journey"
    assert safe["crash_sites"] == [] and safe["avoided_sites"] == [0]
    assert safe["distance_m"] == 1200
    assert safe["extra_s"] > 0
    assert safe["exposure_reduction_pct"] > 90
    assert plan["crashes"]["0"]["fatalities"] == 2


def test_frontier_trades_time_for_exposure_monotonically(rg):
    routes = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)["routes"]
    for slower, faster in zip(routes[1:], routes):
        assert slower["duration_s"] >= faster["duration_s"]
        assert slower["exposure"] < faster["exposure"]


def test_steps_turn_the_right_way(rg):
    plan = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)
    safe = next(r for r in plan["routes"] if r["id"] == plan["recommended_id"])
    instructions = [s["instruction"] for s in safe["steps"]]
    # East along row 0, north up Col 1 (left), east along row 1 (right), south down Col 3 (right), east (left).
    assert instructions == [
        "Head out on Row 0 St",
        "Turn left onto Col 1 Ave",
        "Turn right onto Row 1 St",
        "Turn right onto Col 3 Ave",
        "Turn left onto Row 0 St",
        "Arrive at your drop-off",
    ]


def test_trip_clear_of_crashes_offers_one_route(rg):
    # Row 1 runs 200 m from X, beyond the kernel: nothing worth trading time for.
    plan = routing.plan(rg, latlng(1, 0), latlng(1, 4), radius_m=5_000)
    assert [r["label"] for r in plan["routes"]] == ["Fastest & safest"]
    assert plan["fastest_id"] == plan["safest_id"] == plan["recommended_id"]


def test_tiny_exposure_cuts_are_not_offered_as_safer_routes():
    # One crash 150 m off the direct row: its exposure there is small but not zero.
    lat, lng = latlng(0, 2)
    far = {"lat": lat - 150 / 110_540.0, "lng": lng, "year": 2022, "month": 1, "hour": 3, "fatalities": 1,
           "pedestrian": False, "cyclist": False, "dark": True, "h3": "x"}
    rg = routing.annotate(grid(), [far], slug="test", name="Testville, ZZ", center=(LAT0, LNG0))
    plan = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)
    assert 0 < plan["routes"][0]["exposure"] < routing.MIN_GAIN_ABS
    assert len(plan["routes"]) == 1


def test_plan_names_the_pickup_and_dropoff_streets(rg):
    plan = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)
    assert plan["origin_street"] == "Row 0 St"
    assert plan["destination_street"] == "Row 0 St"


def test_rider_errors_are_readable(rg):
    with pytest.raises(routing.RouteError, match="outside the Testville service area"):
        routing.plan(rg, latlng(0, 0), (LAT0 + 1.0, LNG0), radius_m=5_000)
    with pytest.raises(routing.RouteError, match="same spot"):
        routing.plan(rg, latlng(0, 0), latlng(0, 0), radius_m=5_000)
