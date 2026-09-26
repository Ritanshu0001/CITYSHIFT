"""Contract tests for the P2 model path.

Runs under pytest, or standalone with `python tests/test_model.py` so the checks
are available before pytest is installed. The reference is fitted in-process
from the committed fixtures, so these tests never depend on a saved artifact.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import h3
import pandas as pd

import app.model.reference as reference
from app.model.scenarios import build_scenarios
from app.model.scoring import score_city, z_matrix
from app.model.summary import build_summary
from app.schemas import BAND_RED, BAND_YELLOW, CityResult, HEX_FEATURES, TOP_FEATURES_N

FIXTURES = BACKEND / "tests" / "fixtures"


def _fixtures() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    phoenix = pd.read_csv(FIXTURES / "fake_phoenix_features.csv")
    target = pd.read_csv(FIXTURES / "fake_target_features.csv")
    city = json.loads((FIXTURES / "fake_city.json").read_text(encoding="utf-8"))
    return phoenix, target, city


def _use_fixture_reference(phoenix: pd.DataFrame, city: dict) -> None:
    """Point the module-level cache at a reference fitted from the fixtures."""
    reference.reset_reference_cache()
    reference._CACHE = reference.fit_reference(phoenix, city)


def _target_city(city: dict, **overrides) -> dict:
    target_city = dict(city)
    target_city.update(name="Faketown, XX", slug="faketown-xx")
    target_city.update(overrides)
    return target_city


def _full_result(features: pd.DataFrame, city: dict) -> dict:
    hexes = score_city(features, city)
    summary = build_summary(features, city, hexes)
    return {"hexes": hexes, "summary": summary,
            "scenarios": build_scenarios(features, city, hexes, summary)}


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def test_reference_self_score_is_about_five_percent_red():
    """Contract 4.6: Phoenix scored against itself lands at about 5% red."""
    phoenix, _, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    summary = build_summary(phoenix, city, score_city(phoenix, city))
    assert 3.0 <= summary["pct_red"] <= 8.0, summary["pct_red"]


def test_hex_shape_matches_contract():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    modeled = reference.cached_reference()["feature_order"]
    hexes = score_city(target, _target_city(city))
    assert len(hexes) == len(target)
    for item in hexes:
        assert set(item) == {"h3", "shift_score", "band", "top_features", "novel"}
        assert h3.is_valid_cell(item["h3"])
        assert 0.0 <= item["shift_score"] <= 100.0
        assert item["shift_score"] == round(item["shift_score"], 1)
        expected = "red" if item["shift_score"] >= BAND_RED else (
            "yellow" if item["shift_score"] >= BAND_YELLOW else "green")
        assert item["band"] == expected
        assert len(item["top_features"]) == min(TOP_FEATURES_N, len(modeled))
        magnitudes = [abs(f["z"]) for f in item["top_features"]]
        assert magnitudes == sorted(magnitudes, reverse=True)
        for feature in item["top_features"]:
            assert feature["name"] in modeled  # never a rare feature
            assert feature["z"] == round(feature["z"], 2)
            assert feature["pct"] == round(feature["pct"], 1)


def test_top_features_report_the_reference_median_and_percentile():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    raw = reference.cached_reference()["phoenix_raw"]
    hexes = score_city(target, _target_city(city))
    for item in hexes[:20]:
        for feature in item["top_features"]:
            column = raw[feature["name"]]
            assert feature["ref_median"] == round(float(column.median()), 2)
            assert feature["pct"] == round(float((column <= feature["value"]).mean() * 100), 1)


def test_missing_and_invalid_values_never_reach_the_output():
    """A blank, infinite or negative cell must not produce a NaN in result.json."""
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    dirty = target.copy()
    dirty.loc[3, "signal_density"] = float("nan")
    dirty.loc[4, "crosswalk_density"] = float("inf")
    dirty.loc[5, "arterial_share"] = -1.0
    result = _full_result(dirty, _target_city(city))
    payload = json.dumps(result)
    assert "NaN" not in payload and "Infinity" not in payload
    for item in result["hexes"]:
        for feature in item["top_features"]:
            assert all(math.isfinite(feature[key]) for key in ("value", "ref_median", "z", "pct"))
    CityResult.model_validate(result)


def test_empty_feature_table_produces_an_empty_result():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    result = _full_result(target.iloc[0:0], _target_city(city))
    assert result["hexes"] == []
    assert result["scenarios"] == []
    assert result["summary"]["n_hexes"] == 0
    assert result["summary"]["pct_red"] == 0.0
    CityResult.model_validate(result)


def test_missing_reference_artifact_raises_file_not_found():
    """Contract 4.4: P1 catches this and the message reaches the UI."""
    reference.reset_reference_cache()
    try:
        reference.load_reference(FIXTURES / "no-such-reference")
    except FileNotFoundError as error:
        assert "fit_reference.py" in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------
def test_summary_shape_and_feature_comparison_order():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    target_city = _target_city(city, snow_days_per_year=11.0, driving_side="left")
    summary = build_summary(target, target_city, score_city(target, target_city))
    names = [row["name"] for row in summary["feature_comparison"]]
    assert names[:len(HEX_FEATURES)] == HEX_FEATURES
    assert names[len(HEX_FEATURES):] == ["avg_lanes"]  # both fixtures carry lane data
    assert summary["novel_city"] == ["snow", "left_hand_traffic"]
    assert summary["driving_side"] == "left"


def test_driving_side_is_coerced_to_the_contract_literals():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    for given, expected in (("left", "left"), ("LEFT", "left"), ("right", "right"),
                            ("unknown", "right"), ("", "right")):
        target_city = _target_city(city, driving_side=given)
        summary = build_summary(target, target_city, score_city(target, target_city))
        assert summary["driving_side"] == expected, given
        assert ("left_hand_traffic" in summary["novel_city"]) == (expected == "left")


def test_avg_lanes_row_is_omitted_when_the_target_has_none():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    without = target.drop(columns=["avg_lanes"])
    summary = build_summary(without, _target_city(city), score_city(without, _target_city(city)))
    assert [row["name"] for row in summary["feature_comparison"]] == HEX_FEATURES


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------
def test_city_scope_cards_are_priced_on_the_whole_city():
    """Contract 4.7: for scope="city", n_hexes_affected is n_hexes."""
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    target_city = _target_city(city, snow_days_per_year=11.0, driving_side="left")
    result = _full_result(target, target_city)
    city_cards = [card for card in result["scenarios"] if card["scope"] == "city"]
    assert {card["id"] for card in city_cards} == {"snow_traction", "left_hand_traffic"}
    for card in city_cards:
        assert card["hex_ids"] == []
        assert card["priority"] == round(3.0 * result["summary"]["n_hexes"], 1)


def test_scenarios_are_sorted_and_shaped_per_contract():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    target_city = _target_city(city, rain_days_per_year=120.4, snow_days_per_year=11.0, driving_side="left")
    cards = _full_result(target, target_city)["scenarios"]
    priorities = [card["priority"] for card in cards]
    assert priorities == sorted(priorities, reverse=True)
    for card in cards:
        assert card["triggered_by"], card["id"]
        assert all(trigger and ";" not in trigger for trigger in card["triggered_by"])
        assert (card["scope"] == "hex") == bool(card["hex_ids"])
        assert card["priority"] > 0


def test_infrastructure_cards_follow_the_novel_flags():
    """Contract 4.7 phrases these rules as "movable_bridge_count in novel"."""
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    result = _full_result(target, _target_city(city))
    flagged = {item["h3"] for item in result["hexes"] if "movable_bridge_count" in item["novel"]}
    card = next(c for c in result["scenarios"] if c["id"] == "movable_bridge")
    assert set(card["hex_ids"]) == flagged and flagged


def test_rules_are_skipped_when_their_feature_is_rare_on_the_reference():
    """A rare feature has no z column; the rule must go quiet, not raise."""
    phoenix, target, city = _fixtures()
    quiet = phoenix.copy()
    quiet["nightlife_density"] = 0.0
    quiet["transit_stop_density"] = 0.0
    _use_fixture_reference(quiet, city)
    assert "nightlife_density" in reference.cached_reference()["rare_features"]
    ids = {card["id"] for card in _full_result(target, _target_city(city))["scenarios"]}
    assert "late_night_pedestrians" not in ids
    assert "bus_in_lane" not in ids


def test_rain_rule_needs_a_genuinely_rainier_city():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    dry = _target_city(city, rain_days_per_year=33.0)
    assert not [c for c in _full_result(target, dry)["scenarios"] if c["id"] == "rain_dense_intersection"]
    wet = _target_city(city, rain_days_per_year=120.4)
    card = next(c for c in _full_result(target, wet)["scenarios"] if c["id"] == "rain_dense_intersection")
    assert "3.6x reference" in card["triggered_by"][0]


def test_rain_rule_does_not_divide_by_a_zero_reference():
    phoenix, target, city = _fixtures()
    no_rain_reference = dict(city, rain_days_per_year=0.0)
    _use_fixture_reference(phoenix, no_rain_reference)
    # A bone-dry target must not qualify just because 2 x 0 == 0.
    assert not [c for c in _full_result(target, _target_city(no_rain_reference, rain_days_per_year=0.0))["scenarios"]
                if c["id"] == "rain_dense_intersection"]
    card = next(c for c in _full_result(target, _target_city(no_rain_reference, rain_days_per_year=40.0))["scenarios"]
                if c["id"] == "rain_dense_intersection")
    assert "inf" not in json.dumps(card)


# --------------------------------------------------------------------------
# Reference artifact
# --------------------------------------------------------------------------
def test_artifact_holds_every_key_the_contract_lists():
    phoenix, _, city = _fixtures()
    artifact = reference.fit_reference(phoenix, city)
    assert {"feature_order", "rare_features", "scaler", "iforest", "phoenix_scores_sorted",
            "phoenix_log_mean", "phoenix_log_std", "phoenix_raw", "phoenix_city"} <= set(artifact)
    assert set(artifact["feature_order"]) | set(artifact["rare_features"]) == set(HEX_FEATURES)
    assert not set(artifact["feature_order"]) & set(artifact["rare_features"])


def test_fit_is_reproducible():
    phoenix, target, city = _fixtures()
    first = reference.fit_reference(phoenix, city)
    second = reference.fit_reference(phoenix, city)
    assert (first["phoenix_scores_sorted"] == second["phoenix_scores_sorted"]).all()
    reference._CACHE = first
    one = score_city(target, _target_city(city))
    reference._CACHE = second
    assert one == score_city(target, _target_city(city))


def test_reference_is_loaded_once_per_process():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    artifact = reference.cached_reference()
    target_city = _target_city(city)
    hexes = score_city(target, target_city)
    build_summary(target, target_city, hexes)
    z_matrix(target)
    assert reference.cached_reference() is artifact


def test_z_matrix_covers_only_modeled_features():
    phoenix, target, city = _fixtures()
    _use_fixture_reference(phoenix, city)
    artifact = reference.cached_reference()
    matrix = z_matrix(target)
    assert list(matrix.columns) == artifact["feature_order"]
    assert len(matrix) == len(target)
    assert matrix.to_numpy().std() > 0


if __name__ == "__main__":
    failures = 0
    for name, test in sorted(globals().items()):
        if not name.startswith("test_") or not callable(test):
            continue
        try:
            test()
            print(f"PASS {name}")
        except Exception as error:  # noqa: BLE001 - standalone runner reports and continues
            failures += 1
            print(f"FAIL {name}: {type(error).__name__}: {error}")
    print(f"\n{failures} failure(s)")
    raise SystemExit(1 if failures else 0)
