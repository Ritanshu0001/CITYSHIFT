"""Safe Journey: risk-averse routing on a city's drive network (rider-facing).

GPS apps minimise travel time. Here every street segment also carries a route risk,
and a route minimises

    cost = time_s + lam * risk

for a sweep of lam (seconds a rider pays per unit of risk). lam = 0 is the usual
fastest route; larger lam buys lower risk with extra minutes. The distinct,
non-dominated routes across the sweep are trimmed to three options for the rider:
fastest, balanced and safest. Each slower option must be meaningfully safer, pass no more
fatal-crash sites than the option before it, and be a different route rather than the
same one with a block changed (_frontier).

Risk comes in two layers, in units of "one intersection in a strong-shift (red) area":

1. Area risk from the city's hex shift scores (result.json). Every intersection the
   route crosses is a conflict point and costs the hex weight of the area it sits in;
   each 100 m driven adds AREA_RISK_PER_100M times that weight. So the safer ride crosses
   fewer intersections, and fewer of them in areas unlike Waymo's established cities.
2. Crash exposure from the NHTSA FARS fatal crashes behind the admin crash layer, added
   on top at CRASH_WEIGHT, heavy enough that the safer ride passes fewer fatal-crash
   sites even when that costs some intersections. Each crash spreads a Gaussian (SIGMA_M) over nearby streets,
   weighted by fatalities. A segment's exposure is that field integrated along the
   segment (mean of samples x length / 100 m), so a route's total doesn't depend on how
   OSM splits streets: driving straight through a crash site costs about the same
   wherever the segment boundaries fall.

The crash layer is baked into the pickled graph; the area layer is applied on every load
(score_areas), so a re-analysed city's new shift scores reach routing on restart.

Rider feature only: nothing here feeds the Shift score.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import h3
import networkx as nx
import numpy as np
from scipy.spatial import cKDTree

from app.schemas import H3_RES, band_for

SIGMA_M = 60.0  # about half a Manhattan block: a crash taints its intersection and approaches
CUTOFF_M = 3 * SIGMA_M
SAMPLE_STEP_M = 20.0
EXPOSURE_UNIT_M = 100.0
INTERSECTION_DELAY_S = 5.0  # free-flow OSM speeds ignore signals; a flat per-segment delay keeps ETAs honest
NEAR_ROUTE_M = 45.0  # a crash within this of the route counts as "passed"
MAX_SNAP_M = 350.0

# Area layer. Hex weight w = HEX_FLOOR + (1 - HEX_FLOOR) * (shift_score / 100) ** HEX_POWER:
# score 60 -> 0.37, 80 -> 0.61, 95 -> 0.89, 100 -> 1. The cube keeps red areas clearly
# costlier where most of a city scores high; the floor keeps an intersection from ever being free.
HEX_FLOOR = 0.2
HEX_POWER = 3
INTERSECTION_RISK = 1.0  # risk of one intersection at w = 1
MIN_STREETS = 3  # a node where this many streets meet is an intersection (OSMnx street_count)
AREA_RISK_PER_100M = 0.25  # 100 m of driving costs a quarter of an intersection in the same area
# One single-fatality site driven through (~1.5 exposure) ~ 6 red-area intersections. On 23
# NYC trips this cut the safest option's fatal-crash sites 77% (152 -> 35) for a median
# +2.7 min; at 1.0 the cut was 21% and most "safest" routes were the fastest one retouched.
CRASH_WEIGHT = 4.0

# Seconds paid per unit of risk, i.e. to skip about one intersection in a red area.
# 150 s/unit is "almost any detour that crosses fewer of them".
LAMBDAS = (0, 1, 2, 4, 7, 12, 20, 35, 70, 150)
MIN_GAIN_PCT = 5.0  # a slower route must cut risk by at least this many points to be listed...
MIN_GAIN_ABS = 1.0  # ...and by about one red-area intersection, or "safer" can mean a rounding error
MAX_SHARED = 0.8  # ...and run at least 20% of its distance on streets no faster option uses
DEFAULT_BUDGET_SHARE = 0.25  # recommended route: safest within +25% of the fastest ETA...
DEFAULT_BUDGET_MIN_S = 180  # ...or +3 min, whichever is larger

GRAPH_VERSION = 2  # bump when annotate() changes edge attributes; stale pickles are rebuilt
BANDS = ("green", "yellow", "red")


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
    # edge attrs: time_s, exposure, length, street, ramp, coords [(lat, lng), ...];
    # score_areas adds area_risk, crossing_risk, crossing, band_m, risk
    G: nx.MultiDiGraph
    crashes: list[dict]  # FARS points plus "street"
    node_ids: np.ndarray = field(repr=False)
    node_tree: cKDTree = field(repr=False)
    crash_tree: cKDTree | None = field(repr=False)
    version: int = GRAPH_VERSION
    areas: dict[str, float] = field(default_factory=dict, repr=False)  # h3 -> shift_score, set by score_areas

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
             center: tuple[float, float], hex_scores: dict[str, float] | None = None) -> RoutingGraph:
    """Attach time_s, exposure and risk to every edge. G needs travel_time and length on its edges."""
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
    rg = RoutingGraph(slug=slug, name=name, center=center, G=G, crashes=crashes,
                      node_ids=node_ids, node_tree=cKDTree(node_xy), crash_tree=crash_tree)
    score_areas(rg, hex_scores or {})
    return rg


# ---- area layer ------------------------------------------------------------------------

def _cell(lat: float, lng: float) -> str:
    return h3.latlng_to_cell(lat, lng, H3_RES)


def hex_weight(score: float) -> float:
    return HEX_FLOOR + (1.0 - HEX_FLOOR) * (score / 100.0) ** HEX_POWER


def _street_count(G: nx.MultiDiGraph, n) -> int:
    """Streets meeting at a node: OSMnx's street_count, else distinct neighbours (synthetic graphs)."""
    count = G.nodes[n].get("street_count")
    if count is None:
        count = len(set(G.successors(n)) | set(G.predecessors(n)))
    return int(count)


def score_areas(rg: RoutingGraph, hex_scores: dict[str, float]) -> None:
    """(Re)apply the area layer to every edge from a city's {h3: shift_score}, then set edge risk.

    A cell with no score (the square drive graph's corners outside the hex circle, or a
    clipped edge hex without enough road) borrows the mean of its scored neighbours, else
    the city median. With no scores at all every area counts as strong shift (w = 1), so
    routing falls back to intersections, distance and crashes.
    """
    G, proj = rg.G, rg.proj
    rg.areas = dict(hex_scores)
    fallback = statistics.median(hex_scores.values()) if hex_scores else 100.0
    memo: dict[str, float] = {}

    def score_of(cell: str) -> float:
        if cell not in memo:
            score = hex_scores.get(cell)
            if score is None:
                near = [hex_scores[c] for c in h3.grid_disk(cell, 1) if c in hex_scores]
                score = sum(near) / len(near) if near else fallback
            memo[cell] = score
        return memo[cell]

    node_w = {}
    for n, data in G.nodes(data=True):
        node_w[n] = hex_weight(score_of(_cell(data["y"], data["x"]))) if _street_count(G, n) >= MIN_STREETS else None

    for _u, v, data in G.edges(data=True):
        lat, lng = zip(*data["coords"])
        xy = _sample(proj.xy(lat, lng), SAMPLE_STEP_M)
        scores = [score_of(_cell(y / proj.ky + proj.lat0, x / proj.kx + proj.lng0)) for x, y in xy]
        weights = [hex_weight(s) for s in scores]
        length = float(data["length"])
        data["area_risk"] = AREA_RISK_PER_100M * float(np.mean(weights)) * length / EXPOSURE_UNIT_M
        # The intersection at the far end of the segment: a route pays for every one it enters.
        data["crossing"] = node_w[v] is not None
        data["crossing_risk"] = INTERSECTION_RISK * node_w[v] if data["crossing"] else 0.0
        bands = [band_for(s) for s in scores]
        data["band_m"] = tuple(length * bands.count(b) / len(bands) for b in BANDS)
        data["risk"] = data["area_risk"] + data["crossing_risk"] + CRASH_WEIGHT * data["exposure"]


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
    return min(G[u][v].values(), key=lambda a: a["time_s"] + lam * a["risk"])


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
    lat, lng = zip(*coords)
    dense_xy = _sample(rg.proj.xy(lat, lng), 10.0)
    near: set[int] = set()
    if rg.crash_tree is not None:
        for hits in rg.crash_tree.query_ball_point(dense_xy, NEAR_ROUTE_M):
            near.update(hits)
    proj = rg.proj
    cells = {_cell(y / proj.ky + proj.lat0, x / proj.kx + proj.lng0) for x, y in dense_xy}
    distance = sum(leg["length"] for leg in legs)
    band_m = [sum(leg["band_m"][i] for leg in legs) for i in range(len(BANDS))]
    return {
        "lam": lam,
        "duration_s": sum(leg["time_s"] for leg in legs),
        "distance_m": distance,
        "risk": sum(leg["risk"] for leg in legs),
        "risk_parts": {
            "intersections": sum(leg["crossing_risk"] for leg in legs),
            "distance": sum(leg["area_risk"] for leg in legs),
            "crashes": CRASH_WEIGHT * sum(leg["exposure"] for leg in legs),
        },
        # The last leg ends at the drop-off, which the rider doesn't drive through.
        "intersections": sum(leg["crossing"] for leg in legs[:-1]),
        "area_mix": {b: (100.0 * m / distance if distance else 0.0) for b, m in zip(BANDS, band_m)},
        "hexes": sorted(c for c in cells if c in rg.areas),
        "crash_sites": sorted(near),
        "path": [[round(a, 6), round(b, 6)] for a, b in coords],
        "steps": _steps(legs, rg.proj),
        "_edges": {(u, v): leg["length"] for (u, v), leg in zip(zip(path, path[1:]), legs)},  # for _shared; not sent
    }


def _shared(a: dict, b: dict) -> float:
    """Share of route a's distance driven on the same street segments as route b."""
    total = sum(a["_edges"].values())
    return sum(m for e, m in a["_edges"].items() if e in b["_edges"]) / total if total else 1.0


def _frontier(candidates: list[dict]) -> list[dict]:
    """Keep routes that are faster than every safer option and meaningfully safer than every faster one.

    A slower route is listed only if it cuts risk by MIN_GAIN_PCT / MIN_GAIN_ABS, passes no
    more fatal-crash sites than the option before it (so Safest never passes more than
    Fastest), and shares at most MAX_SHARED of its distance with each option already kept.
    """
    fastest = min(candidates, key=lambda r: (r["duration_s"], r["risk"]))
    base = fastest["risk"]
    kept = [fastest]
    for r in sorted(candidates, key=lambda r: (r["duration_s"], r["risk"])):
        if r is fastest:
            continue
        cut = kept[-1]["risk"] - r["risk"]
        if (cut >= MIN_GAIN_ABS and 100.0 * cut / base >= MIN_GAIN_PCT
                and len(r["crash_sites"]) <= len(kept[-1]["crash_sites"])
                and all(_shared(r, k) <= MAX_SHARED for k in kept)):
            kept.append(r)
    return kept


def _balanced(routes: list[dict], recommended: dict) -> dict:
    """The middle option: the recommended route if it sits between fastest and safest, else the one halfway in risk."""
    middle = routes[1:-1]
    if any(r is recommended for r in middle):
        return recommended
    target = (routes[0]["risk"] + routes[-1]["risk"]) / 2
    return min(middle, key=lambda r: abs(r["risk"] - target))


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
            return min(a["time_s"] + lam * a["risk"] for a in attrs.values())
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
    if len(routes) > 3:
        routes = [fastest, _balanced(routes, recommended), safest]

    for i, r in enumerate(routes):
        del r["_edges"]
        r["id"] = f"r{i}"
        r["extra_s"] = round(r["duration_s"] - fastest["duration_s"])
        r["risk_reduction_pct"] = (round(100.0 * (1 - r["risk"] / fastest["risk"]), 1)
                                   if fastest["risk"] > 0 else 0.0)
        r["avoided_sites"] = sorted(fastest_sites - set(r["crash_sites"]))
        r["duration_s"] = round(r["duration_s"])
        r["distance_m"] = round(r["distance_m"])
        r["risk"] = round(r["risk"], 2)
        r["risk_parts"] = {k: round(v, 2) for k, v in r["risk_parts"].items()}
        r["area_mix"] = {k: round(v, 1) for k, v in r["area_mix"].items()}
        if len(routes) == 1:
            r["label"] = "Fastest & safest"
        elif r is fastest:
            r["label"] = "Fastest"
        elif r is safest:
            r["label"] = "Safest"
        else:
            r["label"] = "Balanced"

    used = sorted({i for r in routes for i in r["crash_sites"]})
    crashes = {str(i): {k: rg.crashes[i].get(k) for k in
                        ("lat", "lng", "year", "month", "hour", "fatalities", "pedestrian", "cyclist", "dark", "street")}
               for i in used}
    areas = {c: {"shift_score": rg.areas[c], "band": band_for(rg.areas[c])}
             for c in sorted({c for r in routes for c in r["hexes"]})}
    return {
        "slug": rg.slug,
        # Where the car actually meets the rider; also labels dropped pins without a geocoder.
        "origin_street": _node_street(rg.G, o),
        "destination_street": _node_street(rg.G, d),
        "routes": routes,
        "fastest_id": fastest["id"],
        "safest_id": safest["id"],
        "recommended_id": recommended["id"],
        "crashes": crashes,
        "areas": areas,
        "method": {
            "area_source": "CityShift hex shift scores",
            "crash_source": "NHTSA FARS fatal crashes, 2020-2024",
            "intersection_risk": INTERSECTION_RISK,
            "area_risk_per_100m": AREA_RISK_PER_100M,
            "crash_weight": CRASH_WEIGHT,
            "kernel_sigma_m": SIGMA_M,
            "near_route_m": NEAR_ROUTE_M,
            "intersection_delay_s": INTERSECTION_DELAY_S,
        },
    }
