"""Deterministic scenario cards derived from feature and climate rules."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas import NOVEL_Z_EQUIVALENT
from .scoring import z_matrix


TITLES = {
    "movable_bridge": "Queue at an opening bridge + adjacent lane change",
    "rain_dense_intersection": "Heavy rain at a dense signalized intersection with a pedestrian crossing",
    "crosswalk_wide_arterial": "Pedestrian crossing a wide arterial",
    "cyclist_complex_intersection": "Cyclist at a complex intersection (car turning across a cyclist)",
    "late_night_pedestrians": "Late-night pedestrian activity",
    "stadium_event": "Event crowd leaving + rideshare pickup congestion",
    "bus_in_lane": "Bus stopping in lane and pulling out",
    "snow_traction": "Reduced traction + hidden lane markings",
    "left_hand_traffic": "Mirrored turn logic; turns across oncoming traffic",
    "roundabout_or_tunnel": "Multi-lane roundabout entry; GPS loss and lighting change in a tunnel",
}


def _card(rule_id: str, title: str, triggers: list[str], description: str, ids: list[str], z_magnitude: float, scope: str = "hex", n_affected: int | None = None) -> dict | None:
    # Contract 4.7: priority = z_mag x n_hexes_affected, and for scope="city"
    # n_hexes_affected is the city's hex count, not the (empty) hex_ids list.
    count = len(ids) if n_affected is None else n_affected
    if count == 0:
        return None  # "A rule with zero affected hexes produces no card."
    return {
        "id": rule_id,
        "priority": round(float(z_magnitude * count), 1),
        "title": title,
        "description": description,
        "triggered_by": list(triggers),
        "hex_ids": ids if scope == "hex" else [],
        "scope": scope,
    }


def _ids(features: pd.DataFrame, mask: pd.Series) -> list[str]:
    return [str(value) for value in features.loc[mask, "h3"]]


def _novel_ids(hexes: list[dict], *names: str) -> list[str]:
    """Hex ids whose novel[] contains any of these features.

    Contract 4.7 phrases the infrastructure rules as "any hex with
    movable_bridge_count in novel", so the trigger follows novel[] rather than a
    raw count. That keeps a card's hex_ids in step with the warning markers the
    frontend draws, and means the rule goes quiet when the feature turns out to
    be common enough on Phoenix to be modeled instead of flagged.
    """
    wanted = set(names)
    return [str(item["h3"]) for item in hexes if wanted.intersection(item.get("novel", ()))]


def _mean_abs(z_values: pd.DataFrame, feature: str, mask: pd.Series) -> float:
    return float(z_values.loc[mask, feature].abs().mean())


def _modeled(z_values: pd.DataFrame, *features: str) -> bool:
    """True when every feature the rule needs is modeled (not rare on Phoenix)."""
    return all(feature in z_values.columns for feature in features)


def movable_bridge(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    ids = _novel_ids(hexes, "movable_bridge_count")
    if not ids:
        return None
    return _card("movable_bridge", TITLES["movable_bridge"],
                 [f"movable_bridge_count novel in {len(ids)} hexes"],
                 f"{len(ids)} hexes contain a movable bridge, which Phoenix has too few of to model.",
                 ids, NOVEL_Z_EQUIVALENT)


def rain_dense_intersection(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if not _modeled(z_values, "intersection_density"):
        return None
    reference = summary["climate"]["reference"]["rain_days_per_year"]
    target = summary["climate"]["target"]["rain_days_per_year"]
    mask = z_values["intersection_density"] > 2
    ids = _ids(features, mask)
    # "Much rainier" = target >= 2x reference (contract 4.7). A zero reference
    # would make that trivially true for a bone-dry city and render the ratio as
    # "inf", so compare on absolute rain days instead.
    much_rainier = target >= 2 * reference if reference > 0 else target > 0
    if not much_rainier or not ids:
        return None
    if reference > 0:
        rain_trigger = f"rain_days_per_year {target / reference:.1f}x reference"
        rain_phrase = f"has {target / reference:.1f}x Phoenix's rain days"
    else:
        rain_trigger = f"rain_days_per_year {target:.1f} vs reference 0.0"
        rain_phrase = f"has {target:.1f} rain days a year against Phoenix's none"
    return _card("rain_dense_intersection", TITLES["rain_dense_intersection"],
                 [rain_trigger, f"intersection_density z > 2 in {len(ids)} hexes"],
                 f"{city['name']} {rain_phrase}. {len(ids)} hexes have intersection density above z = 2.",
                 ids, _mean_abs(z_values, "intersection_density", mask))


def crosswalk_wide_arterial(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if not _modeled(z_values, "crosswalk_density", "arterial_share"):
        return None
    mask = (z_values["crosswalk_density"] > 2) & (z_values["arterial_share"] > 1)
    ids = _ids(features, mask)
    if not ids:
        return None
    crosswalk_z = _mean_abs(z_values, "crosswalk_density", mask)
    arterial_z = _mean_abs(z_values, "arterial_share", mask)
    return _card("crosswalk_wide_arterial", TITLES["crosswalk_wide_arterial"],
                 [f"crosswalk_density z > 2 in {len(ids)} hexes (mean z {crosswalk_z:.1f})",
                  f"arterial_share z > 1 in the same hexes (mean z {arterial_z:.1f})"],
                 f"{len(ids)} hexes combine dense crosswalks with wide arterial roads.",
                 ids, float(np.mean([crosswalk_z, arterial_z])))


def cyclist_complex_intersection(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if not _modeled(z_values, "bike_lane_density", "intersection_density"):
        return None
    mask = (z_values["bike_lane_density"] > 2) & (z_values["intersection_density"] > 2)
    ids = _ids(features, mask)
    if not ids:
        return None
    bike_z = _mean_abs(z_values, "bike_lane_density", mask)
    return _card("cyclist_complex_intersection", TITLES["cyclist_complex_intersection"],
                 [f"bike_lane_density z > 2 in {len(ids)} hexes (mean z {bike_z:.1f})",
                  f"intersection_density z > 2 in the same hexes (mean z {_mean_abs(z_values, 'intersection_density', mask):.1f})"],
                 f"{len(ids)} hexes combine dense bike lanes and complex intersections.",
                 ids, bike_z)


def late_night_pedestrians(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if not _modeled(z_values, "nightlife_density"):
        return None
    mask = z_values["nightlife_density"] > 2
    ids = _ids(features, mask)
    if not ids:
        return None
    nightlife_z = _mean_abs(z_values, "nightlife_density", mask)
    return _card("late_night_pedestrians", TITLES["late_night_pedestrians"],
                 [f"nightlife_density z > 2 in {len(ids)} hexes (mean z {nightlife_z:.1f})"],
                 f"{len(ids)} hexes have nightlife density above z = 2.",
                 ids, nightlife_z)


def stadium_event(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    mask = features["stadium_count"] > 0
    ids = _ids(features, mask)
    if not ids:
        return None
    return _card("stadium_event", TITLES["stadium_event"],
                 [f"stadium_count > 0 in {len(ids)} hexes"],
                 f"{len(ids)} hexes contain a stadium.",
                 ids, NOVEL_Z_EQUIVALENT)


def bus_in_lane(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if not _modeled(z_values, "transit_stop_density"):
        return None
    mask = z_values["transit_stop_density"] > 2
    ids = _ids(features, mask)
    if not ids:
        return None
    transit_z = _mean_abs(z_values, "transit_stop_density", mask)
    return _card("bus_in_lane", TITLES["bus_in_lane"],
                 [f"transit_stop_density z > 2 in {len(ids)} hexes (mean z {transit_z:.1f})"],
                 f"{len(ids)} hexes have transit stop density above z = 2.",
                 ids, transit_z)


def snow_traction(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if "snow" not in summary["novel_city"]:
        return None
    target = summary["climate"]["target"]["snow_days_per_year"]
    reference = summary["climate"]["reference"]["snow_days_per_year"]
    return _card("snow_traction", TITLES["snow_traction"],
                 [f"snow_days_per_year {target:.1f} vs reference {reference:.1f}",
                  "snow in novel_city"],
                 f"{city['name']} has {target:.1f} snow days per year versus Phoenix's {reference:.1f}.",
                 [], NOVEL_Z_EQUIVALENT, "city", n_affected=int(summary["n_hexes"]))


def left_hand_traffic(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if "left_hand_traffic" not in summary["novel_city"]:
        return None
    return _card("left_hand_traffic", TITLES["left_hand_traffic"],
                 ["driving_side left vs reference right", "left_hand_traffic in novel_city"],
                 f"{city['name']} drives on the left, unlike Phoenix's right-hand traffic.",
                 [], NOVEL_Z_EQUIVALENT, "city", n_affected=int(summary["n_hexes"]))


def roundabout_or_tunnel(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    ids = _novel_ids(hexes, "roundabout_count", "tunnel_count")
    if not ids:
        return None
    return _card("roundabout_or_tunnel", TITLES["roundabout_or_tunnel"],
                 [f"roundabout_count or tunnel_count novel in {len(ids)} hexes"],
                 f"{len(ids)} hexes contain a roundabout or tunnel, which Phoenix has too few of to model.",
                 ids, NOVEL_Z_EQUIVALENT)


def build_scenarios(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict) -> list[dict]:
    z_values = z_matrix(features)
    rules = (movable_bridge, rain_dense_intersection, crosswalk_wide_arterial, cyclist_complex_intersection,
             late_night_pedestrians, stadium_event, bus_in_lane, snow_traction, left_hand_traffic, roundabout_or_tunnel)
    cards = [card for rule in rules if (card := rule(features, city, hexes, summary, z_values)) is not None]
    return sorted(cards, key=lambda card: card["priority"], reverse=True)
