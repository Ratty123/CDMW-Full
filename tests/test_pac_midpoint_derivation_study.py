from __future__ import annotations

import numpy as np
import pytest

from tools import pac_midpoint_derivation_study as study


# ── Codec round trips ────────────────────────────────────────────────

@pytest.mark.parametrize("value", [-1.0, -0.5, 0.0, 0.25, 0.75, 1.0])
def test_the_ten_bit_component_round_trips_within_one_step(value: float) -> None:
    raw = study.encode_component_10(np.asarray([value]))
    decoded = raw.astype(np.float64) * (2.0 / 1023.0) - 1.0
    assert abs(float(decoded[0]) - value) <= study.COMPONENT_STEP


def test_the_ten_bit_component_stays_in_range() -> None:
    raw = study.encode_component_10(np.asarray([-4.0, 4.0]))
    assert raw.min() >= 0
    assert raw.max() <= 1023


def test_the_tangent_lane_carries_the_magnitude_and_the_z_sign_together() -> None:
    positive = study.encode_tangent_lane(np.asarray([0.0]), np.asarray([0.5]))
    negative = study.encode_tangent_lane(np.asarray([0.0]), np.asarray([-0.5]))
    assert positive[0] > 0
    assert negative[0] == -positive[0]


def test_a_zero_z_encodes_as_non_negative_which_is_the_codec_degenerate_case() -> None:
    assert study.encode_tangent_lane(np.asarray([0.5]), np.asarray([0.0]))[0] > 0


def test_the_tangent_lane_round_trips_within_one_step() -> None:
    for x in (-1.0, -0.25, 0.0, 0.5, 1.0):
        raw = study.encode_tangent_lane(np.asarray([x]), np.asarray([1.0]))
        decoded = abs(float(raw[0]) / 32767.0) * 2.0 - 1.0
        assert abs(decoded - x) <= study.TANGENT_LANE_STEP


# ── Interpolation helpers ────────────────────────────────────────────

def test_slerp_at_the_endpoints_returns_the_endpoints() -> None:
    left = np.asarray([[1.0, 0.0, 0.0]])
    right = np.asarray([[0.0, 1.0, 0.0]])
    assert study._slerp(left, right, np.asarray([0.0]))[0] == pytest.approx(left[0], abs=1e-9)
    assert study._slerp(left, right, np.asarray([1.0]))[0] == pytest.approx(right[0], abs=1e-9)


def test_slerp_halfway_bisects_the_angle() -> None:
    left = np.asarray([[1.0, 0.0, 0.0]])
    right = np.asarray([[0.0, 1.0, 0.0]])
    middle = study._slerp(left, right, np.asarray([0.5]))[0]
    assert middle == pytest.approx([2 ** -0.5, 2 ** -0.5, 0.0], abs=1e-9)


def test_slerp_survives_identical_inputs_without_dividing_by_zero() -> None:
    same = np.asarray([[0.0, 0.0, 1.0]])
    result = study._slerp(same, same.copy(), np.asarray([0.5]))
    assert np.isfinite(result).all()
    assert result[0] == pytest.approx([0.0, 0.0, 1.0])


def test_orthogonalising_removes_the_normal_component() -> None:
    normal = np.asarray([[0.0, 0.0, 1.0]])
    vector = np.asarray([[1.0, 0.0, 0.7]])
    result = study._orthogonalise(vector, normal)
    assert float(np.dot(result[0], normal[0])) == pytest.approx(0.0, abs=1e-12)
    assert float(np.linalg.norm(result[0])) == pytest.approx(1.0)


# ── Rules are pre-registered, with controls ──────────────────────────

def test_every_rule_is_declared_up_front_and_controls_are_marked() -> None:
    names = [rule.name for rule in study.RULES]
    assert len(names) == len(set(names))
    controls = [rule.name for rule in study.RULES if rule.control]
    # Without a control, "close" cannot be distinguished from "closer than
    # copying a parent", which is the whole point of the exercise.
    assert "copy_nearest_parent" in controls
    assert len(controls) >= 1
    assert any(not rule.control for rule in study.RULES)


def _inputs(t: float) -> study.RuleInputs:
    left_normal = np.asarray([[0.0, 0.0, 1.0]])
    right_normal = np.asarray([[0.0, 0.2, 1.0]]) / np.linalg.norm([0.0, 0.2, 1.0])
    return study.RuleInputs(
        normal_left=left_normal,
        normal_right=right_normal,
        stored_left=np.asarray([[1.0, 0.0, 0.0]]),
        stored_right=np.asarray([[0.9, 0.1, 0.0]]) / np.linalg.norm([0.9, 0.1, 0.0]),
        handedness_left=np.asarray([1.0]),
        t=np.asarray([t]),
        recomputed_tangent=np.asarray([[0.0, 1.0, 0.0]]),
    )


@pytest.mark.parametrize("rule", study.RULES, ids=lambda rule: rule.name)
def test_every_rule_returns_unit_vectors(rule: study.Rule) -> None:
    normal, stored = rule.predict(_inputs(0.5))
    assert float(np.linalg.norm(normal[0])) == pytest.approx(1.0, abs=1e-9)
    assert float(np.linalg.norm(stored[0])) == pytest.approx(1.0, abs=1e-9)


def test_copying_the_nearest_parent_switches_at_the_halfway_point() -> None:
    rule = next(r for r in study.RULES if r.name == "copy_nearest_parent")
    near_left, _s = rule.predict(_inputs(0.2))
    near_right, _s2 = rule.predict(_inputs(0.8))
    assert near_left[0] == pytest.approx([0.0, 0.0, 1.0])
    assert near_right[0] != pytest.approx([0.0, 0.0, 1.0])


def test_the_orthogonalising_rule_produces_a_tangent_perpendicular_to_its_normal() -> None:
    rule = next(r for r in study.RULES if r.name == "lerp_decoded")
    normal, stored = rule.predict(_inputs(0.5))
    assert float(np.dot(normal[0], stored[0])) == pytest.approx(0.0, abs=1e-9)


def test_the_non_orthogonalising_rule_is_allowed_to_drift() -> None:
    # It exists precisely to show whether the orthogonalise step earns its place,
    # so it must not quietly do the same thing.
    plain = next(r for r in study.RULES if r.name == "lerp_no_orthogonalise")
    _n, stored = plain.predict(_inputs(0.5))
    normal, _s = plain.predict(_inputs(0.5))
    assert abs(float(np.dot(normal[0], stored[0]))) > 1e-9


def test_the_geometry_rule_uses_the_handedness_it_was_given() -> None:
    rule = next(r for r in study.RULES if r.name == "recompute_from_geometry")
    inputs = _inputs(0.5)
    _n, positive = rule.predict(inputs)
    inputs.handedness_left = np.asarray([-1.0])
    _n2, negative = rule.predict(inputs)
    assert positive[0] == pytest.approx(-negative[0], abs=1e-9)


# ── Encoded-error comparison ─────────────────────────────────────────

def _record_with(normal_xy: tuple[float, float], tangent_y: float, lane: int) -> np.ndarray:
    import struct

    record = bytearray(40)
    packed = (
        study.encode_component_10(np.asarray([tangent_y]))[0]
        | (study.encode_component_10(np.asarray([normal_xy[0]]))[0] << 10)
        | (study.encode_component_10(np.asarray([normal_xy[1]]))[0] << 20)
    )
    struct.pack_into("<I", record, 16, int(packed))
    struct.pack_into("<h", record, 6, lane)
    return np.frombuffer(bytes(record), dtype=np.uint8).reshape(1, 40)


def test_a_perfect_prediction_reports_exact_bytes() -> None:
    records = _record_with((0.25, -0.5), 0.75, 12345)
    normal = np.asarray([[0.25, -0.5, 0.0]])
    stored = np.asarray([[abs(12345 / 32767.0) * 2.0 - 1.0, 0.75, 1.0]])
    result = study._encoded_errors(normal, stored, records, np.asarray([0]))
    assert result["all_lanes_exact_percent"] == pytest.approx(100.0)
    assert result["normal_within_1_step_percent"] == pytest.approx(100.0)


def test_a_wrong_prediction_does_not_report_exact_bytes() -> None:
    records = _record_with((0.25, -0.5), 0.75, 12345)
    normal = np.asarray([[-0.9, 0.9, 0.0]])
    stored = np.asarray([[0.0, -0.9, 1.0]])
    result = study._encoded_errors(normal, stored, records, np.asarray([0]))
    assert result["all_lanes_exact_percent"] == pytest.approx(0.0)
    assert result["normal_within_1_step_percent"] == pytest.approx(0.0)


def test_the_lane_sign_comparison_notices_a_flipped_z() -> None:
    records = _record_with((0.0, 0.0), 0.0, 12345)
    stored_positive = np.asarray([[abs(12345 / 32767.0) * 2.0 - 1.0, 0.0, 1.0]])
    stored_negative = np.asarray([[abs(12345 / 32767.0) * 2.0 - 1.0, 0.0, -1.0]])
    normal = np.asarray([[0.0, 0.0, 1.0]])
    assert study._encoded_errors(normal, stored_positive, records, np.asarray([0]))[
        "tangent_lane_sign_matches_percent"
    ] == pytest.approx(100.0)
    assert study._encoded_errors(normal, stored_negative, records, np.asarray([0]))[
        "tangent_lane_sign_matches_percent"
    ] == pytest.approx(0.0)
