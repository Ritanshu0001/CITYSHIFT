"""Locked constants and contract models for CityShift.

Source of truth: contracts/CONTRACTS.md, sections 3, 4.1, 4.2 and 4.3.
Owner: P1. Frozen at hour 0.5; after that, changes need all three people.
P2 imports the constants and column lists. P3 mirrors them in frontend/src/lib/constants.ts.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# --------------------------------------------------------------------------
# Section 3: fixed constants
# --------------------------------------------------------------------------
RADIUS_KM = 8
H3_RES = 8
MIN_ROAD_KM = 0.5  # hexes with less road are dropped

WEATHER_START = "2020-01-01"
WEATHER_END = "2024-12-31"
RAIN_MM = 1.0        # rain day: precipitation_sum >= RAIN_MM
HEAVY_RAIN_MM = 20.0  # heavy-rain day: precipitation_sum >= HEAVY_RAIN_MM
SNOW_CM = 1.0        # snow day: snowfall_sum >= SNOW_CM (Open-Meteo reports cm)

RARE_PRESENCE_THRESHOLD = 0.01  # feature present in < 1% of Phoenix hexes is rare
BAND_YELLOW = 80  # score <  80 -> green
BAND_RED = 95     # 80..95 -> yellow; >= 95 -> red
TOP_FEATURES_N = 3

JOB_STEPS = ["roads", "infrastructure", "weather", "scoring", "scenarios"]

REFERENCE_SLUG = "phoenix-az-usa"  # kept for compatibility; the reference is REFERENCE_SLUGS (CR-010)
REFERENCE_CENTER = {"lat": 33.4484, "lng": -112.0740}

# CR-010 (approved at sync): the reference is Waymo's established cities, pooled
# with equal weight per hex. Climate reference is the per-metric max across them.
REFERENCE_SLUGS = [
    "phoenix-az-usa",
    "san-francisco-ca-usa",
    "los-angeles-ca-usa",
    "austin-tx-usa",
    "atlanta-ga-usa",
]
REFERENCE_LABEL = "Waymo's established cities"

ISOFOREST_SEED = 42
NOVEL_Z_EQUIVALENT = 3.0  # z magnitude used for novel triggers in scenario priority

# --------------------------------------------------------------------------
# Section 4.3: feature table columns (cache/{slug}/features.csv)
# --------------------------------------------------------------------------
HEX_FEATURES = [
    # Network
    "intersection_density",
    "road_density",
    # Road mix
    "arterial_share",
    "motorway_share",
    "oneway_share",
    # Control
    "signal_density",
    "crosswalk_density",
    # Vulnerable road users
    "bike_lane_density",
    "transit_stop_density",
    # Activity
    "school_density",
    "nightlife_density",
    "tourism_density",
    # Infrastructure (usually rare)
    "bridge_count",
    "movable_bridge_count",
    "tunnel_count",
    "roundabout_count",
    "stadium_count",
]
assert len(HEX_FEATURES) == 17

FEATURE_CSV_COLUMNS = ["h3", "area_km2", "road_km", *HEX_FEATURES, "avg_lanes"]
assert len(FEATURE_CSV_COLUMNS) == 21

# Keys of cache/{slug}/city.json (contract 4.3)
CITY_JSON_KEYS = [
    "name", "slug", "lat", "lng", "radius_km",
    "country_code", "driving_side",
    "rain_days_per_year", "heavy_rain_days_per_year", "snow_days_per_year",
    "osm_completeness", "n_hexes_total", "n_hexes_kept", "created_at",
]

Band = Literal["green", "yellow", "red"]


def band_for(shift_score: float) -> Band:
    """Map a 0-100 shift score to its color band (contract section 3)."""
    if shift_score >= BAND_RED:
        return "red"
    if shift_score >= BAND_YELLOW:
        return "yellow"
    return "green"


# --------------------------------------------------------------------------
# Section 4.2: CityResult
# --------------------------------------------------------------------------
class TopFeature(BaseModel):
    name: str
    value: float
    ref_median: float
    z: float
    pct: float


class Hex(BaseModel):
    h3: str
    shift_score: float
    band: Band
    top_features: list[TopFeature]
    novel: list[str]


class Center(BaseModel):
    lat: float
    lng: float


class Climate(BaseModel):
    rain_days_per_year: float
    heavy_rain_days_per_year: float
    snow_days_per_year: float


class ClimateComparison(BaseModel):
    target: Climate
    reference: Climate


class FeatureComparison(BaseModel):
    name: str
    target: float
    reference: float


class Summary(BaseModel):
    city: str
    slug: str
    center: Center
    radius_km: float
    n_hexes: int
    pct_red: float
    climate: ClimateComparison
    driving_side: Literal["left", "right"]
    feature_comparison: list[FeatureComparison]
    osm_completeness: float
    novel_city: list[Literal["snow", "left_hand_traffic"]]


class Scenario(BaseModel):
    id: str
    priority: float
    title: str
    description: str
    triggered_by: list[str]
    hex_ids: list[str]
    scope: Literal["hex", "city"]


class CityResult(BaseModel):
    hexes: list[Hex]
    summary: Summary
    scenarios: list[Scenario]


# --------------------------------------------------------------------------
# Section 4.1: HTTP API
# --------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    name: str
    lat: float
    lng: float
    country_code: str | None = None


class AnalyzeResponse(BaseModel):
    job_id: str
    slug: str
    status: Literal["queued", "running", "done"]
    cached: bool


class JobStatus(BaseModel):
    job_id: str
    slug: str
    status: Literal["queued", "running", "done", "error"]
    step: str | None
    steps_done: list[str]
    message: str | None
    error: str | None


class CityListItem(BaseModel):
    slug: str
    name: str
    center: Center
    n_hexes: int
    pct_red: float
    created_at: str


class CitiesResponse(BaseModel):
    cities: list[CityListItem]
