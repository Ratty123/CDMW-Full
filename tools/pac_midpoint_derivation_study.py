"""Phase 4 of the PAC vertex channel study: leave-one-out against real vertices.

Read-only, and it writes no PAC. Phase 2 established what the protected lanes
mean by reading the game's own shaders. Knowing what a byte means is not the same
as knowing what to put there for a vertex that did not exist before, and this is
the phase that decides whether such a rule exists.

The test is the plan's: find real vertices that already sit where a split would
have put one, hide their protected lanes, predict those lanes from the two
neighbours, and compare. A rule passes only when its residual is explained by the
codec's own quantisation, not merely when it looks close.

Fixtures are ``A - M - B`` triples where ``M`` neighbours both ``A`` and ``B``,
``A - B`` is not itself an edge, ``M`` lies on the segment at some parameter
``t``, and UV0 independently agrees on that same ``t``. Requiring UV0 to confirm
the parameter that position implies is what makes a fixture a split rather than
a coincidence, and it is why fixtures are scarce: on this corpus about one
vertex in two hundred qualifies.

Every rule below is declared in ``RULES`` before any of them is run, so that
picking the winner afterwards is not mistaken for a discovery. The controls are
part of that declaration: a rule that cannot beat "copy whichever parent is
nearer" has not earned anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "tools"))

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.mesh_pac_topology_builder import (
    PROVEN_PAC_STRIDE,
    _original_records,
    _submesh_is_proven_layout,
    _submesh_is_skinned,
)
from pac_parser_corpus_harness import discover_pac_entries
from pac_shader_consumer_study import decode_record_tbn

REPORT_FORMAT = "cdmw_pac_midpoint_derivation_v1"
STUDY_PHASE = "phase-4"
PLAN_PATH = "docs/plans/active/pac-vertex-channel-identification-v1.md"

#: One step of the 10-bit lanes, in the [-1, 1] domain they decode into.
COMPONENT_STEP = 2.0 / 1023.0
#: One step of the 15-bit magnitude in bytes 6-7, same domain.
TANGENT_LANE_STEP = 2.0 / 32767.0


# ── Codec ────────────────────────────────────────────────────────────

def encode_component_10(value: np.ndarray) -> np.ndarray:
    """Inverse of ``raw * 2/1023 - 1``, rounded to the nearest representable."""
    return np.clip(np.rint((np.asarray(value) + 1.0) * 1023.0 / 2.0), 0, 1023).astype(np.int64)


def encode_tangent_lane(x: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Bytes 6-7: the x magnitude, signed by the z component.

    The lane carries two things at once, which is why they cannot be owned
    separately: the magnitude is ``(x + 1) / 2`` over 15 bits and the sign is the
    sign of z. A z of exactly zero encodes as non-negative, which is the codec's
    own degenerate case rather than an error in the rule under test.
    """
    magnitude = np.clip(np.rint((np.asarray(x) + 1.0) / 2.0 * 32767.0), 0, 32767).astype(np.int64)
    return np.where(np.asarray(z) < 0.0, -magnitude, magnitude)


def _normalise(vectors: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.divide(vectors, np.where(lengths > 1e-12, lengths, 1.0))


def _orthogonalise(vectors: np.ndarray, against: np.ndarray) -> np.ndarray:
    return _normalise(vectors - against * np.sum(against * vectors, axis=-1, keepdims=True))


def _slerp(left: np.ndarray, right: np.ndarray, t: np.ndarray) -> np.ndarray:
    dots = np.clip(np.sum(left * right, axis=-1), -1.0, 1.0)
    omega = np.arccos(dots)
    sin_omega = np.sin(omega)
    near = sin_omega < 1e-6
    factor_left = np.where(near, 1.0 - t, np.sin((1.0 - t) * omega) / np.where(near, 1.0, sin_omega))
    factor_right = np.where(near, t, np.sin(t * omega) / np.where(near, 1.0, sin_omega))
    return _normalise(factor_left[:, None] * left + factor_right[:, None] * right)


# ── Fixtures ─────────────────────────────────────────────────────────

@dataclass
class Fixture:
    """One ``A - M - B`` triple that a split would have produced."""

    asset: str
    submesh_index: int
    mid: int
    left: int
    right: int
    t: float
    position_residual: float
    uv_residual: float
    normal_agreement: float
    handedness_agree: bool


@dataclass
class SubmeshFixtures:
    asset: str
    submesh_index: int
    records: np.ndarray
    normal: np.ndarray
    stored: np.ndarray
    handedness: np.ndarray
    positions: np.ndarray
    uvs: np.ndarray
    faces: list[tuple[int, int, int]]
    fixtures: list[Fixture] = field(default_factory=list)


def _find_fixtures(
    data: SubmeshFixtures,
    *,
    min_edge_units: float,
    collinear_tolerance: float,
    uv_tolerance: float,
    t_range: tuple[float, float],
) -> None:
    quantised = data.records[:, 0:6].copy().view(np.uint16).reshape(len(data.records), 3).astype(np.float64)
    adjacency: dict[int, set[int]] = defaultdict(set)
    edges: set[tuple[int, int]] = set()
    for a, b, c in data.faces:
        for left, right in ((a, b), (b, c), (c, a)):
            if left == right:
                continue
            adjacency[left].add(right)
            adjacency[right].add(left)
            edges.add((left, right) if left < right else (right, left))

    for mid, neighbours in adjacency.items():
        ordered = sorted(neighbours)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                if ((left, right) if left < right else (right, left)) in edges:
                    continue
                span = quantised[right] - quantised[left]
                length = float(np.linalg.norm(span))
                if length < min_edge_units:
                    continue
                t = float(np.dot(quantised[mid] - quantised[left], span) / (length * length))
                if not (t_range[0] < t < t_range[1]):
                    continue
                residual = float(np.linalg.norm(quantised[mid] - (quantised[left] + t * span)))
                if residual > collinear_tolerance * length:
                    continue
                uv_span = float(np.linalg.norm(data.uvs[right] - data.uvs[left]))
                if uv_span <= 1e-6:
                    continue
                uv_predicted = data.uvs[left] + t * (data.uvs[right] - data.uvs[left])
                uv_residual = float(np.linalg.norm(data.uvs[mid] - uv_predicted))
                if uv_residual > uv_tolerance * uv_span:
                    continue
                data.fixtures.append(
                    Fixture(
                        asset=data.asset,
                        submesh_index=data.submesh_index,
                        mid=mid,
                        left=left,
                        right=right,
                        t=t,
                        position_residual=residual / length,
                        uv_residual=uv_residual / uv_span,
                        normal_agreement=float(np.dot(data.normal[left], data.normal[right])),
                        handedness_agree=bool(data.handedness[left] == data.handedness[right]),
                    )
                )


# ── Pre-registered rules ─────────────────────────────────────────────

@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    control: bool
    predict: Callable[["RuleInputs"], tuple[np.ndarray, np.ndarray]]


@dataclass
class RuleInputs:
    """Everything a rule may look at. It may never look at the target vertex."""

    normal_left: np.ndarray
    normal_right: np.ndarray
    stored_left: np.ndarray
    stored_right: np.ndarray
    handedness_left: np.ndarray
    t: np.ndarray
    #: Tangent recomputed from post-edit geometry at the target, for the rule
    #: that regenerates rather than interpolates.
    recomputed_tangent: np.ndarray


def _rule_lerp(inputs: RuleInputs) -> tuple[np.ndarray, np.ndarray]:
    t = inputs.t[:, None]
    normal = _normalise(inputs.normal_left * (1.0 - t) + inputs.normal_right * t)
    stored = _normalise(inputs.stored_left * (1.0 - t) + inputs.stored_right * t)
    return normal, _orthogonalise(stored, normal)


def _rule_slerp(inputs: RuleInputs) -> tuple[np.ndarray, np.ndarray]:
    normal = _slerp(inputs.normal_left, inputs.normal_right, inputs.t)
    stored = _slerp(inputs.stored_left, inputs.stored_right, inputs.t)
    return normal, _orthogonalise(stored, normal)


def _rule_lerp_no_orthogonalise(inputs: RuleInputs) -> tuple[np.ndarray, np.ndarray]:
    t = inputs.t[:, None]
    normal = _normalise(inputs.normal_left * (1.0 - t) + inputs.normal_right * t)
    stored = _normalise(inputs.stored_left * (1.0 - t) + inputs.stored_right * t)
    return normal, stored


def _rule_recompute(inputs: RuleInputs) -> tuple[np.ndarray, np.ndarray]:
    t = inputs.t[:, None]
    normal = _normalise(inputs.normal_left * (1.0 - t) + inputs.normal_right * t)
    tangent = _orthogonalise(inputs.recomputed_tangent, normal)
    stored = _normalise(np.cross(normal, tangent) * inputs.handedness_left[:, None])
    return normal, stored


def _rule_copy_nearest(inputs: RuleInputs) -> tuple[np.ndarray, np.ndarray]:
    take_left = (inputs.t < 0.5)[:, None]
    normal = np.where(take_left, inputs.normal_left, inputs.normal_right)
    stored = np.where(take_left, inputs.stored_left, inputs.stored_right)
    return normal, stored


def _rule_copy_left(inputs: RuleInputs) -> tuple[np.ndarray, np.ndarray]:
    return inputs.normal_left, inputs.stored_left


RULES: tuple[Rule, ...] = (
    Rule(
        "lerp_decoded",
        "Decode both parents, linearly interpolate, renormalise, re-orthogonalise, re-encode.",
        False,
        _rule_lerp,
    ),
    Rule(
        "lerp_no_orthogonalise",
        "As above but without re-orthogonalising, to show whether that step earns its place.",
        False,
        _rule_lerp_no_orthogonalise,
    ),
    Rule("slerp_decoded", "Spherical interpolation of both vectors.", False, _rule_slerp),
    Rule(
        "recompute_from_geometry",
        "Regenerate the tangent from post-edit position and UV0, then cross with the interpolated normal.",
        False,
        _rule_recompute,
    ),
    Rule("copy_nearest_parent", "Copy whichever parent is nearer. Control.", True, _rule_copy_nearest),
    Rule("copy_left_parent", "Always copy the first parent. Control.", True, _rule_copy_left),
)


# ── Evaluation ───────────────────────────────────────────────────────

def _angles(predicted: np.ndarray, actual: np.ndarray) -> np.ndarray:
    return np.degrees(np.arccos(np.clip(np.sum(predicted * actual, axis=-1), -1.0, 1.0)))


#: Fixtures are stratified by how nearly the two parents' normals agree, which is
#: a proxy for how flat the patch is. This is the load-bearing analysis, not a
#: refinement: on a curved surface the true value at the midpoint is not the
#: interpolated value, so a residual that shrinks as the patch flattens is
#: curvature and a residual that does not is the rule being wrong. The normal is
#: carried through every stratum as a positive control, because its meaning is
#: already proven and it must behave.
FLATNESS_BINS: tuple[tuple[float, float, str], ...] = (
    (0.0, 0.90, "dot < 0.90"),
    (0.90, 0.99, "0.90 - 0.99"),
    (0.99, 0.999, "0.99 - 0.999"),
    (0.999, 0.9999, "0.999 - 0.9999"),
    (0.9999, 1.01, "> 0.9999"),
)


def _encoded_errors(
    predicted_normal: np.ndarray,
    predicted_stored: np.ndarray,
    records: np.ndarray,
    mid: np.ndarray,
) -> dict[str, object]:
    """Compare the rule's bytes against the bytes actually on disk."""
    packed = records[mid, 16:20].copy().view(np.uint32).reshape(-1).astype(np.int64)
    actual_normal_x = (packed >> 10) & 1023
    actual_normal_y = (packed >> 20) & 1023
    actual_tangent_y = packed & 1023
    actual_lane = records[mid, 6:8].copy().view(np.int16).reshape(-1).astype(np.int64)

    predicted_normal_x = encode_component_10(predicted_normal[:, 0])
    predicted_normal_y = encode_component_10(predicted_normal[:, 1])
    predicted_tangent_y = encode_component_10(predicted_stored[:, 1])
    predicted_lane = encode_tangent_lane(predicted_stored[:, 0], predicted_stored[:, 2])

    normal_steps = np.maximum(
        np.abs(predicted_normal_x - actual_normal_x), np.abs(predicted_normal_y - actual_normal_y)
    )
    tangent_y_steps = np.abs(predicted_tangent_y - actual_tangent_y)
    lane_steps = np.abs(predicted_lane - actual_lane)
    sign_matches = np.sign(predicted_lane) == np.sign(actual_lane)

    total = max(1, len(mid))
    return {
        "normal_within_1_step_percent": round(float((normal_steps <= 1).mean() * 100.0), 3),
        "normal_median_steps": float(np.median(normal_steps)),
        "tangent_y_within_1_step_percent": round(float((tangent_y_steps <= 1).mean() * 100.0), 3),
        "tangent_y_median_steps": float(np.median(tangent_y_steps)),
        "tangent_lane_median_steps": float(np.median(lane_steps)),
        "tangent_lane_sign_matches_percent": round(float(sign_matches.mean() * 100.0), 3),
        "all_lanes_exact_percent": round(
            float(
                (
                    (predicted_normal_x == actual_normal_x)
                    & (predicted_normal_y == actual_normal_y)
                    & (predicted_tangent_y == actual_tangent_y)
                    & (predicted_lane == actual_lane)
                ).sum()
                / total
                * 100.0
            ),
            3,
        ),
    }


def _recomputed_tangents(data: SubmeshFixtures) -> np.ndarray:
    """Per-vertex tangent from position and UV0, the standard accumulation."""
    count = len(data.records)
    tangent = np.zeros((count, 3), dtype=np.float64)
    for a, b, c in data.faces:
        edge1 = data.positions[b] - data.positions[a]
        edge2 = data.positions[c] - data.positions[a]
        du1, dv1 = data.uvs[b] - data.uvs[a]
        du2, dv2 = data.uvs[c] - data.uvs[a]
        determinant = du1 * dv2 - du2 * dv1
        if abs(determinant) < 1e-12:
            continue
        contribution = (edge1 * dv2 - edge2 * dv1) / determinant
        tangent[a] += contribution
        tangent[b] += contribution
        tangent[c] += contribution
    return _normalise(tangent)


def _load_submesh(entry, payload: bytes, submesh, index: int) -> SubmeshFixtures | None:
    if not _submesh_is_skinned(submesh) or not _submesh_is_proven_layout(submesh, skinned_required=True):
        return None
    try:
        records = _original_records(submesh, payload)
    except Exception:
        return None
    count = len(records)
    faces = [tuple(int(value) for value in face) for face in submesh.faces]
    if count < 128 or len(faces) < 128:
        return None
    matrix = np.frombuffer(b"".join(records), dtype=np.uint8).reshape(count, PROVEN_PAC_STRIDE)
    normal, stored, handedness = decode_record_tbn(matrix)
    bbox_min = np.asarray(submesh.source_bbox_min, dtype=np.float64)
    extent = np.asarray(submesh.source_bbox_extent, dtype=np.float64)
    raw = matrix[:, 0:6].copy().view(np.uint16).reshape(count, 3).astype(np.float64)
    return SubmeshFixtures(
        asset=str(entry.path).replace("\\", "/"),
        submesh_index=index,
        records=matrix,
        normal=normal,
        stored=stored,
        handedness=handedness,
        positions=bbox_min + (raw / 32767.0) * extent,
        uvs=matrix[:, 8:12].copy().view(np.float16).reshape(count, 2).astype(np.float64),
        faces=faces,
    )


def _skin_prediction(data: SubmeshFixtures, fixtures: Sequence[Fixture]) -> dict[str, object]:
    """Does the union of the parents' influences contain the child's?

    Phase 2 showed the record carries eight influences, six as 10-bit palette
    slots and two more as half-typed indices gated by byte 39. Those are
    categorical: a midpoint cannot interpolate a bone index, it can only inherit
    from its parents. So the question a derivation rule has to answer first is
    whether the child's bones are a subset of its parents' at all.
    """
    def live_slots(index: int) -> set[int]:
        record = data.records[index]
        groups = record[20:28].copy().view(np.uint32)
        weights = record[28:36].astype(np.int64)
        slots: list[int] = []
        for group in range(2):
            for position in range(3):
                slots.append(int((groups[group] >> (10 * position)) & 0x3FF))
        gate = int(record[39]) & 63
        if gate != 63:
            halves = record[12:16].copy().view(np.float16).astype(np.float64)
            slots.append(int(np.floor(halves[0] + 0.5)))
            slots.append(int(np.floor(halves[1] + 0.5)))
        else:
            slots.extend((-1, -1))
        return {slot for slot, weight in zip(slots, weights) if weight > 0 and slot >= 0}

    subset = 0
    exact = 0
    over_capacity = 0
    for fixture in fixtures:
        child = live_slots(fixture.mid)
        parents = live_slots(fixture.left) | live_slots(fixture.right)
        if child <= parents:
            subset += 1
        if child == parents:
            exact += 1
        if len(parents) > 8:
            over_capacity += 1
    total = max(1, len(fixtures))
    return {
        "fixtures": len(fixtures),
        "child_bones_subset_of_parents_percent": round(subset / total * 100.0, 3),
        "child_bones_equal_parent_union_percent": round(exact / total * 100.0, 3),
        "parent_union_over_eight_percent": round(over_capacity / total * 100.0, 3),
    }


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--assets", type=int, default=60, help="Assets to search for fixtures.")
    parser.add_argument("--path-contains", default="character/model", help="Archive path filter.")
    parser.add_argument("--min-edge-units", type=float, default=8.0, help="Shortest A-B span, in u16 position units.")
    parser.add_argument("--collinear-tolerance", type=float, default=0.01, help="Offset from the segment, relative to its length.")
    parser.add_argument("--uv-tolerance", type=float, default=0.02, help="UV0 residual, relative to the UV span.")
    parser.add_argument("--normal-agreement", type=float, default=0.0, help="Minimum dot(N_A, N_B) for the smooth subset.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = args.output or (
        Path(__import__("tempfile").gettempdir()) / "cdmw-pac-midpoint-derivation" / run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    entries = discover_pac_entries(game_root=args.game_root, path_contains=(args.path_contains,))
    collected: list[SubmeshFixtures] = []
    scanned = 0
    for entry in entries:
        if len(collected) >= int(args.assets):
            break
        scanned += 1
        try:
            payload, _cached, _source = read_archive_entry_data(entry)
            mesh = parse_mesh(payload, str(entry.path))
        except Exception:
            continue
        for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
            data = _load_submesh(entry, payload, submesh, index)
            if data is None:
                continue
            _find_fixtures(
                data,
                min_edge_units=float(args.min_edge_units),
                collinear_tolerance=float(args.collinear_tolerance),
                uv_tolerance=float(args.uv_tolerance),
                t_range=(0.1, 0.9),
            )
            if data.fixtures:
                collected.append(data)
            break

    fixtures = [(data, fixture) for data in collected for fixture in data.fixtures]
    print(f"  {scanned} assets read, {len(collected)} contributed fixtures, {len(fixtures)} fixtures total")
    if not fixtures:
        print("No fixtures found; Phase 4 cannot run on this corpus.", file=sys.stderr)
        return 2

    results: list[dict[str, object]] = []
    smooth_results: list[dict[str, object]] = []
    stratified: list[dict[str, object]] = []
    for rule in RULES:
        angle_normal: list[np.ndarray] = []
        angle_stored: list[np.ndarray] = []
        encoded: list[dict[str, object]] = []
        smooth_angle_stored: list[np.ndarray] = []
        flatness_all: list[np.ndarray] = []
        for data in collected:
            if not data.fixtures:
                continue
            mid = np.asarray([f.mid for f in data.fixtures])
            left = np.asarray([f.left for f in data.fixtures])
            right = np.asarray([f.right for f in data.fixtures])
            t = np.asarray([f.t for f in data.fixtures])
            smooth = np.asarray([f.normal_agreement >= float(args.normal_agreement) for f in data.fixtures])

            inputs = RuleInputs(
                normal_left=data.normal[left],
                normal_right=data.normal[right],
                stored_left=data.stored[left],
                stored_right=data.stored[right],
                handedness_left=data.handedness[left],
                t=t,
                recomputed_tangent=_recomputed_tangents(data)[mid],
            )
            predicted_normal, predicted_stored = rule.predict(inputs)
            angle_normal.append(_angles(predicted_normal, data.normal[mid]))
            stored_angles = _angles(predicted_stored, data.stored[mid])
            angle_stored.append(stored_angles)
            if smooth.any():
                smooth_angle_stored.append(stored_angles[smooth])
            flatness_all.append(np.asarray([f.normal_agreement for f in data.fixtures]))
            encoded.append(_encoded_errors(predicted_normal, predicted_stored, data.records, mid))

        normals = np.concatenate(angle_normal)
        stored = np.concatenate(angle_stored)
        flatness = np.concatenate(flatness_all)
        for low, high, label in FLATNESS_BINS:
            mask = (flatness >= low) & (flatness < high)
            if mask.sum() < 5:
                continue
            normal_median = float(np.median(normals[mask]))
            stored_median = float(np.median(stored[mask]))
            stratified.append(
                {
                    "rule": rule.name,
                    "flatness": label,
                    "fixtures": int(mask.sum()),
                    "normal_median_deg": round(normal_median, 4),
                    "stored_median_deg": round(stored_median, 4),
                    "stored_p90_deg": round(float(np.percentile(stored[mask], 90)), 4),
                    # The decision-relevant number. The normal is a lane the
                    # shipping serializer already owns and authors, so a ratio at
                    # or below 1 says the tangent lane is no harder to derive
                    # than something already being derived in production.
                    "stored_over_normal": round(stored_median / normal_median, 4) if normal_median > 0 else None,
                }
            )
        merged = {
            key: float(np.mean([row[key] for row in encoded]))
            for key in encoded[0]
        }
        results.append(
            {
                "rule": rule.name,
                "description": rule.description,
                "control": rule.control,
                "fixtures": int(len(stored)),
                "normal_angle_deg": {
                    "median": round(float(np.median(normals)), 4),
                    "p90": round(float(np.percentile(normals, 90)), 4),
                    "max": round(float(normals.max()), 4),
                },
                "stored_vector_angle_deg": {
                    "median": round(float(np.median(stored)), 4),
                    "p90": round(float(np.percentile(stored, 90)), 4),
                    "max": round(float(stored.max()), 4),
                    "within_1_deg_percent": round(float((stored < 1.0).mean() * 100.0), 3),
                },
                "encoded": {key: round(value, 4) for key, value in merged.items()},
            }
        )
        if smooth_angle_stored:
            smooth_all = np.concatenate(smooth_angle_stored)
            smooth_results.append(
                {
                    "rule": rule.name,
                    "fixtures": int(len(smooth_all)),
                    "median_deg": round(float(np.median(smooth_all)), 4),
                    "p90_deg": round(float(np.percentile(smooth_all, 90)), 4),
                }
            )

    skin = _skin_prediction(collected[0], [f for _d, f in fixtures if _d is collected[0]]) if collected else {}
    skin_all = {
        "fixtures": len(fixtures),
        **{
            key: round(
                float(np.mean([_skin_prediction(data, data.fixtures)[key] for data in collected if data.fixtures])), 3
            )
            for key in (
                "child_bones_subset_of_parents_percent",
                "child_bones_equal_parent_union_percent",
                "parent_union_over_eight_percent",
            )
        },
    }

    report = {
        "report_format": REPORT_FORMAT,
        "phase": STUDY_PHASE,
        "plan": PLAN_PATH,
        "run_id": run_id,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started, 3),
        "arguments": {
            "assets": int(args.assets),
            "path_contains": args.path_contains,
            "min_edge_units": float(args.min_edge_units),
            "collinear_tolerance": float(args.collinear_tolerance),
            "uv_tolerance": float(args.uv_tolerance),
        },
        "quantisation": {
            "component_step": COMPONENT_STEP,
            "tangent_lane_step": TANGENT_LANE_STEP,
            "note": (
                "A rule passes only when its residual is within one step of the lane it writes. "
                "Angles are reported too, but the byte comparison is the verdict."
            ),
        },
        "corpus": {
            "assets_read": scanned,
            "assets_with_fixtures": len(collected),
            "fixtures": len(fixtures),
            "midpoint_fixtures": sum(1 for _d, f in fixtures if abs(f.t - 0.5) < 0.02),
            "handedness_disagreeing_fixtures": sum(1 for _d, f in fixtures if not f.handedness_agree),
        },
        "rules": results,
        "stratified_by_flatness": stratified,
        "smooth_subset": smooth_results,
        "skin": skin_all,
        "fixture_sample": [
            {
                "asset": f.asset,
                "submesh": f.submesh_index,
                "mid": f.mid,
                "parents": [f.left, f.right],
                "t": round(f.t, 4),
                "position_residual": round(f.position_residual, 6),
                "uv_residual": round(f.uv_residual, 6),
                "normal_agreement": round(f.normal_agreement, 4),
            }
            for _d, f in fixtures[:20]
        ],
    }
    _atomic_write_json(output_dir / "pac-midpoint-derivation.json", report)

    print(f"\nrun id   : {run_id}")
    print(f"evidence : {output_dir}")
    print(f"fixtures : {len(fixtures)} over {len(collected)} assets, "
          f"{report['corpus']['midpoint_fixtures']} of them at the midpoint")
    print("\nrule                        ctl  stored angle med/p90   exact bytes   normal<=1step  tanY<=1step")
    for row in results:
        print(
            f"  {row['rule']:<26} {'C' if row['control'] else ' '}  "
            f"{row['stored_vector_angle_deg']['median']:>7.3f} /{row['stored_vector_angle_deg']['p90']:>7.3f}   "
            f"{row['encoded']['all_lanes_exact_percent']:>8.2f}%   "
            f"{row['encoded']['normal_within_1_step_percent']:>8.2f}%   "
            f"{row['encoded']['tangent_y_within_1_step_percent']:>8.2f}%"
        )
    print("\nstratified by how flat the patch is (the normal is the positive control):")
    print(f"  {'rule':<26}{'flatness':<16}{'n':>6}{'normal med':>12}{'stored med':>12}{'ratio':>8}")
    for row in stratified:
        ratio = row["stored_over_normal"]
        print(
            f"  {row['rule']:<26}{row['flatness']:<16}{row['fixtures']:>6}"
            f"{row['normal_median_deg']:>12.3f}{row['stored_median_deg']:>12.3f}"
            f"{(f'{ratio:.2f}' if ratio is not None else '-'):>8}"
        )
    print(f"\nskin: {skin_all}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
