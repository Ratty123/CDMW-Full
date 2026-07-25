"""Split a body difference into per-region sliders.

Capturing "vanilla versus this modded body" as a morph target already works, but
it yields one monolithic slider: all of it or none of it. Splitting that
difference across the body regions turns any existing body mod into an editable
set — keep its hips, halve its bust, drop its calves.

The split is exact. Region weights are a partition of unity, so scaling each
region's share by its own slider and summing reproduces the original difference
with no residual: every region at 100% is the captured body, vertex for vertex.
Vertices no region claims would break that, so their remainder becomes its own
slider rather than being silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Mapping, Sequence

from cdmw.domain.mesh.body_regions import BodyRegionMap

from .mesh_morph_sliders import (
    MESH_MORPH_SLIDER_TYPE_MORPH_TARGET,
    MeshMorphSliderDelta,
)
from .mesh_parser import ParsedMesh


REGION_REMAINDER_SLIDER_ID = "unassigned"
DEFAULT_REGION_SLIDER_MINIMUM = -100.0
DEFAULT_REGION_SLIDER_MAXIMUM = 200.0
"""Headroom past the captured shape, so a region can be pushed beyond it."""

Vec3 = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class BodyDifferenceCapture:
    """A captured body-to-body displacement and what it could not cover."""

    delta: MeshMorphSliderDelta
    skipped_submesh_indices: tuple[int, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegionDecomposition:
    """Per-region sliders plus what the split could and could not account for."""

    sliders: tuple[MeshMorphSliderDelta, ...] = ()
    moved_vertex_count: int = 0
    unassigned_vertex_count: int = 0
    skipped_submesh_indices: tuple[int, ...] = ()
    reconstruction_error: float = 0.0
    diagnostics: tuple[str, ...] = ()

    @property
    def exact(self) -> bool:
        """True when every region at 100% rebuilds the captured body."""

        return self.reconstruction_error <= 1.0e-6


def decompose_body_difference(
    base_mesh: ParsedMesh,
    target_mesh: ParsedMesh,
    region_map: BodyRegionMap,
    *,
    slider_prefix: str = "",
    minimum_displacement: float = 1.0e-6,
) -> RegionDecomposition:
    """Capture base -> target and split it across the map's regions."""

    capture = capture_body_difference(base_mesh, target_mesh, slider_prefix or "body_difference")
    decomposition = decompose_morph_delta_by_region(
        capture.delta,
        region_map,
        slider_prefix=slider_prefix,
        minimum_displacement=minimum_displacement,
    )
    return replace(
        decomposition,
        skipped_submesh_indices=capture.skipped_submesh_indices,
        diagnostics=capture.diagnostics + decomposition.diagnostics,
    )


def capture_body_difference(
    base_mesh: ParsedMesh,
    target_mesh: ParsedMesh,
    slider_id: str = "body_difference",
) -> BodyDifferenceCapture:
    """Per-vertex displacement from one body to another of the same topology.

    Deliberately not :func:`build_morph_delta`, which also demands matching
    submesh names. Body variants rename their parts — the vanilla female body
    ships as ``cd_phw_00_nude_0001`` and its heavier variant as
    ``CD_PHW_00_Nude_0001_Fat`` — so a name check would refuse exactly the
    bodies a modder wants to decompose.

    Correspondence is per submesh, because it varies within one file: between
    those two bodies the torso and hands are index-identical while the head
    shares only its vertex count. A submesh whose faces disagree is skipped and
    named rather than subtracted, since its vertices do not line up and the
    difference would be noise.
    """

    base_submeshes = tuple(base_mesh.submeshes or ())
    target_submeshes = tuple(target_mesh.submeshes or ())
    if len(base_submeshes) != len(target_submeshes):
        raise ValueError(
            "Cannot capture a body difference: submesh count differs "
            f"(base {len(base_submeshes)}, target {len(target_submeshes)})."
        )
    rows: list[tuple[Vec3, ...]] = []
    skipped: list[int] = []
    for index, (base_submesh, target_submesh) in enumerate(zip(base_submeshes, target_submeshes)):
        base_vertices = base_submesh.vertices or []
        target_vertices = target_submesh.vertices or []
        aligned = len(base_vertices) == len(target_vertices) and list(base_submesh.faces or []) == list(
            target_submesh.faces or []
        )
        if not aligned:
            skipped.append(index)
            rows.append(tuple((0.0, 0.0, 0.0) for _ in base_vertices))
            continue
        rows.append(
            tuple(
                (
                    float(moved[0]) - float(origin[0]),
                    float(moved[1]) - float(origin[1]),
                    float(moved[2]) - float(origin[2]),
                )
                for origin, moved in zip(base_vertices, target_vertices)
            )
        )
    if len(skipped) == len(base_submeshes):
        raise ValueError(
            "Cannot capture a body difference: no submesh shares the other body's topology."
        )
    diagnostics: list[str] = []
    if skipped:
        names = ", ".join(
            f"{index} ({base_submeshes[index].name or 'unnamed'})" for index in skipped
        )
        diagnostics.append(
            f"Submesh {names} does not share the other body's topology and was left unchanged; "
            "its difference cannot be expressed as per-vertex displacement."
        )
    return BodyDifferenceCapture(
        delta=MeshMorphSliderDelta(
            slider_id=str(slider_id or "body_difference"),
            label="Body Difference",
            deltas=tuple(rows),
            min_percent=DEFAULT_REGION_SLIDER_MINIMUM,
            max_percent=DEFAULT_REGION_SLIDER_MAXIMUM,
            default_percent=100.0,
            slider_type=MESH_MORPH_SLIDER_TYPE_MORPH_TARGET,
        ),
        skipped_submesh_indices=tuple(skipped),
        diagnostics=tuple(diagnostics),
    )


def decompose_morph_delta_by_region(
    captured: MeshMorphSliderDelta,
    region_map: BodyRegionMap,
    *,
    slider_prefix: str = "",
    minimum_displacement: float = 1.0e-6,
) -> RegionDecomposition:
    """Split an already-captured delta across regions, exactly."""

    submesh_deltas = tuple(tuple(rows) for rows in captured.deltas)
    weights = _region_weights(region_map, submesh_deltas)
    prefix = str(slider_prefix or "").strip()

    sliders: list[MeshMorphSliderDelta] = []
    accumulated = [[[0.0, 0.0, 0.0] for _ in rows] for rows in submesh_deltas]
    for region in region_map.populated_regions:
        share = _region_share(submesh_deltas, weights.get(region.region_id, {}))
        if not _has_displacement(share, minimum_displacement):
            continue
        _accumulate(accumulated, share)
        sliders.append(
            _slider(
                _identifier(prefix, region.region_id),
                f"{region.label}" if not prefix else f"{prefix} {region.label}",
                share,
                captured,
            )
        )

    remainder, unassigned = _remainder(submesh_deltas, accumulated, minimum_displacement)
    diagnostics: list[str] = []
    if remainder is not None:
        _accumulate(accumulated, remainder)
        sliders.append(
            _slider(
                _identifier(prefix, REGION_REMAINDER_SLIDER_ID),
                "Unassigned" if not prefix else f"{prefix} Unassigned",
                remainder,
                captured,
            )
        )
        diagnostics.append(
            f"{unassigned} moved vertices belong to no region; their displacement was kept "
            "in a separate slider so the split stays exact."
        )

    error = _reconstruction_error(submesh_deltas, accumulated)
    if error > 1.0e-6:
        diagnostics.append(
            f"Region shares rebuild the capture to {error * 1000.0:.4f} mm, not exactly."
        )
    return RegionDecomposition(
        sliders=tuple(sliders),
        moved_vertex_count=_moved_count(submesh_deltas, minimum_displacement),
        unassigned_vertex_count=unassigned,
        reconstruction_error=error,
        diagnostics=tuple(diagnostics),
    )


def _region_weights(
    region_map: BodyRegionMap,
    submesh_deltas: Sequence[Sequence[Vec3]],
) -> dict[str, dict[int, dict[int, float]]]:
    weights: dict[str, dict[int, dict[int, float]]] = {}
    for region in region_map.populated_regions:
        rows: dict[int, dict[int, float]] = {}
        for part in region.parts:
            if not 0 <= part.submesh_index < len(submesh_deltas):
                continue
            rows[part.submesh_index] = dict(zip(part.vertex_indices, part.weights))
        weights[region.region_id] = rows
    return weights


def _region_share(
    submesh_deltas: Sequence[Sequence[Vec3]],
    rows: Mapping[int, Mapping[int, float]],
) -> list[list[Vec3]]:
    share: list[list[Vec3]] = []
    for submesh_index, deltas in enumerate(submesh_deltas):
        weights = rows.get(submesh_index, {})
        submesh_share: list[Vec3] = []
        for vertex_index, delta in enumerate(deltas):
            weight = weights.get(vertex_index, 0.0)
            if weight:
                submesh_share.append((delta[0] * weight, delta[1] * weight, delta[2] * weight))
            else:
                submesh_share.append((0.0, 0.0, 0.0))
        share.append(submesh_share)
    return share


def _remainder(
    submesh_deltas: Sequence[Sequence[Vec3]],
    accumulated: Sequence[Sequence[Sequence[float]]],
    minimum_displacement: float,
) -> tuple[list[list[Vec3]] | None, int]:
    """Whatever the regions did not account for, as its own field."""

    rows: list[list[Vec3]] = []
    count = 0
    for deltas, running in zip(submesh_deltas, accumulated):
        submesh_rows: list[Vec3] = []
        for delta, total in zip(deltas, running):
            left = (delta[0] - total[0], delta[1] - total[1], delta[2] - total[2])
            if _length(left) >= minimum_displacement:
                count += 1
                submesh_rows.append(left)
            else:
                submesh_rows.append((0.0, 0.0, 0.0))
        rows.append(submesh_rows)
    return (rows, count) if count else (None, 0)


def _slider(
    slider_id: str,
    label: str,
    share: Sequence[Sequence[Vec3]],
    captured: MeshMorphSliderDelta,
) -> MeshMorphSliderDelta:
    return MeshMorphSliderDelta(
        slider_id=slider_id,
        label=label,
        deltas=tuple(tuple(rows) for rows in share),
        min_percent=DEFAULT_REGION_SLIDER_MINIMUM,
        max_percent=DEFAULT_REGION_SLIDER_MAXIMUM,
        # Opens on the captured body, so a decomposed mod starts where it was.
        default_percent=100.0,
        slider_type=captured.slider_type or MESH_MORPH_SLIDER_TYPE_MORPH_TARGET,
    )


def _accumulate(running: Sequence[Sequence[Sequence[float]]], share: Sequence[Sequence[Vec3]]) -> None:
    for submesh_running, submesh_share in zip(running, share):
        for total, delta in zip(submesh_running, submesh_share):
            total[0] += delta[0]
            total[1] += delta[1]
            total[2] += delta[2]


def _reconstruction_error(
    submesh_deltas: Sequence[Sequence[Vec3]],
    accumulated: Sequence[Sequence[Sequence[float]]],
) -> float:
    worst = 0.0
    for deltas, running in zip(submesh_deltas, accumulated):
        for delta, total in zip(deltas, running):
            worst = max(
                worst,
                _length((delta[0] - total[0], delta[1] - total[1], delta[2] - total[2])),
            )
    return worst


def _has_displacement(share: Sequence[Sequence[Vec3]], minimum_displacement: float) -> bool:
    return any(
        _length(delta) >= minimum_displacement for submesh in share for delta in submesh
    )


def _moved_count(submesh_deltas: Sequence[Sequence[Vec3]], minimum_displacement: float) -> int:
    return sum(
        1 for deltas in submesh_deltas for delta in deltas if _length(delta) >= minimum_displacement
    )


def _identifier(prefix: str, suffix: str) -> str:
    stem = f"{prefix}_{suffix}" if prefix else suffix
    return stem.strip().lower().replace(" ", "_")


def _length(value: Sequence[float]) -> float:
    return math.sqrt((value[0] * value[0]) + (value[1] * value[1]) + (value[2] * value[2]))
