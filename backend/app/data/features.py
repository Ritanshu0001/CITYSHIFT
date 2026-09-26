"""Per-hex feature table (contract 4.3).

Assignment: graph nodes by point, edges by midpoint, point features by location,
line features by midpoint, polygon features by centroid, all via h3.latlng_to_cell.

OSMnx stores merged tag values as list(set(...)), whose order changes between runs.
"Lists take the first value" is applied after sorting so output is deterministic.
"""
from __future__ import annotations

import re
import warnings

import geopandas as gpd
import h3
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from pyproj import Geod

from app.schemas import FEATURE_CSV_COLUMNS, H3_RES, MIN_ROAD_KM

ARTERIAL = {"primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link"}
MOTORWAY = {"motorway", "motorway_link", "trunk", "trunk_link"}
ONEWAY_TRUE = {"yes", "true", "1", "-1", "reverse"}
FALSY_TAG = {"", "no", "false", "0"}
TRANSIT_PT = {"platform", "station"}
TRANSIT_RAIL = {"station", "tram_stop"}
NIGHTLIFE = {"bar", "pub", "nightclub"}
TOURISM = {"hotel", "attraction"}

_GEOD = Geod(ellps="WGS84")
_LANES_RE = re.compile(r"\s*(\d+(?:\.\d+)?)")


def _first(value):
    """Scalar tag value: lists -> first after sorting, NaN -> None."""
    if isinstance(value, (list, tuple, set)):
        return sorted(value, key=str)[0] if value else None
    if value is None or pd.isna(value):
        return None
    return value


def _tag(df: pd.DataFrame, col: str) -> pd.Series:
    """Lowercase string tag column, NA where missing (pandas may turn None into NaN)."""
    if col not in df.columns:
        return pd.Series([None] * len(df), index=df.index, dtype=object)
    return df[col].map(lambda v: None if (f := _first(v)) is None else str(f).strip().lower())


def _is_truthy(tag: pd.Series) -> pd.Series:
    return tag.map(lambda v: isinstance(v, str) and v not in FALSY_TAG).astype(bool)


def _is_oneway(col: pd.Series) -> pd.Series:
    def one(v):
        v = _first(v)
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        return v is not None and str(v).strip().lower() in ONEWAY_TRUE

    return col.map(one).astype(bool)


def _lanes(v) -> float:
    v = _first(v)
    if v is None:
        return np.nan
    m = _LANES_RE.match(str(v))
    return float(m.group(1)) if m else np.nan


def _midpoints(geoms: gpd.GeoSeries) -> gpd.GeoSeries:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # midpoint in EPSG:4326 is fine at hex scale
        return geoms.interpolate(0.5, normalized=True)


def _cells(points: gpd.GeoSeries) -> list[str]:
    return [h3.latlng_to_cell(p.y, p.x, H3_RES) for p in points]


def _locations(geoms: gpd.GeoSeries) -> gpd.GeoSeries:
    """Point for each geometry: points as-is, lines by midpoint, polygons (and anything else) by centroid."""
    kind = geoms.geom_type
    lines = kind.isin(["LineString", "MultiLineString"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # centroid in EPSG:4326 is fine at hex scale
        loc = geoms.centroid
    loc[kind == "Point"] = geoms[kind == "Point"]
    loc[lines] = _midpoints(geoms[lines])
    return loc


def _dedupe_two_way(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """A drive MultiDiGraph stores two-way streets as u->v and v->u. Keep one copy of each."""
    u = edges.index.get_level_values("u").to_numpy()
    v = edges.index.get_level_values("v").to_numpy()
    osmid = edges["osmid"].map(lambda o: tuple(sorted(o)) if isinstance(o, list) else (o,))
    key = pd.DataFrame({
        "a": np.minimum(u, v),
        "b": np.maximum(u, v),
        "osmid": osmid.to_numpy(),
        "len": edges["length"].round(1).to_numpy(),
    })
    return edges[~key.duplicated().to_numpy()]


def build_features(hex_ids: list[str], G: nx.MultiDiGraph, feats: gpd.GeoDataFrame) -> tuple[pd.DataFrame, float]:
    """Feature table (FEATURE_CSV_COLUMNS, hexes with road_km >= MIN_ROAD_KM) and osm_completeness."""
    hex_set = set(hex_ids)
    out = pd.DataFrame(index=pd.Index(sorted(hex_set), name="h3"))
    out["area_km2"] = [h3.cell_area(h, unit="km^2") for h in out.index]

    # ---- graph nodes: intersections -------------------------------------------------
    nodes, edges = ox.graph_to_gdfs(G)
    nodes = nodes.assign(hex=[h3.latlng_to_cell(y, x, H3_RES) for y, x in zip(nodes["y"], nodes["x"])])
    nodes = nodes[nodes["hex"].isin(hex_set)]
    out["n_intersections"] = nodes[nodes["street_count"] >= 3].groupby("hex").size()

    # ---- graph edges: road length, mix, infrastructure -------------------------------
    edges = _dedupe_two_way(edges)
    edges = edges.assign(hex=_cells(_midpoints(edges.geometry)))
    edges = edges[edges["hex"].isin(hex_set)].copy()
    edges["km"] = edges["length"] / 1000.0
    highway = _tag(edges, "highway")
    bridge = _tag(edges, "bridge")
    edges["arterial_km"] = edges["km"].where(highway.isin(ARTERIAL), 0.0)
    edges["motorway_km"] = edges["km"].where(highway.isin(MOTORWAY), 0.0)
    oneway = _is_oneway(edges["oneway"]) if "oneway" in edges.columns else pd.Series(False, index=edges.index)
    edges["oneway_km"] = edges["km"].where(oneway, 0.0)
    edges["is_bridge"] = _is_truthy(bridge).astype(int)
    edges["is_movable"] = (bridge == "movable").astype(int)
    edges["is_tunnel"] = _is_truthy(_tag(edges, "tunnel")).astype(int)
    edges["is_roundabout"] = (_tag(edges, "junction") == "roundabout").astype(int)
    edges["lanes_num"] = edges["lanes"].map(_lanes) if "lanes" in edges.columns else np.nan

    by_hex = edges.groupby("hex")
    out["road_km"] = by_hex["km"].sum()
    for col in ["arterial_km", "motorway_km", "oneway_km"]:
        out[col] = by_hex[col].sum()
    out["bridge_count"] = by_hex["is_bridge"].sum()
    out["movable_bridge_count"] = by_hex["is_movable"].sum()
    out["tunnel_count"] = by_hex["is_tunnel"].sum()
    out["roundabout_count"] = by_hex["is_roundabout"].sum()
    out["avg_lanes"] = by_hex["lanes_num"].mean()

    has_tags = pd.Series(False, index=edges.index)
    for col in ["maxspeed", "lanes"]:
        if col in edges.columns:
            has_tags |= edges[col].map(lambda v: _first(v) is not None)
    osm_completeness = round(float(has_tags.mean()), 3) if len(edges) else 0.0

    # ---- OSM features: control, VRU, activity, stadiums -------------------------------
    if len(feats):
        feats = feats.assign(hex=_cells(_locations(feats.geometry)))
        feats = feats[feats["hex"].isin(hex_set)].copy()
        kind = feats.geom_type
        f_highway = _tag(feats, "highway")
        f_amenity = _tag(feats, "amenity")
        is_line = kind.isin(["LineString", "MultiLineString"])
        masks = {
            "n_signals": (f_highway == "traffic_signals") & (kind == "Point"),
            "n_crossings": (f_highway == "crossing") & (kind == "Point"),
            # one physical stop often carries several transit tags: count it once
            "n_transit": (f_highway == "bus_stop")
            | _tag(feats, "public_transport").isin(TRANSIT_PT)
            | _tag(feats, "railway").isin(TRANSIT_RAIL),
            "n_schools": f_amenity == "school",
            "n_nightlife": f_amenity.isin(NIGHTLIFE),
            "n_tourism": _tag(feats, "tourism").isin(TOURISM),
            "stadium_count": _tag(feats, "leisure") == "stadium",
        }
        for col, mask in masks.items():
            out[col] = feats[mask.to_numpy()].groupby("hex").size()
        cycle = feats[((f_highway == "cycleway") & is_line).to_numpy()]
        cycle_km = pd.Series([_GEOD.geometry_length(g) / 1000.0 for g in cycle.geometry], index=cycle.index)
        out["cycle_km"] = cycle_km.groupby(cycle["hex"]).sum()

    # ---- assemble --------------------------------------------------------------------
    count_cols = [
        "n_intersections", "road_km", "arterial_km", "motorway_km", "oneway_km",
        "bridge_count", "movable_bridge_count", "tunnel_count", "roundabout_count",
        "n_signals", "n_crossings", "n_transit", "n_schools", "n_nightlife", "n_tourism",
        "stadium_count", "cycle_km",
    ]
    for col in count_cols:
        out[col] = out[col].fillna(0) if col in out.columns else 0
    if "avg_lanes" not in out.columns:
        out["avg_lanes"] = np.nan

    out = out[out["road_km"] >= MIN_ROAD_KM].copy()
    area, road = out["area_km2"], out["road_km"]
    out["intersection_density"] = out["n_intersections"] / area
    out["road_density"] = road / area
    out["arterial_share"] = np.where(road > 0, out["arterial_km"] / road, 0.0)
    out["motorway_share"] = np.where(road > 0, out["motorway_km"] / road, 0.0)
    out["oneway_share"] = np.where(road > 0, out["oneway_km"] / road, 0.0)
    out["signal_density"] = out["n_signals"] / area
    out["crosswalk_density"] = out["n_crossings"] / area
    out["bike_lane_density"] = out["cycle_km"] / area
    out["transit_stop_density"] = out["n_transit"] / area
    out["school_density"] = out["n_schools"] / area
    out["nightlife_density"] = out["n_nightlife"] / area
    out["tourism_density"] = out["n_tourism"] / area

    out = out.reset_index()
    int_cols = ["bridge_count", "movable_bridge_count", "tunnel_count", "roundabout_count", "stadium_count"]
    out[int_cols] = out[int_cols].astype(int)
    float_cols = [c for c in FEATURE_CSV_COLUMNS if c not in int_cols and c != "h3"]
    out[float_cols] = out[float_cols].astype(float).round(6)
    return out[FEATURE_CSV_COLUMNS], osm_completeness
