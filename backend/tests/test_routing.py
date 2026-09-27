"""Safe Journey routing on synthetic streets: no network, no cache.

Grid (turn-by-turn steps, crash kernel, rider errors):

    row 1:  o---o---o---o---o      detour row, 2 extra 200 m legs
                |   |   |
    row 0:  A---o---X---o---B      direct row; X is a fatal-crash site

Two roads (the risk layers). A and B sit between two parallel roads with the same
length and the same three intersections, each made by a dead-end side street:

    row 3:      s   s   s
                |   |   |
    row 2:  o---o---o---o---o      north road
            |               |
    row 1:  A               B
            |               |
    row 0:  o---o---o---o---o      south road
                |   |   |
    row -1:     s   s   s
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


def crash_at(lat: float, lng: float, fatalities: int = 1) -> dict:
    return {"lat": lat, "lng": lng, "year": 2023, "month": 5, "hour": 18, "fatalities": fatalities,
            "pedestrian": True, "cyclist": False, "dark": False, "h3": "x"}


def street(G: nx.MultiDiGraph, u: int, v: int, name: str, seconds: float = STEP_M / 10.0) -> None:
    for a, b in ((u, v), (v, u)):
        G.add_edge(a, b, length=STEP_M, travel_time=seconds, name=name, highway="residential")


def grid() -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for r in range(2):
        for c in range(5):
            lat, lng = latlng(r, c)
            G.add_node(node(r, c), y=lat, x=lng)
    for r in range(2):
        for c in range(4):
            street(G, node(r, c), node(r, c + 1), f"Row {r} St")
    # Avenues on columns 1-3 only, so exactly one detour (up Col 1, down Col 3) avoids X.
    for c in range(1, 4):
        street(G, node(0, c), node(1, c), f"Col {c} Ave")
    return G


def two_roads(south_s: float, north_s: float) -> nx.MultiDiGraph:
    """South and north roads between A (1, 0) and B (1, 4); *_s is the time for each 200 m of that road."""
    G = nx.MultiDiGraph()
    rows = {0: ("South Rd", south_s, -1), 2: ("North Rd", north_s, 3)}
    for r, c in [(1, 0), (1, 4)] + [(r, c) for r in rows for c in range(5)] + [(s, c) for _, _, s in rows.values() for c in (1, 2, 3)]:
        lat, lng = latlng(r, c)
        G.add_node(node(r, c), y=lat, x=lng)
    for r, (name, seconds, stub_row) in rows.items():
        for c in range(4):
            street(G, node(r, c), node(r, c + 1), name, seconds)
        for c in (1, 2, 3):
            street(G, node(r, c), node(stub_row, c), f"{name} Spur {c}")
        street(G, node(1, 0), node(r, 0), "West Link")
        street(G, node(1, 4), node(r, 4), "East Link")
    return G


def north_south_cells(monkeypatch) -> None:
    """Two stand-in hex cells: "north" above row 1, "south" at or below it."""
    monkeypatch.setattr(routing, "_cell", lambda lat, lng: "north" if lat > LAT0 + DLAT * 1.01 else "south")


def by_label(plan: dict) -> dict[str, dict]:
    return {r["label"]: r for r in plan["routes"]}


A, B = latlng(1, 0), latlng(1, 4)


@pytest.fixture
def rg() -> routing.RoutingGraph:
    crash = crash_at(*latlng(0, 2), fatalities=2)
    return routing.annotate(grid(), [crash], slug="test", name="Testville, ZZ", center=(LAT0, LNG0))


# ---- area layer: intersections and hex scores come first --------------------------------

def test_safest_route_crosses_fewer_intersections():
    # Main Street crosses three side streets; the parkway around it crosses none but is slower.
    G = nx.MultiDiGraph()
    for r, c in [(0, c) for c in range(5)] + [(-1, 1), (-1, 2), (-1, 3), (1, 0), (1, 4)]:
        lat, lng = latlng(r, c)
        G.add_node(node(r, c), y=lat, x=lng)
    for c in range(4):
        street(G, node(0, c), node(0, c + 1), "Main St")
    for c in (1, 2, 3):
        street(G, node(0, c), node(-1, c), f"Side St {c}")
    street(G, node(0, 0), node(1, 0), "Parkway")
    street(G, node(0, 4), node(1, 4), "Parkway")
    for a, b in ((node(1, 0), node(1, 4)), (node(1, 4), node(1, 0))):
        G.add_edge(a, b, length=4 * STEP_M, travel_time=60.0, name="Parkway", highway="primary")
    rg = routing.annotate(G, [], slug="test", name="Testville, ZZ", center=(LAT0, LNG0))

    plan = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)
    fastest, safest = by_label(plan)["Fastest"], by_label(plan)["Safest"]
    assert fastest["intersections"] == 3 and fastest["steps"][0]["street"] == "Main St"
    assert safest["intersections"] == 0 and safest["steps"][0]["street"] == "Parkway"
    assert safest["extra_s"] > 0
    assert safest["risk_reduction_pct"] > 30
    assert plan["recommended_id"] == safest["id"]


def test_same_intersections_in_a_familiar_area_are_safer(monkeypatch):
    north_south_cells(monkeypatch)
    rg = routing.annotate(two_roads(south_s=16.0, north_s=20.0), [], slug="test", name="Testville, ZZ",
                          center=(LAT0, LNG0), hex_scores={"south": 99.0, "north": 40.0})
    plan = routing.plan(rg, A, B, radius_m=5_000)
    fastest, safest = by_label(plan)["Fastest"], by_label(plan)["Safest"]

    assert fastest["intersections"] == safest["intersections"] == 3
    assert fastest["area_mix"]["red"] > 80 and safest["area_mix"]["green"] > 80
    assert safest["risk_parts"]["intersections"] < fastest["risk_parts"]["intersections"] / 2
    assert safest["risk_reduction_pct"] > 50
    assert plan["areas"] == {"north": {"shift_score": 40.0, "band": "green"},
                             "south": {"shift_score": 99.0, "band": "red"}}
    # A and B sit on row 1, which the stand-in cells count as south.
    assert fastest["hexes"] == ["south"] and safest["hexes"] == ["north", "south"]


def test_crash_layer_outweighs_a_milder_area(monkeypatch):
    # The quick south road is in a familiar area but passes a fatal-crash site; the north road is
    # strong shift and clear. Crashes weigh enough that the safest option takes the north road.
    north_south_cells(monkeypatch)
    crash = crash_at(*latlng(0, 2))
    rg = routing.annotate(two_roads(south_s=16.0, north_s=20.0), [crash], slug="test", name="Testville, ZZ",
                          center=(LAT0, LNG0), hex_scores={"south": 60.0, "north": 99.0})
    plan = routing.plan(rg, A, B, radius_m=5_000)
    fastest, safest = by_label(plan)["Fastest"], by_label(plan)["Safest"]

    assert fastest["crash_sites"] == [0] and fastest["area_mix"]["green"] > 80
    assert safest["crash_sites"] == [] and safest["area_mix"]["red"] > 80
    assert safest["risk_parts"]["intersections"] > fastest["risk_parts"]["intersections"]


def candidate(duration_s: float, risk: float, sites: list[int], edges: dict) -> dict:
    return {"duration_s": duration_s, "risk": risk, "crash_sites": sites, "_edges": edges}


def test_safer_options_never_pass_more_crash_sites():
    # The slower route is much lower risk on paper (fewer intersections) but passes one more crash site.
    fast = candidate(600, 50.0, [1], {("a", "b"): 1000.0})
    fewer_intersections = candidate(700, 30.0, [1, 2], {("a", "c"): 1000.0})
    fewer_sites = candidate(800, 40.0, [], {("a", "d"): 1000.0})
    assert routing._frontier([fast, fewer_intersections, fewer_sites]) == [fast, fewer_sites]


def test_near_copies_of_a_faster_route_are_not_offered():
    # 90% of the slower route is the fastest route with one block changed.
    fast = candidate(600, 50.0, [1, 2], {("a", "b"): 900.0, ("b", "z"): 100.0})
    retouched = candidate(610, 40.0, [1], {("a", "b"): 900.0, ("b", "y"): 100.0})
    different = candidate(700, 30.0, [], {("a", "c"): 500.0, ("c", "z"): 500.0})
    assert routing._frontier([fast, retouched, different]) == [fast, different]
    assert routing._shared(retouched, fast) == pytest.approx(0.9)


def test_unscored_cells_borrow_the_city_median():
    lat, lng = latlng(0, 0)
    scored = routing._cell(lat, lng)
    rg = routing.annotate(grid(), [], slug="test", name="Testville, ZZ", center=(LAT0, LNG0),
                          hex_scores={scored: 40.0, "8f2a1072b59ffff": 60.0, "8f2a1072b5bffff": 80.0})
    # Every intersection sits in the scored cell (40), a neighbour of it (their mean: 40) or
    # farther out (the median of the three: 60).
    weights = {round(d["crossing_risk"], 6) for _, _, d in rg.G.edges(data=True) if d["crossing"]}
    assert weights and weights <= {round(routing.hex_weight(40.0), 6), round(routing.hex_weight(60.0), 6)}


def test_without_hex_scores_every_area_counts_as_strong_shift(rg):
    edge = rg.G[node(0, 0)][node(0, 1)][0]
    assert edge["area_risk"] == pytest.approx(routing.AREA_RISK_PER_100M * 2)
    assert edge["crossing"] and edge["crossing_risk"] == pytest.approx(routing.INTERSECTION_RISK)
    assert routing.hex_weight(100.0) == pytest.approx(1.0)
    assert routing.hex_weight(0.0) == pytest.approx(routing.HEX_FLOOR)


# ---- crash layer -----------------------------------------------------------------------

def test_exposure_concentrates_on_streets_near_the_crash(rg):
    G = rg.G
    near = G[node(0, 1)][node(0, 2)][0]["exposure"]
    far = G[node(1, 0)][node(1, 1)][0]["exposure"]
    assert near > 1.0
    assert far < near / 100
    assert rg.crashes[0]["street"] in {"Row 0 St", "Col 2 Ave"}


def test_crash_layer_picks_between_otherwise_equal_roads():
    crash = crash_at(*latlng(0, 2), fatalities=2)
    rg = routing.annotate(two_roads(south_s=16.0, north_s=20.0), [crash], slug="test", name="Testville, ZZ",
                          center=(LAT0, LNG0))
    plan = routing.plan(rg, A, B, radius_m=5_000)
    fastest, safest = by_label(plan)["Fastest"], by_label(plan)["Safest"]

    assert fastest["crash_sites"] == [0] and fastest["steps"][1]["street"] == "South Rd"
    assert safest["crash_sites"] == [] and safest["avoided_sites"] == [0]
    assert safest["steps"][1]["street"] == "North Rd"
    assert safest["intersections"] == fastest["intersections"]
    assert safest["extra_s"] > 0
    assert plan["crashes"]["0"]["fatalities"] == 2


def test_tiny_risk_cuts_are_not_offered_as_safer_routes():
    # One crash 150 m off the south road: its exposure there is small but not zero.
    lat, lng = latlng(0, 2)
    far = crash_at(lat - 150 / 110_540.0, lng)
    rg = routing.annotate(two_roads(south_s=16.0, north_s=20.0), [far], slug="test", name="Testville, ZZ",
                          center=(LAT0, LNG0))
    plan = routing.plan(rg, A, B, radius_m=5_000)
    assert 0 < plan["routes"][0]["risk_parts"]["crashes"] < routing.MIN_GAIN_ABS
    assert len(plan["routes"]) == 1


# ---- options ---------------------------------------------------------------------------

def test_frontier_trades_time_for_risk_monotonically():
    crash = crash_at(*latlng(0, 2), fatalities=2)
    rg = routing.annotate(two_roads(south_s=16.0, north_s=20.0), [crash], slug="test", name="Testville, ZZ",
                          center=(LAT0, LNG0))
    routes = routing.plan(rg, A, B, radius_m=5_000)["routes"]
    assert len(routes) > 1
    for slower, faster in zip(routes[1:], routes):
        assert slower["duration_s"] >= faster["duration_s"]
        assert slower["risk"] < faster["risk"]


def test_long_frontier_trims_to_fastest_balanced_safest(rg, monkeypatch):
    def five(candidates):
        base = min(candidates, key=lambda r: r["duration_s"])
        return [{**base, "duration_s": base["duration_s"] + 60 * i, "risk": base["risk"] * (1 - 0.2 * i)}
                for i in range(5)]
    monkeypatch.setattr(routing, "_frontier", five)
    plan = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)
    assert [r["label"] for r in plan["routes"]] == ["Fastest", "Balanced", "Safest"]
    assert plan["recommended_id"] in {r["id"] for r in plan["routes"]}


def test_balanced_is_recommended_route_or_halfway_in_risk():
    routes = [{"risk": e} for e in (10.0, 8.0, 5.5, 2.0, 0.0)]
    assert routing._balanced(routes, routes[1]) is routes[1]
    assert routing._balanced(routes, routes[-1]) is routes[2]


def test_trip_with_no_safer_option_offers_one_route(rg):
    # Row 1 is the only sensible way along row 1: any other route is longer and crosses more.
    plan = routing.plan(rg, latlng(1, 0), latlng(1, 4), radius_m=5_000)
    assert [r["label"] for r in plan["routes"]] == ["Fastest & safest"]
    assert plan["fastest_id"] == plan["safest_id"] == plan["recommended_id"]


# ---- directions and errors -------------------------------------------------------------

def test_steps_turn_the_right_way(rg):
    detour = [node(0, 0), node(0, 1), node(1, 1), node(1, 2), node(1, 3), node(0, 3), node(0, 4)]
    route = routing._route(rg, detour, lam=0)
    # East along row 0, north up Col 1 (left), east along row 1 (right), south down Col 3 (right), east (left).
    assert [s["instruction"] for s in route["steps"]] == [
        "Head out on Row 0 St",
        "Turn left onto Col 1 Ave",
        "Turn right onto Row 1 St",
        "Turn right onto Col 3 Ave",
        "Turn left onto Row 0 St",
        "Arrive at your drop-off",
    ]
    assert route["intersections"] == 5


def test_plan_names_the_pickup_and_dropoff_streets(rg):
    plan = routing.plan(rg, latlng(0, 0), latlng(0, 4), radius_m=5_000)
    assert plan["origin_street"] == "Row 0 St"
    assert plan["destination_street"] == "Row 0 St"


def test_rider_errors_are_readable(rg):
    with pytest.raises(routing.RouteError, match="outside the Testville service area"):
        routing.plan(rg, latlng(0, 0), (LAT0 + 1.0, LNG0), radius_m=5_000)
    with pytest.raises(routing.RouteError, match="same spot"):
        routing.plan(rg, latlng(0, 0), latlng(0, 0), radius_m=5_000)
