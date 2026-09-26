"""Deterministic scenario cards derived from feature and climate rules."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas import NOVEL_Z_EQUIVALENT, REFERENCE_LABEL
from .reference import cached_reference, reference_climate
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
    "steep_grade": "Steep grade with a limited sight line over the crest",
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
    be common enough on the reference to be modeled instead of flagged.
    """
    wanted = set(names)
    return [str(item["h3"]) for item in hexes if wanted.intersection(item.get("novel", ()))]


def _mean_abs(z_values: pd.DataFrame, feature: str, mask: pd.Series) -> float:
    return float(z_values.loc[mask, feature].abs().mean())


def _modeled(z_values: pd.DataFrame, *features: str) -> bool:
    """True when every feature the rule needs is modeled (not rare on the reference)."""
    return all(feature in z_values.columns for feature in features)


def movable_bridge(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    ids = _novel_ids(hexes, "movable_bridge_count")
    if not ids:
        return None
    return _card("movable_bridge", TITLES["movable_bridge"],
                 [f"movable_bridge_count novel in {len(ids)} hexes"],
                 f"{len(ids)} hexes contain a movable bridge, which {REFERENCE_LABEL} have too few of to model.",
                 ids, NOVEL_Z_EQUIVALENT)


def rain_dense_intersection(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if not _modeled(z_values, "intersection_density"):
        return None
    # summary.climate.reference holds the per-metric max over the reference cities.
    reference = summary["climate"]["reference"]["rain_days_per_year"]
    target = summary["climate"]["target"]["rain_days_per_year"]
    mask = z_values["intersection_density"] > 2
    ids = _ids(features, mask)
    # CR-010: "much rainier" = wetter than the wettest reference city (replaces
    # 2x Phoenix). Absolute days, so a zero reference never divides.
    if not target > reference or not ids:
        return None
    wettest = reference_climate(cached_reference())[1]["rain_days_per_year"].split(",")[0]
    return _card("rain_dense_intersection", TITLES["rain_dense_intersection"],
                 [f"rain_days_per_year {target:.1f} vs max reference {reference:.1f} ({wettest})",
                  f"intersection_density z > 2 in {len(ids)} hexes"],
                 f"{city['name']} has {target:.1f} rain days a year, more than any of {REFERENCE_LABEL} "
                 f"(wettest: {wettest}, {reference:.1f}). {len(ids)} hexes have intersection density above z = 2.",
                 ids, _mean_abs(z_values, "intersection_density", mask))


def crosswalk_wide_arterial(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    """Dense crosswalks on wide arterials (CR-008: crosswalk bar lowered to z > 1).

    The original z > 2 could not fire. Phoenix counts every `highway=crossing`
    including `crossing=unmarked` (CR-001, a bulk sidewalk import), so the
    reference crosswalk distribution is inflated and z > 2 worked out to a grade
    of raw density no hex in any cached city reached. z > 1 restores the rule
    while leaving the reference cities quiet.
    """
    if not _modeled(z_values, "crosswalk_density", "arterial_share"):
        return None
    mask = (z_values["crosswalk_density"] > 1) & (z_values["arterial_share"] > 1)
    ids = _ids(features, mask)
    if not ids:
        return None
    crosswalk_z = _mean_abs(z_values, "crosswalk_density", mask)
    arterial_z = _mean_abs(z_values, "arterial_share", mask)
    return _card("crosswalk_wide_arterial", TITLES["crosswalk_wide_arterial"],
                 [f"crosswalk_density z > 1 in {len(ids)} hexes (mean z {crosswalk_z:.1f})",
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
                 [f"snow_days_per_year {target:.1f} vs max reference {reference:.1f}",
                  "snow in novel_city"],
                 f"{city['name']} has {target:.1f} snow days per year versus at most {reference:.1f} "
                 f"in {REFERENCE_LABEL}.",
                 [], NOVEL_Z_EQUIVALENT, "city", n_affected=int(summary["n_hexes"]))


def left_hand_traffic(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    if "left_hand_traffic" not in summary["novel_city"]:
        return None
    return _card("left_hand_traffic", TITLES["left_hand_traffic"],
                 ["driving_side left vs reference right", "left_hand_traffic in novel_city"],
                 f"{city['name']} drives on the left; {REFERENCE_LABEL} all drive on the right.",
                 [], NOVEL_Z_EQUIVALENT, "city", n_affected=int(summary["n_hexes"]))


def roundabout_or_tunnel(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    """Hexes with an unusual roundabout or tunnel concentration (CR-005).

    Contract 4.7 originally keyed this on novel[], but novel only ever holds
    features that are rare on the reference, and roundabouts and tunnels sit in
    7.0% and 5.7% of real Phoenix hexes -- far above RARE_PRESENCE_THRESHOLD. They
    are therefore always modeled, never novel, and the card could never be
    produced on real data. CR-005 (all three agreed) moves the trigger onto the
    modeled z values instead, which also prices the card on the real z magnitude
    rather than the flat NOVEL_Z_EQUIVALENT.

    The trigger is an OR, so a reference where only one of the two turns out to be
    rare still fires on the other rather than going silent.
    """
    present = [name for name in ("roundabout_count", "tunnel_count") if _modeled(z_values, name)]
    if not present:
        return None
    # z of whichever of the two triggered this hex, which is what contract 4.7
    # means by "mean |z| of the triggering feature over affected hexes".
    triggering_z = z_values.loc[:, present].max(axis=1)
    mask = triggering_z > 2
    ids = _ids(features, mask)
    if not ids:
        return None
    triggers = [f"{name} z > 2 in {int((z_values[name] > 2).sum())} hexes"
                for name in present if bool((z_values[name] > 2).any())]
    return _card("roundabout_or_tunnel", TITLES["roundabout_or_tunnel"],
                 triggers,
                 f"{len(ids)} hexes have a roundabout or tunnel concentration above z = 2.",
                 ids, float(triggering_z[mask].abs().mean()))


def steep_grade(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict, z_values: pd.DataFrame) -> dict | None:
    """Hexes whose grade is unusual against the reference pool (CR-011).

    Guarded on the feature being modeled: a reference pool with no elevation
    coverage makes terrain_slope_pct rare, and the rule then goes quiet rather
    than raising on a missing z column.
    """
    if not _modeled(z_values, "terrain_slope_pct"):
        return None
    mask = z_values["terrain_slope_pct"] > 2
    ids = _ids(features, mask)
    if not ids:
        return None
    slope_z = _mean_abs(z_values, "terrain_slope_pct", mask)
    # The raw percent grade of the steepest triggering hex. z alone is unitless,
    # and "z > 2" reads very differently at 3% than at 15%, so the card carries
    # the real number a reader can judge.
    steepest = float(pd.to_numeric(features.loc[mask, "terrain_slope_pct"], errors="coerce").max())
    return _card("steep_grade", TITLES["steep_grade"],
                 [f"terrain_slope_pct z > 2 in {len(ids)} hexes (max {steepest:.1f}%)"],
                 f"{len(ids)} hexes have a grade above z = 2 against {REFERENCE_LABEL}, "
                 f"the steepest at {steepest:.1f}%.",
                 ids, slope_z)


def build_scenarios(features: pd.DataFrame, city: dict, hexes: list[dict], summary: dict) -> list[dict]:
    z_values = z_matrix(features)
    rules = (movable_bridge, rain_dense_intersection, crosswalk_wide_arterial, cyclist_complex_intersection,
             late_night_pedestrians, stadium_event, bus_in_lane, snow_traction, left_hand_traffic, roundabout_or_tunnel,
             steep_grade)
    cards = [card for rule in rules if (card := rule(features, city, hexes, summary, z_values)) is not None]
    return sorted(cards, key=lambda card: card["priority"], reverse=True)
