"""Safe Journey: risk-averse routing on a city's drive network (rider-facing).

GPS apps minimise travel time. Here every street segment also carries a historical
crash exposure built from the NHTSA FARS fatal crashes behind the admin crash layer,
and a route minimises

    cost = time_s + lam * exposure

for a sweep of lam (seconds a rider pays per unit of exposure). lam = 0 is the usual
fastest route; larger lam buys lower exposure with extra minutes. The distinct,
non-dominated routes across the sweep are the rider's time-for-safety trade-off.

Exposure: each crash spreads a Gaussian (SIGMA_M) over nearby streets, weighted by
fatalities. A segment's exposure is that field integrated along the segment (mean of
samples x length / 100 m), so a route's total doesn't depend on how OSM splits
streets: driving straight through a crash site costs about the same wherever the
segment boundaries fall.

Rider feature only: nothing here feeds the Shift score.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

SIGMA_M = 60.0  # about half a Manhattan block: a crash taints its intersection and approaches
CUTOFF_M = 3 * SIGMA_M
SAMPLE_STEP_M = 20.0
EXPOSURE_UNIT_M = 100.0
INTERSECTION_DELAY_S = 5.0  # free-flow OSM speeds ignore signals; a flat per-segment delay keeps ETAs honest
NEAR_ROUTE_M = 45.0  # a crash within this of the route counts as "passed"
MAX_SNAP_M = 350.0
# Seconds paid per unit of exposure. One isolated single-fatality site driven straight
# through is ~1.5 units, so 3000 s/unit is "almost any detour to avoid it".
LAMBDAS = (0, 15, 40, 90, 180, 360, 720, 1500, 3000)
MIN_GAIN_PCT = 3.0  # a slower route must cut exposure by at least this many points to be listed...
MIN_GAIN_ABS = 0.5  # ...and by this many units (a third of one site), or "100% safer" can mean a crash 150 m away
DEFAULT_BUDGET_SHARE = 0.25  # recommended route: safest within +25% of the fastest ETA...
DEFAULT_BUDGET_MIN_S = 180  # ...or +3 min, whichever is larger

GRAPH_VERSION = 2  # bump when annotate() changes edge attributes; stale pickles are rebuilt


class RouteError(ValueError):
    """A request the rider can fix (outside the service area, no road nearby). Readable in the UI."""


class _Proj:
    """Local equirectangular metres around the city centre; plenty accurate inside 8 km."""

    def __init__(self, lat0: float, lng0: float):
        self.lat0, self.lng0 = lat0, lng0
        self.kx = 111_320.0 * math.cos(math.radians(lat0))
        self.ky = 110_540.0

    def xy(self, lat, lng) -> np.ndarray:
        return np.column_stack([(np.asarray(lng, float) - self.lng0) * self.kx,
                                (np.asarray(lat, float) - self.lat0) * self.ky])


@dataclass
class RoutingGraph:
    slug: str
    name: str
    center: tuple[float, float]
    G: nx.MultiDiGraph  # edge attrs: time_s, exposure, length, street, coords [(lat, lng), ...]
    crashes: list[dict]  # FARS points plus "street"
    node_ids: np.ndarray = field(repr=False)
    node_tree: cKDTree = field(repr=False)
    crash_tree: cKDTree | None = field(repr=False)
    version: int = GRAPH_VERSION

    @property
    def proj(self) -> _Proj:
        return _Proj(*self.center)


def _street(data: dict) -> str | None:
    for key in ("name", "ref"):
        value = data.get(key)
        if isinstance(value, list):
            value = next((v for v in value if isinstance(v, str)), None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _edge_coords(G: nx.MultiDiGraph, u, v, data: dict) -> list[tuple[float, float]]:
    """(lat, lng) points from u to v, following the OSM geometry when the edge has one."""
    if "geometry" not in data:
        return [(G.nodes[u]["y"], G.nodes[u]["x"]), (G.nodes[v]["y"], G.nodes[v]["x"])]
    coords = [(lat, lng) for lng, lat in data["geometry"].coords]
    ux, uy = G.nodes[u]["x"], G.nodes[u]["y"]
    if (coords[-1][1] - ux) ** 2 + (coords[-1][0] - uy) ** 2 < (coords[0][1] - ux) ** 2 + (coords[0][0] - uy) ** 2:
        coords.reverse()
    return coords


def _sample(xy: np.ndarray, step: float) -> np.ndarray:
    """Evenly spaced points along a polyline, endpoints included."""
    seglen = np.hypot(*np.diff(xy, axis=0).T)
    total = float(seglen.sum())
    if total == 0.0:
        return xy[:1]
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    d = np.linspace(0.0, total, max(2, math.ceil(total / step) + 1))
    return np.column_stack([np.interp(d, cum, xy[:, 0]), np.interp(d, cum, xy[:, 1])])


def annotate(G: nx.MultiDiGraph, points: list[dict], *, slug: str, name: str,
             center: tuple[float, float]) -> RoutingGraph:
    """Attach time_s and exposure to every edge. G needs travel_time and length on its edges."""
    proj = _Proj(*center)
    edges = list(G.edges(keys=True, data=True))

    sample_xy, sample_edge = [], []
    for i, (u, v, _k, data) in enumerate(edges):
        data["coords"] = _edge_coords(G, u, v, data)
        lat, lng = zip(*data["coords"])
        s = _sample(proj.xy(lat, lng), SAMPLE_STEP_M)
        sample_xy.append(s)
        sample_edge.append(np.full(len(s), i))
    samples = np.concatenate(sample_xy)
    sample_edge = np.concatenate(sample_edge)

    crash_xy = proj.xy([p["lat"] for p in points], [p["lng"] for p in points]) if points else np.empty((0, 2))
    intensity = np.zeros(len(samples))
    crash_tree = None
    crashes = [dict(p) for p in points]
    if len(crash_xy):
        weights = np.array([max(1, int(p.get("fatalities") or 1)) for p in points], float)
        crash_tree = cKDTree(crash_xy)
        sample_tree = cKDTree(samples)
        # ndarray output keeps zero-distance pairs; the sparse outputs silently drop them.
        pairs = sample_tree.sparse_distance_matrix(crash_tree, CUTOFF_M, output_type="ndarray")
        contrib = weights[pairs["j"]] * np.exp(-(pairs["v"] ** 2) / (2 * SIGMA_M ** 2))
        intensity = np.bincount(pairs["i"], weights=contrib, minlength=len(samples))
        # Name each crash after the street it sits on, for "avoids 3 sites on Canal St".
        _, nearest = sample_tree.query(crash_xy)
        for crash, s in zip(crashes, nearest):
            crash["street"] = _street(edges[sample_edge[s]][3])

    per_edge = np.bincount(sample_edge, weights=intensity, minlength=len(edges))
    per_edge /= np.bincount(sample_edge, minlength=len(edges))
    keep = {"time_s", "exposure", "length", "street", "ramp", "coords"}
    for (u, v, k, data), mean in zip(edges, per_edge):
        data["time_s"] = float(data["travel_time"]) + INTERSECTION_DELAY_S
        data["exposure"] = float(mean) * float(data["length"]) / EXPOSURE_UNIT_M
        data["street"] = _street(data)
        highway = data.get("highway")
        data["ramp"] = any(str(h).endswith("_link") for h in (highway if isinstance(highway, list) else [highway]))
        for attr in [a for a in data if a not in keep]:
            del data[attr]

    node_ids = np.array(list(G.nodes))
    node_xy = proj.xy([G.nodes[n]["y"] for n in node_ids], [G.nodes[n]["x"] for n in node_ids])
    return RoutingGraph(slug=slug, name=name, center=center, G=G, crashes=crashes,
                        node_ids=node_ids, node_tree=cKDTree(node_xy), crash_tree=crash_tree)


# ---- planning --------------------------------------------------------------------------

def _snap(rg: RoutingGraph, lat: float, lng: float, what: str, radius_m: float):
    xy = rg.proj.xy([lat], [lng])[0]
    if math.hypot(*xy) > radius_m:
        raise RouteError(f"{what} is outside the {rg.name.split(',')[0]} service area "
                         f"({radius_m / 1000:.0f} km around the city centre).")
    dist, i = rg.node_tree.query(xy)
    if dist > MAX_SNAP_M:
        raise RouteError(f"No drivable street near the {what.lower()}. Try a point on a road.")
    return rg.node_ids[i]


def _best_edge(G: nx.MultiDiGraph, u, v, lam: float) -> dict:
    return min(G[u][v].values(), key=lambda a: a["time_s"] + lam * a["exposure"])


def _bearing(a: tuple[float, float], b: tuple[float, float], proj: _Proj) -> float | None:
    (x0, y0), (x1, y1) = proj.xy([a[0], b[0]], [a[1], b[1]])
    if math.hypot(x1 - x0, y1 - y0) < 1.0:
        return None
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360  # 0 = north, clockwise


def _turn(delta: float) -> str:
    """Instruction verb for a heading change in degrees, positive = clockwise (right)."""
    side = "right" if delta > 0 else "left"
    mag = abs(delta)
    if mag < 25:
        return "Continue"
    if mag < 60:
        return f"Bear {side}"
    if mag < 150:
        return f"Turn {side}"
    return "Make a U-turn"


def _extend(run: dict, other: dict) -> None:
    run["distance_m"] += other["distance_m"]
    run["coords"].extend(other["coords"][1:])
    run["ramp"] = run["ramp"] and other["ramp"]


def _merge_runs(runs: list[dict]) -> list[dict]:
    out: list[dict] = []
    for run in runs:
        if out and out[-1]["street"] == run["street"]:
            _extend(out[-1], run)
        else:
            out.append(run)
    return out


def _steps(legs: list[dict], proj: _Proj) -> list[dict]:
    """Merge consecutive same-street edges into turn-by-turn steps."""
    runs = _merge_runs([{"street": leg["street"], "distance_m": leg["length"], "coords": list(leg["coords"]),
                         "ramp": leg["ramp"]} for leg in legs])
    # Fold unnamed slivers (slip lanes, short connectors) into the step before them, then
    # re-merge: a sliver between two stretches of West Street must not split it in two.
    folded: list[dict] = []
    for run in runs:
        if folded and run["street"] is None and run["distance_m"] < 60:
            _extend(folded[-1], run)
        else:
            folded.append(run)
    merged = _merge_runs(folded)

    steps = []
    prev_heading = None
    for i, run in enumerate(merged):
        coords = run["coords"]
        heading_in = next((b for a, c in zip(coords, coords[1:]) if (b := _bearing(a, c, proj)) is not None), None)
        street = run["street"]
        if street is None:
            instruction = "Head out" if i == 0 else ("Take the ramp" if run["ramp"] else "Continue on the connector road")
        elif i == 0:
            instruction = f"Head out on {street}"
        elif prev_heading is None or heading_in is None:
            instruction = f"Continue onto {street}"
        else:
            instruction = f"{_turn((heading_in - prev_heading + 180) % 360 - 180)} onto {street}"
        steps.append({"instruction": instruction, "street": street, "distance_m": round(run["distance_m"])})
        rev = coords[::-1]
        prev_heading = next(((b + 180) % 360 for a, c in zip(rev, rev[1:]) if (b := _bearing(a, c, proj)) is not None),
                            prev_heading)
    steps.append({"instruction": "Arrive at your drop-off", "street": None, "distance_m": 0})
    return steps


def _route(rg: RoutingGraph, path: list, lam: float) -> dict:
    legs = [_best_edge(rg.G, u, v, lam) for u, v in zip(path, path[1:])]
    coords = [legs[0]["coords"][0]]
    for leg in legs:
        coords.extend(leg["coords"][1:])
    near: set[int] = set()
    if rg.crash_tree is not None:
        lat, lng = zip(*coords)
        dense = _sample(rg.proj.xy(lat, lng), 10.0)
        for hits in rg.crash_tree.query_ball_point(dense, NEAR_ROUTE_M):
            near.update(hits)
    return {
        "lam": lam,
        "duration_s": sum(leg["time_s"] for leg in legs),
        "distance_m": sum(leg["length"] for leg in legs),
        "exposure": sum(leg["exposure"] for leg in legs),
        "crash_sites": sorted(near),
        "path": [[round(a, 6), round(b, 6)] for a, b in coords],
        "steps": _steps(legs, rg.proj),
    }


def _frontier(candidates: list[dict]) -> list[dict]:
    """Keep routes that are faster than every safer option and meaningfully safer than every faster one."""
    fastest = min(candidates, key=lambda r: (r["duration_s"], r["exposure"]))
    base = fastest["exposure"]
    kept = [fastest]
    for r in sorted(candidates, key=lambda r: (r["duration_s"], r["exposure"])):
        if r is fastest:
            continue
        cut = kept[-1]["exposure"] - r["exposure"]
        if cut >= MIN_GAIN_ABS and 100.0 * cut / base >= MIN_GAIN_PCT:
            kept.append(r)
    return kept


def _node_street(G: nx.MultiDiGraph, n) -> str | None:
    """The most common street name on the segments meeting at a node."""
    names = [a["street"] for _, _, a in G.out_edges(n, data=True)] + [a["street"] for _, _, a in G.in_edges(n, data=True)]
    names = [s for s in names if s]
    return max(set(names), key=names.count) if names else None


def plan(rg: RoutingGraph, origin: tuple[float, float], destination: tuple[float, float],
         radius_m: float) -> dict:
    """Fastest-to-safest route options between two (lat, lng) points."""
    o = _snap(rg, *origin, "Pickup", radius_m)
    d = _snap(rg, *destination, "Drop-off", radius_m)
    if o == d:
        raise RouteError("Pickup and drop-off are the same spot. Move one of them.")

    candidates, seen = [], set()
    for lam in LAMBDAS:
        def weight(_u, _v, attrs, lam=lam):
            return min(a["time_s"] + lam * a["exposure"] for a in attrs.values())
        try:
            _, path = nx.bidirectional_dijkstra(rg.G, o, d, weight=weight)
        except nx.NetworkXNoPath:
            raise RouteError("No drivable route connects those two points.") from None
        if tuple(path) not in seen:
            seen.add(tuple(path))
            candidates.append(_route(rg, path, lam))

    routes = _frontier(candidates)
    fastest, safest = routes[0], routes[-1]
    fastest_sites = set(fastest["crash_sites"])
    budget_s = max(DEFAULT_BUDGET_MIN_S, DEFAULT_BUDGET_SHARE * fastest["duration_s"])
    recommended = [r for r in routes if r["duration_s"] - fastest["duration_s"] <= budget_s][-1]

    for i, r in enumerate(routes):
        r["id"] = f"r{i}"
        r["extra_s"] = round(r["duration_s"] - fastest["duration_s"])
        r["exposure_reduction_pct"] = (round(100.0 * (1 - r["exposure"] / fastest["exposure"]), 1)
                                       if fastest["exposure"] > 0 else 0.0)
        r["avoided_sites"] = sorted(fastest_sites - set(r["crash_sites"]))
        r["duration_s"] = round(r["duration_s"])
        r["distance_m"] = round(r["distance_m"])
        r["exposure"] = round(r["exposure"], 3)
        if len(routes) == 1:
            r["label"] = "Fastest & safest"
        elif r is fastest:
            r["label"] = "Fastest"
        elif r is recommended:
            r["label"] = "Safe Journey"
        elif r is safest:
            r["label"] = "Safest"
        else:
            r["label"] = "Balanced"

    used = sorted({i for r in routes for i in r["crash_sites"]})
    crashes = {str(i): {k: rg.crashes[i].get(k) for k in
                        ("lat", "lng", "year", "month", "hour", "fatalities", "pedestrian", "cyclist", "dark", "street")}
               for i in used}
    return {
        "slug": rg.slug,
        # Where the car actually meets the rider; also labels dropped pins without a geocoder.
        "origin_street": _node_street(rg.G, o),
        "destination_street": _node_street(rg.G, d),
        "routes": routes,
        "fastest_id": fastest["id"],
        "safest_id": safest["id"],
        "recommended_id": recommended["id"],
        "default_budget_s": round(budget_s),
        "crashes": crashes,
        "method": {
            "source": "NHTSA FARS fatal crashes, 2020-2024",
            "kernel_sigma_m": SIGMA_M,
            "near_route_m": NEAR_ROUTE_M,
            "intersection_delay_s": INTERSECTION_DELAY_S,
        },
    }
