"""New Item Studio: a model of the user's own, placed over the template in the studio itself.

The Model and icon step takes a model file (glTF, GLB, OBJ, DAE, or a zip holding one),
reads it the way the Model Library does (the scene import, the source's own textures), and
shows it in the step's viewport over the template's mesh, where the gizmo and the numbers
place it. Two layers: the *fit* (`fitted_placement`: scaled to the template's length, levelled
with its grid, and centred or grip-aligned for the template family) is baked into the mesh
itself (`bake_mesh`), so the numbers the user sees and the gizmo moves start at zero; the
*placement* on top is one convention everywhere: scale, then the rotations about x, y and
z, then the offset, all about the baked model's origin (the hand, for a weapon). The helper
composes a gizmo drag that way
(`ManualLinearMatrix`), the host's fallback matrix does, and so does the static
replacement pipeline (`_rotate_xyz`), so `ModelPlacement.build_transform()` hands the
numbers over as they are. Applying the placement runs the Builder's import headlessly over
the baked mesh (`build_placed_import`), and what comes back is what the Builder's dialog
would have handed over: the rebuilt mesh and its side files.
"""

from __future__ import annotations

import copy
import hashlib
import math
import shutil
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ArchiveEntry
from cdmw.services.fbx_blender_conversion import FBX_EXTENSION, convert_fbx_to_glb
from cdmw.services.preview_workflow_service import scene_import_normalizes_texture_v
from cdmw.services.mesh_workflow_service import StaticMeshReplacementOptions, StaticReplacementTransform, StaticTextureUvTransform

__all__ = [
    "MeshGeometryAnalysis",
    "MeshPrincipalFrame",
    "ModelImportSource",
    "ModelPlacement",
    "Vec3",
    "bake_mesh",
    "build_placed_import",
    "flip_v_transforms",
    "fitted_placement",
    "load_model_import_source",
    "analyze_mesh_geometry",
    "mesh_bounds",
    "mesh_centroid",
    "mesh_principal_frame",
    "prepare_model_import_mesh_edit",
]

Vec3 = Tuple[float, float, float]
Bounds = Tuple[Vec3, Vec3]
MODEL_IMPORTER_SCHEMA_VERSION = 2
MODEL_FIT_VERSION = 3


@dataclass(frozen=True)
class MeshPrincipalFrame:
    """A mesh's oriented bounds, ordered from its longest axis to its shortest.

    Elongated models supply a heading; broad models also supply a stable plane.
    A model with neither keeps the established axis-aligned fit, where an
    unstable eigendirection would be worse than no extra rotation.
    """

    axes: Tuple[Vec3, Vec3, Vec3]
    intervals: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]
    center: Vec3
    direction_hint: Optional[Vec3] = None
    grip: Optional[Vec3] = None
    tip: Optional[Vec3] = None
    end_weights: Tuple[float, float] = (0.0, 0.0)

    @property
    def extents(self) -> Vec3:
        return tuple(max(0.0, high - low) for low, high in self.intervals)

    @property
    def is_elongated(self) -> bool:
        long, middle, _short = self.extents
        return long > 1e-9 and long >= max(middle, 1e-9) * 1.15


@dataclass(frozen=True)
class MeshGeometryAnalysis:
    """Bounds, mass cues, and principal frame computed from one vertex walk."""

    bounds: Optional[Bounds]
    centroid: Optional[Vec3]
    principal_frame: Optional[MeshPrincipalFrame]


class _ModelImportUsage:
    """One worker's claim on an imported source until native teardown."""

    def __init__(self, source: "ModelImportSource") -> None:
        self._source: Optional[ModelImportSource] = source
        self._release_lock = threading.Lock()

    def release(self) -> None:
        with self._release_lock:
            source, self._source = self._source, None
        if source is not None:
            source._release_usage()

    def __enter__(self) -> "_ModelImportUsage":
        return self

    def __exit__(self, _error_type, _error, _traceback) -> None:
        self.release()


def _vec(values: Sequence[float], fallback: Vec3) -> Vec3:
    try:
        items = tuple(float(v) for v in values)
    except (TypeError, ValueError):
        return fallback
    return items if len(items) == 3 else fallback


# ------------------------------------------------------------------ the placement


@dataclass(frozen=True)
class ModelPlacement:
    """Where the imported model sits over the template: offset in metres, rotation in
    degrees about x, then y, then z, scale per axis. Scale first, then the rotations,
    then the offset, all about the model's origin (the hand, for a weapon)."""

    offset: Vec3 = (0.0, 0.0, 0.0)
    rotation: Vec3 = (0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)

    def with_values(self, *, offset: Optional[Sequence[float]] = None, rotation: Optional[Sequence[float]] = None, scale: Optional[Sequence[float]] = None) -> "ModelPlacement":
        return replace(
            self,
            offset=_vec(offset, self.offset) if offset is not None else self.offset,
            rotation=_vec(rotation, self.rotation) if rotation is not None else self.rotation,
            scale=_vec(scale, self.scale) if scale is not None else self.scale,
        )

    def matrix(self, *, origin: Optional[Sequence[float]] = None) -> list:
        """The 4 x 4 row-vector matrix the viewport composes for this placement.

        ``origin`` is the fitted source origin the Model & Placement gizmo rotates and
        scales about. With it, this is the same anchored manual transform that
        :meth:`build_transform` gives the final Builder and resident scene frame.
        """

        from cdmw.ui.preview.dotnet_host import _placement_matrix

        matrix = _placement_matrix(self.offset, self.rotation, self.scale)
        if origin is None:
            return matrix
        anchor = _vec(origin, (0.0, 0.0, 0.0))
        # Desired anchored placement: ``(point - anchor) @ linear + anchor + offset``.
        # Translation occupies M41/M42/M43 in the shared row-vector convention.
        matrix[12] = anchor[0] + self.offset[0] - (
            anchor[0] * matrix[0] + anchor[1] * matrix[4] + anchor[2] * matrix[8]
        )
        matrix[13] = anchor[1] + self.offset[1] - (
            anchor[0] * matrix[1] + anchor[1] * matrix[5] + anchor[2] * matrix[9]
        )
        matrix[14] = anchor[2] + self.offset[2] - (
            anchor[0] * matrix[2] + anchor[1] * matrix[6] + anchor[2] * matrix[10]
        )
        return matrix

    def apply(self, point: Sequence[float]) -> Vec3:
        """`point` under the placement (row vector times the matrix)."""

        m = self.matrix()
        x, y, z = (float(v) for v in point[:3])
        return (
            x * m[0] + y * m[4] + z * m[8] + m[12],
            x * m[1] + y * m[5] + z * m[9] + m[13],
            x * m[2] + y * m[6] + z * m[10] + m[14],
        )

    def build_transform(self, *, origin: Optional[Sequence[float]] = None) -> StaticReplacementTransform:
        """The static replacement pipeline's transform for this placement: manual mode
        (no auto scale or fit), the same scale, rotation and offset. ``origin`` names the
        already-baked source origin when the mesh's first fit moved it away from world
        zero; using it as both anchors keeps the build and the gizmo on that origin."""

        anchor = _vec(origin, (0.0, 0.0, 0.0)) if origin is not None else None

        return StaticReplacementTransform(
            rotate_xyz_degrees=tuple(float(v) for v in self.rotation),
            scale=1.0,
            scale_xyz=tuple(float(v) for v in self.scale),
            offset_xyz=tuple(float(v) for v in self.offset),
            fit_to_original_bbox=False,
            scale_to_original_length=False,
            alignment_mode="manual",
            source_anchor=anchor,
            target_anchor=anchor,
        )

    @property
    def is_identity(self) -> bool:
        return all(abs(v) < 1e-9 for v in self.offset) and all(abs(v) < 1e-9 for v in self.rotation) and all(abs(v - 1.0) < 1e-9 for v in self.scale)


# ------------------------------------------------------------------ bounds and the fit


def analyze_mesh_geometry(mesh: object) -> MeshGeometryAnalysis:
    """Analyze geometry once, including named anchors and surface-weighted ends."""

    try:
        import numpy as np
    except Exception:  # pragma: no cover - the bundled runtime includes NumPy
        np = None

    points: list[tuple[float, float, float]] = []
    triangle_centres: list[tuple[float, float, float]] = []
    triangle_areas: list[float] = []
    named: dict[str, list[tuple[float, float, float]]] = {"grip": [], "tip": []}
    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    total = [0.0, 0.0, 0.0]
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        raw_vertices = tuple(getattr(submesh, "vertices", ()) or ())
        local: list[Optional[tuple[float, float, float]]] = []
        label = " ".join(
            str(value or "").casefold()
            for value in (getattr(submesh, "name", ""), getattr(submesh, "material", ""))
        )
        group = (
            "grip"
            if any(token in label for token in ("grip", "hilt", "handle", "pommel"))
            else "tip"
            if any(token in label for token in ("tip", "blade_end", "point"))
            else ""
        )
        for vertex in raw_vertices:
            try:
                point = tuple(float(vertex[axis]) for axis in range(3))
            except (IndexError, TypeError, ValueError):
                local.append(None)
                continue
            if not all(math.isfinite(value) for value in point):
                local.append(None)
                continue
            local.append(point)
            points.append(point)
            if group:
                named[group].append(point)
            for axis, value in enumerate(point):
                lo[axis] = min(lo[axis], value)
                hi[axis] = max(hi[axis], value)
                total[axis] += value
        for face in tuple(getattr(submesh, "faces", ()) or ()):
            try:
                indices = tuple(int(face[index]) for index in range(3))
                triangle = tuple(local[index] for index in indices)
            except (IndexError, TypeError, ValueError):
                continue
            if any(point is None for point in triangle):
                continue
            a, b, c = triangle  # type: ignore[misc]
            ab = tuple(b[index] - a[index] for index in range(3))
            ac = tuple(c[index] - a[index] for index in range(3))
            cross = (
                ab[1] * ac[2] - ab[2] * ac[1],
                ab[2] * ac[0] - ab[0] * ac[2],
                ab[0] * ac[1] - ab[1] * ac[0],
            )
            area = 0.5 * math.sqrt(sum(value * value for value in cross))
            if area > 1e-18 and math.isfinite(area):
                triangle_areas.append(area)
                triangle_centres.append(tuple((a[index] + b[index] + c[index]) / 3.0 for index in range(3)))
    if not points:
        return MeshGeometryAnalysis(None, None, None)
    bounds: Bounds = (tuple(lo), tuple(hi))  # type: ignore[assignment]
    centroid: Vec3 = tuple(value / len(points) for value in total)  # type: ignore[assignment]
    if np is None or len(points) < 3:
        return MeshGeometryAnalysis(bounds, centroid, None)

    array = np.asarray(points, dtype=np.float64)
    mean = array.mean(axis=0)
    covariance = (array.T @ array) / len(array) - np.outer(mean, mean)
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    except np.linalg.LinAlgError:
        return MeshGeometryAnalysis(bounds, centroid, None)
    order = np.argsort(eigenvalues)[::-1]
    if float(eigenvalues[order[0]]) <= 1e-18:
        return MeshGeometryAnalysis(bounds, centroid, None)
    axes = [np.asarray(eigenvectors[:, index], dtype=np.float64) for index in order]
    if float(np.dot(np.cross(axes[0], axes[1]), axes[2])) < 0.0:
        axes[2] = -axes[2]
    projections = array @ np.stack(axes, axis=1)
    lows = projections.min(axis=0)
    highs = projections.max(axis=0)
    center_vector = sum(
        (axis * ((lows[index] + highs[index]) * 0.5) for index, axis in enumerate(axes)),
        np.zeros(3, dtype=np.float64),
    )

    def named_center(key: str) -> Optional[Vec3]:
        values = named[key]
        if not values:
            return None
        centre = np.asarray(values, dtype=np.float64).mean(axis=0)
        return tuple(float(value) for value in centre)

    grip = named_center("grip")
    tip = named_center("tip")
    direction = None
    if grip is not None and tip is not None:
        direction = tuple(tip[index] - grip[index] for index in range(3))
    elif grip is not None:
        direction = tuple(float(center_vector[index]) - grip[index] for index in range(3))
    elif tip is not None:
        direction = tuple(tip[index] - float(center_vector[index]) for index in range(3))

    end_weights = (0.0, 0.0)
    if triangle_centres:
        centres = np.asarray(triangle_centres, dtype=np.float64)
        areas = np.asarray(triangle_areas, dtype=np.float64)
        long_projection = centres @ axes[0]
        span = max(float(highs[0] - lows[0]), 1e-12)
        low_weight = float(areas[long_projection <= lows[0] + span * 0.28].sum())
        high_weight = float(areas[long_projection >= highs[0] - span * 0.28].sum())
        end_weights = (low_weight, high_weight)
        if direction is None and max(low_weight, high_weight) > min(low_weight, high_weight) * 1.05:
            sign = 1.0 if high_weight > low_weight else -1.0
            direction = tuple(float(value * sign) for value in axes[0])
        if direction is None:
            surface_center = (centres * areas[:, None]).sum(axis=0) / max(float(areas.sum()), 1e-12)
            surface_lean = surface_center - center_vector
            if float(np.linalg.norm(surface_lean)) > span * 0.02:
                direction = tuple(float(value) for value in surface_lean)
    if direction is None:
        vertex_lean = np.asarray(centroid) - center_vector
        if float(np.linalg.norm(vertex_lean)) > max(float(highs[0] - lows[0]), 1e-12) * 0.02:
            direction = tuple(float(value) for value in vertex_lean)

    frame = MeshPrincipalFrame(
        axes=tuple(tuple(float(value) for value in axis) for axis in axes),
        intervals=tuple((float(lows[index]), float(highs[index])) for index in range(3)),
        center=tuple(float(value) for value in center_vector),
        direction_hint=direction,
        grip=grip,
        tip=tip,
        end_weights=end_weights,
    )
    return MeshGeometryAnalysis(bounds, centroid, frame)


def mesh_bounds(mesh: object) -> Optional[Bounds]:
    """Return an AABB without paying for PCA when framing alone needs bounds."""

    low = [math.inf, math.inf, math.inf]
    high = [-math.inf, -math.inf, -math.inf]
    found = False
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for vertex in tuple(getattr(submesh, "vertices", ()) or ()):
            try:
                point = tuple(float(vertex[axis]) for axis in range(3))
            except (IndexError, TypeError, ValueError):
                continue
            if not all(math.isfinite(value) for value in point):
                continue
            found = True
            for axis, value in enumerate(point):
                low[axis] = min(low[axis], value)
                high[axis] = max(high[axis], value)
    if not found:
        return None
    return tuple(low), tuple(high)  # type: ignore[return-value]


def _axis_order(extent: Sequence[float]) -> Tuple[int, int, int]:
    """Axis indices from the longest extent to the shortest."""

    return tuple(sorted(range(3), key=lambda axis: -float(extent[axis])))


def mesh_centroid(mesh: object) -> Optional[Vec3]:
    """The mean vertex of a ParsedMesh (or anything with `submeshes` carrying `vertices`):
    a weapon's detail sits at the hilt, so it leans toward the hand; None without a vertex."""

    total = [0.0, 0.0, 0.0]
    count = 0
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for vertex in tuple(getattr(submesh, "vertices", ()) or ()):
            try:
                point = tuple(float(vertex[axis]) for axis in range(3))
            except (IndexError, TypeError, ValueError):
                continue
            if not all(math.isfinite(value) for value in point):
                continue
            for axis, value in enumerate(point):
                total[axis] += value
            count += 1
    if not count:
        return None
    return tuple(value / count for value in total)  # type: ignore[return-value]


def mesh_principal_frame(mesh: object) -> Optional[MeshPrincipalFrame]:
    """Return the consolidated PCA frame, or ``None`` without enough data."""

    return analyze_mesh_geometry(mesh).principal_frame


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def fitted_placement(
    source_bounds: Optional[Bounds],
    template_bounds: Optional[Bounds],
    *,
    source_centroid: Optional[Vec3] = None,
    template_centroid: Optional[Vec3] = None,
    match_grip: bool = True,
    source_frame: Optional[MeshPrincipalFrame] = None,
    template_frame: Optional[MeshPrincipalFrame] = None,
) -> ModelPlacement:
    """Scale to the template and align the source's broad plane with the placement grid.

    Stable oriented frames retain the template's heading within that plane, without
    copying its tilt. Ambiguous shapes keep the right-angle bounding-box fit. Weapon
    families additionally match heavy ends and grips; other families stay centred.
    The user can adjust the fitted placement afterwards.
    """

    if source_bounds is None or template_bounds is None:
        return ModelPlacement()
    s_lo, s_hi = source_bounds
    t_lo, t_hi = template_bounds
    s_ext = tuple(max(0.0, s_hi[i] - s_lo[i]) for i in range(3))
    t_ext = tuple(max(0.0, t_hi[i] - t_lo[i]) for i in range(3))
    if (
        source_frame is not None
        and template_frame is not None
        and (
            source_frame.is_elongated
            or source_frame.extents[1] > max(source_frame.extents[2], 1e-9) * 1.15
        )
    ):
        return _fitted_principal_placement(
            source_frame,
            template_frame,
            source_centroid=source_centroid,
            template_centroid=template_centroid,
            match_grip=match_grip,
            # Match flat_preview_normal_axis, including its Z-first tie break.
            grid_axis=min((2, 0, 1), key=lambda index: t_ext[index]),
        )
    s_long = max(s_ext)
    t_long = max(t_ext)
    scale = t_long / s_long if s_long > 1e-9 and t_long > 1e-9 else 1.0
    s_order = _axis_order(s_ext)
    t_order = _axis_order(t_ext)
    unit = lambda axis: tuple(1.0 if i == axis else 0.0 for i in range(3))  # noqa: E731
    s_centre = tuple((s_lo[i] + s_hi[i]) * 0.5 for i in range(3))
    t_centre = tuple((t_lo[i] + t_hi[i]) * 0.5 for i in range(3))
    # which way the heavy end lies, along the long and the middle axis, as signs
    s_lean = tuple(source_centroid[i] - s_centre[i] for i in range(3)) if source_centroid is not None else None
    t_lean = tuple(template_centroid[i] - t_centre[i] for i in range(3)) if template_centroid is not None else None

    def score(rotation: Vec3) -> Tuple[float, float]:
        turned = ModelPlacement(rotation=rotation)
        long_fit = abs(_dot(turned.apply(unit(s_order[0])), unit(t_order[0])))
        mid_fit = abs(_dot(turned.apply(unit(s_order[1])), unit(t_order[1])))
        value = round(long_fit, 6) + round(mid_fit, 6) * 0.5
        if match_grip and s_lean is not None and t_lean is not None:
            lean = turned.apply(s_lean)
            for weight, axis, threshold in ((0.25, t_order[0], 0.02), (0.125, t_order[1], 0.02)):
                theirs = t_lean[axis]
                ours = lean[axis]
                # only when both lean clearly (a fiftieth of the extent), else no opinion
                if abs(theirs) > threshold * t_ext[axis] and abs(ours) * scale > threshold * t_ext[axis] and theirs * ours > 0:
                    value += weight
        return (value, -sum(abs(v) for v in rotation))

    best = (0.0, 0.0, 0.0)
    best_score = score(best)
    for rx in (0.0, 90.0, 180.0, -90.0):
        for ry in (0.0, 90.0, 180.0, -90.0):
            for rz in (0.0, 90.0, 180.0, -90.0):
                candidate = (rx, ry, rz)
                candidate_score = score(candidate)
                if candidate_score > best_score:
                    best, best_score = candidate, candidate_score
    placement = ModelPlacement(rotation=best, scale=(scale, scale, scale))
    moved = placement.apply(s_centre)
    offset = [t_centre[i] - moved[i] for i in range(3)]

    # Along the long axis, line the grips up rather than the centres. A weapon is held by
    # its grip, and two weapons of the same length can carry their mass very differently:
    # an axe whose head is most of it has its grip far from its middle, so matching middles
    # leaves the handle half a weapon away from the hand and the reader drags it back by
    # exactly that much. The grip is the end away from the heavy one, which is the same
    # reading of the centroid the turn above already trusts.
    axis = t_order[0]
    turned_lean = placement.apply(s_lean) if s_lean is not None else None
    if match_grip and t_lean is not None and turned_lean is not None:
        threshold = 0.02
        theirs, ours = t_lean[axis], turned_lean[axis]
        if abs(theirs) > threshold * t_ext[axis] and abs(ours) > threshold * t_ext[axis]:
            corners = [
                placement.apply((x, y, z))
                for x in (s_lo[0], s_hi[0]) for y in (s_lo[1], s_hi[1]) for z in (s_lo[2], s_hi[2])
            ]
            source_low = min(corner[axis] for corner in corners)
            source_high = max(corner[axis] for corner in corners)
            # the grip end of each, then the move that brings them together
            template_grip = t_lo[axis] if theirs > 0 else t_hi[axis]
            source_grip = source_low if ours > 0 else source_high
            offset[axis] = template_grip - source_grip
    return placement.with_values(offset=tuple(offset))


def _xyz_degrees_from_row_matrix(matrix: Sequence[Sequence[float]]) -> Vec3:
    """Invert the shared row-vector ``Rx @ Ry @ Rz`` placement convention."""

    sin_y = max(-1.0, min(1.0, -float(matrix[0][2])))
    y = math.asin(sin_y)
    if abs(math.cos(y)) > 1e-8:
        x = math.atan2(float(matrix[1][2]), float(matrix[2][2]))
        z = math.atan2(float(matrix[0][1]), float(matrix[0][0]))
    else:
        x = math.atan2(-float(matrix[2][1]), float(matrix[1][1]))
        z = 0.0
    return tuple(math.degrees(value) for value in (x, y, z))


def _fitted_principal_placement(
    source: MeshPrincipalFrame,
    template: MeshPrincipalFrame,
    *,
    source_centroid: Optional[Vec3],
    template_centroid: Optional[Vec3],
    match_grip: bool,
    grid_axis: int,
) -> ModelPlacement:
    """Level the source to the grid while retaining template heading and anchors."""

    normal_sign = 1.0 if template.axes[2][grid_axis] >= 0.0 else -1.0
    normal = tuple(normal_sign if index == grid_axis else 0.0 for index in range(3))
    long = tuple(0.0 if index == grid_axis else value for index, value in enumerate(template.axes[0]))
    length = math.sqrt(_dot(long, long))
    if length < 1e-9:
        # A degenerate projection has no heading on the grid.
        long = tuple(1.0 if index == (grid_axis + 1) % 3 else 0.0 for index in range(3))
    else:
        long = tuple(value / length for value in long)
    middle = (
        normal[1] * long[2] - normal[2] * long[1],
        normal[2] * long[0] - normal[0] * long[2],
        normal[0] * long[1] - normal[1] * long[0],
    )
    target_axes = (long, middle, normal)

    source_lean = source.direction_hint or (
        tuple(source_centroid[index] - source.center[index] for index in range(3))
        if source_centroid is not None
        else None
    )
    template_lean = template.direction_hint or (
        tuple(template_centroid[index] - template.center[index] for index in range(3))
        if template_centroid is not None
        else None
    )
    candidates = (
        (1.0, 1.0, 1.0),
        (1.0, -1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
    )
    best_matrix = None
    best_score = None
    for signs in candidates:
        signed_target = tuple(
            tuple(signs[index] * component for component in target_axes[index])
            for index in range(3)
        )
        # S * R = T for row-vector axes, so R = transpose(S) * T.
        matrix = tuple(
            tuple(
                sum(source.axes[index][row] * signed_target[index][column] for index in range(3))
                for column in range(3)
            )
            for row in range(3)
        )
        trace = sum(matrix[index][index] for index in range(3))
        turn = math.acos(max(-1.0, min(1.0, (trace - 1.0) * 0.5)))
        long_match = middle_match = 0
        if match_grip and source_lean is not None and template_lean is not None:
            for index, weight in ((0, 2), (1, 1)):
                ours = _dot(source_lean, source.axes[index]) * signs[index]
                theirs = _dot(template_lean, template.axes[index])
                if (
                    abs(ours) > 0.02 * template.extents[index]
                    and abs(theirs) > 0.02 * template.extents[index]
                ):
                    matched = 1 if ours * theirs > 0.0 else -1
                    if index == 0:
                        long_match = matched * weight
                    else:
                        middle_match = matched * weight
        score = (long_match, middle_match, -turn)
        if best_score is None or score > best_score:
            best_score = score
            best_matrix = matrix

    assert best_matrix is not None
    source_length = source.extents[0]
    template_length = template.extents[0]
    scale = template_length / source_length if source_length > 1e-9 else 1.0
    placement = ModelPlacement(
        rotation=_xyz_degrees_from_row_matrix(best_matrix),
        scale=(scale, scale, scale),
    )
    moved_center = placement.apply(source.center)
    offset = [template.center[index] - moved_center[index] for index in range(3)]
    placement = placement.with_values(offset=offset)

    if match_grip and source.grip is not None and template.grip is not None:
        moved_grip = placement.apply(source.grip)
        placement = placement.with_values(
            offset=tuple(
                placement.offset[index] + template.grip[index] - moved_grip[index]
                for index in range(3)
            )
        )
        return placement

    if match_grip and source_lean is not None and template_lean is not None:
        ours = _dot(source_lean, source.axes[0]) * scale
        theirs = _dot(template_lean, template.axes[0])
        if (
            abs(ours) > 0.02 * template.extents[0]
            and abs(theirs) > 0.02 * template.extents[0]
        ):
            # The reference remains in its authored frame. Align the actual grip
            # points in 3D, since its long axis can now differ from the level source.
            def grip_point(frame: MeshPrincipalFrame, lean: float) -> Vec3:
                end = frame.intervals[0][0 if lean > 0.0 else 1]
                distance = end - _dot(frame.center, frame.axes[0])
                return tuple(frame.center[index] + frame.axes[0][index] * distance for index in range(3))

            template_grip = grip_point(template, theirs)
            source_grip = placement.apply(grip_point(source, ours))
            placement = placement.with_values(
                offset=tuple(
                    placement.offset[index] + template_grip[index] - source_grip[index]
                    for index in range(3)
                )
            )
    return placement


def flip_v_transforms(mesh: object) -> Tuple[StaticTextureUvTransform, ...]:
    """A vertical UV flip for every material the mesh names: the build's equivalent of the
    Builder's Flip V, which a glTF, GLB, OBJ or DAE source needs (their V origin is the
    bottom, the game samples from the top). Keyed by material and by submesh name, the two
    keys the replacement pipeline matches on."""

    keys: list[str] = []
    seen: set[str] = set()
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for value in (getattr(submesh, "material", ""), getattr(submesh, "name", "")):
            key = str(value or "").strip()
            if key and key.casefold() not in seen:
                seen.add(key.casefold())
                keys.append(key)
    return tuple(StaticTextureUvTransform(source_material_name=key, flip_v=True) for key in keys)


def bake_mesh(
    mesh: object,
    placement: ModelPlacement,
    *,
    origin: Optional[Sequence[float]] = None,
) -> object:
    """A copy of `mesh` (a ParsedMesh) with `placement` applied to its vertices, and its
    normals and tangents turned with it (scale leaves directions alone, up to a renormalise).
    The copy keeps everything else: uvs, faces, bones, the preview texture attributes.
    ``origin`` selects the same fitted pivot Model & Placement and the final Builder use."""

    from cdmw.services.mesh_workflow_service import clone_mesh_for_editing

    baked = clone_mesh_for_editing(mesh)
    m = placement.matrix(origin=origin)

    position_matrix = (
        m[0], m[4], m[8], m[12],
        m[1], m[5], m[9], m[13],
        m[2], m[6], m[10], m[14],
    )
    target_indices = tuple(range(len(baked.submeshes)))
    native_changed = None
    try:
        from cdmw.services.mesh_workflow_service import apply_native_mesh_affine_transform_submeshes

        native_changed = apply_native_mesh_affine_transform_submeshes(
            baked.submeshes,
            position_matrices_by_index={index: position_matrix for index in target_indices},
            timeout_seconds=20.0,
        )
    except (OSError, RuntimeError, ValueError):
        native_changed = None

    try:
        import numpy as np
    except Exception:  # pragma: no cover - NumPy is bundled; scalar compatibility remains
        np = None

    linear = (
        (m[0], m[1], m[2]),
        (m[4], m[5], m[6]),
        (m[8], m[9], m[10]),
    )

    def array_directions(values):
        if np is None or not values or any(len(value) < 3 for value in values):
            return None
        source = np.asarray([value[:3] for value in values], dtype=np.float64)
        transformed = source @ np.asarray(linear, dtype=np.float64)
        lengths = np.linalg.norm(transformed, axis=1)
        live = lengths > 1e-12
        transformed[live] /= lengths[live, None]
        transformed[~live] = (0.0, 0.0, 1.0)
        return transformed

    def point(v):
        x, y, z = (float(c) for c in v[:3])
        return (x * m[0] + y * m[4] + z * m[8] + m[12], x * m[1] + y * m[5] + z * m[9] + m[13], x * m[2] + y * m[6] + z * m[10] + m[14])

    def direction(v):
        x, y, z = (float(c) for c in v[:3])
        out = (x * m[0] + y * m[4] + z * m[8], x * m[1] + y * m[5] + z * m[9], x * m[2] + y * m[6] + z * m[10])
        length = (out[0] * out[0] + out[1] * out[1] + out[2] * out[2]) ** 0.5
        return tuple(c / length for c in out) if length > 1e-12 else (0.0, 0.0, 1.0)

    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for index, submesh in enumerate(baked.submeshes):
        if native_changed is None or index not in native_changed:
            if np is not None and submesh.vertices:
                vertices = np.asarray([value[:3] for value in submesh.vertices], dtype=np.float64)
                transformed = vertices @ np.asarray(linear, dtype=np.float64)
                transformed += np.asarray((m[12], m[13], m[14]), dtype=np.float64)
                submesh.vertices = [tuple(value) for value in transformed.tolist()]
            else:
                submesh.vertices = [point(v) for v in submesh.vertices]
        normals = array_directions(submesh.normals)
        submesh.normals = (
            [tuple(value) for value in normals.tolist()]
            if normals is not None
            else [direction(n) if len(n) >= 3 else n for n in submesh.normals]
        )
        tangents = array_directions(submesh.tangents)
        submesh.tangents = (
            [(*value, *original[3:]) for value, original in zip(tangents.tolist(), submesh.tangents)]
            if tangents is not None
            else [(*direction(t), *t[3:]) if len(t) >= 3 else t for t in submesh.tangents]
        )
        for v in submesh.vertices:
            for axis in range(3):
                lo[axis] = min(lo[axis], v[axis])
                hi[axis] = max(hi[axis], v[axis])
    if lo[0] is not math.inf:
        baked.bbox_min = tuple(lo)
        baked.bbox_max = tuple(hi)
    return baked


# ------------------------------------------------------------------ the source


@dataclass
class ModelImportSource:
    """A model file read for the studio: the file the user chose, the importable model it
    resolved to (inside a zip's extract root when it was a zip), the scene import (mesh
    and the source's textures), a preview model with those textures bound for the
    viewport, and the bounds of the mesh as it came."""

    chosen_path: Path
    model_path: Path
    scene: object
    preview_model: object
    bounds: Optional[Bounds]
    preview_mesh: object = None
    source_fingerprint: str = ""
    external_texture_fingerprint: str = ""
    texture_count: int = 0
    notes: Tuple[str, ...] = ()
    extract_root: Optional[Path] = None
    #: True only when the loader created ``extract_root``. A caller-provided extraction
    #: directory belongs to that caller and must never be removed here.
    owns_extract_root: bool = False
    #: the mean vertex, for the fit's sense of which end is the heavy one
    centroid: Optional[Vec3] = None
    principal_frame: Optional[MeshPrincipalFrame] = None
    #: immutable template facts prepared with the import on its worker. Re-fit uses these
    #: instead of reading and parsing the template PAC again on the UI thread.
    fit_template_bounds: Optional[Bounds] = None
    fit_template_centroid: Optional[Vec3] = None
    fit_template_frame: Optional[MeshPrincipalFrame] = None
    fit_match_grip: bool = True
    #: the fit baked into the mesh the viewport and the build see; the numbers start at zero on top
    bake: ModelPlacement = field(default_factory=ModelPlacement)
    #: flip the source's textures vertically in the build. glTF, GLB, OBJ and DAE put V's
    #: origin at the bottom and the game samples it from the top, so a source in those
    #: formats needs the flip or its textures come out mirrored along the model. The
    #: Builder's own Flip V checkbox is the same switch.
    flip_texture_v: bool = False
    #: how many times the bake changed, for the viewport's token
    bake_generation: int = 0
    #: how many accepted Mesh Editor revisions changed the source geometry
    mesh_generation: int = 0
    #: the (bake, placement) the studio applied last, when a result was built from this source
    applied: Optional[Tuple[ModelPlacement, ModelPlacement]] = field(default=None)

    @property
    def label(self) -> str:
        return self.chosen_path.name

    @property
    def cache_identity(self) -> tuple:
        return (
            self.source_fingerprint or str(self.model_path.resolve(strict=False)),
            self.external_texture_fingerprint,
            MODEL_IMPORTER_SCHEMA_VERSION,
            MODEL_FIT_VERSION,
        )

    def set_bake(self, bake: ModelPlacement) -> None:
        """Take a new fit: the meshes are re-baked on the next read, the token moves on."""

        if bake == self.bake and self.bake_generation:
            return
        self.bake = bake
        self.bake_generation += 1
        self._baked_scene_mesh = None
        self._baked_preview_mesh = None

    def baked_origin(self) -> Vec3:
        """The source model's origin after its first fit was baked into the vertices."""

        return self.bake.apply((0.0, 0.0, 0.0))

    _baked_scene_mesh: object = field(default=None, repr=False)
    _baked_preview_mesh: object = field(default=None, repr=False)
    _usage_condition: threading.Condition = field(default_factory=threading.Condition, init=False, repr=False, compare=False)
    _active_usage_count: int = field(default=0, init=False, repr=False, compare=False)
    _retired: bool = field(default=False, init=False, repr=False, compare=False)

    def acquire_usage(self) -> Optional[_ModelImportUsage]:
        """Retain source files for one worker, unless this import was already retired."""

        with self._usage_condition:
            if self._retired:
                return None
            self._active_usage_count += 1
        return _ModelImportUsage(self)

    def usage(self) -> _ModelImportUsage:
        usage = self.acquire_usage()
        if usage is None:
            raise RunCancelled("Operation cancelled.")
        return usage

    def _release_usage(self) -> None:
        with self._usage_condition:
            if self._active_usage_count <= 0:
                return
            self._active_usage_count -= 1
            if self._active_usage_count == 0:
                self._usage_condition.notify_all()

    def retire(self) -> None:
        """Reject new users while existing preview/build workers finish."""

        with self._usage_condition:
            self._retired = True
            if self._active_usage_count == 0:
                self._usage_condition.notify_all()

    def wait_until_unused(self) -> None:
        """Block a cleanup worker, never the UI thread, until every usage is released."""

        with self._usage_condition:
            while self._active_usage_count:
                self._usage_condition.wait()

    def baked_scene_mesh(self) -> object:
        """The scene import's mesh with the bake applied (what the build rebuilds from)."""

        if self._baked_scene_mesh is None:
            self._baked_scene_mesh = bake_mesh(self.preview_mesh or self.scene.mesh, self.bake)
            if self.preview_mesh is not None:
                self._baked_preview_mesh = self._baked_scene_mesh
        return self._baked_scene_mesh

    def baked_preview_mesh(self) -> object:
        """The textured preview mesh with the bake applied (what the viewport shows)."""

        if self._baked_preview_mesh is None:
            if self.preview_mesh is not None:
                self._baked_preview_mesh = self.baked_scene_mesh()
            else:
                from cdmw.services.mesh_rust_preview_cache import parsed_mesh_from_model_preview

                self._baked_preview_mesh = bake_mesh(parsed_mesh_from_model_preview(self.preview_model), self.bake)
        return self._baked_preview_mesh

    def baked_bounds(self) -> Optional[Bounds]:
        mesh = self.baked_scene_mesh()
        return (tuple(mesh.bbox_min), tuple(mesh.bbox_max)) if mesh is not None and mesh.bbox_min is not None else None

    def cleanup(self) -> None:
        """Release an extraction directory created for this import, once."""

        root = self.extract_root
        if not self.owns_extract_root or root is None:
            return
        self.extract_root = None
        shutil.rmtree(root, ignore_errors=True)


def prepare_model_import_mesh_edit(
    mesh: object,
    *,
    scene: object,
    model_path: Path,
    stop_event: Optional[threading.Event] = None,
) -> tuple[object, object, MeshGeometryAnalysis, int]:
    """Prepare one Mesh Editor revision for New Item Studio off the UI thread.

    The edited mesh becomes a fresh scene/preview pair while the imported scene's
    texture bindings and supplemental-file context stay unchanged. The caller owns
    publication and must reject a result whose model or editor session went stale.
    """

    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.services.mesh_dotnet_material_state import set_dotnet_preview_texture_flip_vertical
    from cdmw.services.mesh_workflow_service import ParsedMesh
    from cdmw.services.preview_workflow_service import attach_scene_preview_textures, parsed_mesh_to_preview_model

    if not isinstance(mesh, ParsedMesh):
        raise TypeError("The Mesh Editor revision could not be captured safely.")
    if not tuple(mesh.submeshes or ()):
        raise ValueError("The Mesh Editor revision could not be captured safely.")
    raise_if_cancelled(stop_event)
    _name_separated_parts_uniquely(mesh)
    edited_scene = copy.copy(scene)
    setattr(edited_scene, "mesh", mesh)
    preview_model = parsed_mesh_to_preview_model(mesh)
    raise_if_cancelled(stop_event)
    texture_count = int(attach_scene_preview_textures(preview_model, edited_scene, Path(model_path)) or 0)
    from cdmw.services.mesh_workflow_service import copy_extra_submesh_attrs

    set_dotnet_preview_texture_flip_vertical(
        preview_model,
        scene_import_normalizes_texture_v(
            getattr(mesh, "format", ""),
            getattr(mesh, "path", "") or str(model_path),
        ),
    )
    for source, target in zip(
        tuple(getattr(preview_model, "meshes", ()) or ()),
        tuple(mesh.submeshes or ()),
    ):
        copy_extra_submesh_attrs(source, target)
    raise_if_cancelled(stop_event)
    return edited_scene, preview_model, analyze_mesh_geometry(mesh), texture_count


def _name_separated_parts_uniquely(mesh: object) -> None:
    """Give repeated face separations stable, independently addressable names.

    The generic Mesh Editor correctly inherits the source part's name for every
    separation. New Item needs distinct names because Glow and material routing are
    selected by part name; rename only topology-created parts, never source-authored
    duplicates.
    """

    seen: set[str] = set()
    for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        name = str(getattr(submesh, "name", "") or "").strip()
        separated = hasattr(submesh, "cdmw_mesh_edit_topology_source_submesh_index")
        if separated:
            base = name or str(getattr(submesh, "material", "") or "").strip() or f"part {index}"
            candidate = base
            suffix = 2
            while candidate.casefold() in seen:
                candidate = f"{base} {suffix}"
                suffix += 1
            if candidate != name:
                submesh.name = candidate
            name = candidate
        if name:
            seen.add(name.casefold())


#: What a model file might be that the studio cannot read, and what to do about it. FBX is
#: the one people actually arrive with: half the models on the asset sites ship as `source/
#: <name>.fbx` with the textures beside it, and "holds no importable model" reads like the
#: file is broken rather than like it is the wrong kind.
_UNREADABLE_MODEL_ADVICE: Mapping[str, str] = {
    ".fbx": "FBX",
    ".blend": "a Blender file",
    ".max": "a 3ds Max file",
    ".ma": "a Maya file",
    ".mb": "a Maya file",
    ".c4d": "a Cinema 4D file",
    ".skp": "a SketchUp file",
    ".usd": "USD",
    ".usdz": "USD",
    ".ply": "PLY",
    ".stl": "STL",
}


def _nothing_to_import(chosen: Path, root: Path) -> str:
    """Why nothing in `chosen` could be read, naming what was found where it helps."""

    from cdmw.domain.library.models import IMPORTABLE_MODEL_EXTENSIONS

    readable = ", ".join(sorted(extension.lstrip(".").upper() for extension in IMPORTABLE_MODEL_EXTENSIONS))
    names: list = [chosen]
    # a zip that holds nothing importable is never extracted, so its listing is the only
    # place the file inside it can be seen
    if chosen.suffix.casefold() == ".zip" and chosen.is_file():
        try:
            import zipfile

            with zipfile.ZipFile(chosen) as archive:
                names.extend(Path(name) for name in archive.namelist())
        except Exception:  # noqa: BLE001 - a zip that will not open says nothing extra
            pass
    if root.is_dir():
        names.extend(sorted(root.rglob("*")))
    found: list = []
    for candidate in names:
        kind = _UNREADABLE_MODEL_ADVICE.get(candidate.suffix.casefold())
        if kind and (candidate.name, kind) not in found:
            found.append((candidate.name, kind))
    if found:
        name, kind = found[0]
        if kind == "FBX":
            return fbx_needs_blender_message(name)
        return (
            f"{chosen.name} holds {name}, and the studio does not read {kind}. Export it as glTF, GLB, OBJ or DAE "
            f"-- Blender does that in a few seconds -- and import that instead."
        )
    return f"{chosen.name} holds no model the studio can read. It reads {readable}."


def fbx_needs_blender_message(name: str) -> str:
    """Why `name` cannot be read, and the two ways out of it."""

    return (
        f"{name} is an FBX, and the studio reads FBX by converting it with Blender. Choose blender.exe on the Model "
        f"step first, or export the model as glTF, GLB, OBJ or DAE yourself and import that."
    )


def fbx_needing_blender(chosen: object) -> str:
    """The FBX that would have to be converted before `chosen` can be read, or "".

    Answered from the name, and for a zip from its listing alone: nothing is extracted
    and nothing is run, because this is the question asked *before* an import starts. A
    zip that also holds a model the studio reads itself needs no Blender for it, so that
    answers "" and the import goes ahead on the model it can read.
    """

    from cdmw.domain.library.models import IMPORTABLE_MODEL_EXTENSIONS

    path = Path(str(chosen or ""))
    if path.suffix.casefold() == FBX_EXTENSION:
        return path.name
    inside = _fbx_inside(path)
    if not inside:
        return ""
    try:
        import zipfile

        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith("/") and Path(name).suffix.casefold() in IMPORTABLE_MODEL_EXTENSIONS:
                    return ""
    except Exception:  # noqa: BLE001 - a zip that will not open is the reader's next problem
        pass
    return Path(inside).name


def _fbx_inside(chosen: Path) -> str:
    """The first `.fbx` in a zip's listing, or "" -- read from the listing, because a zip
    holding nothing the studio reads is never extracted."""

    if chosen.suffix.casefold() != ".zip" or not chosen.is_file():
        return ""
    try:
        import zipfile

        with zipfile.ZipFile(chosen) as archive:
            for name in archive.namelist():
                if name.casefold().endswith(FBX_EXTENSION) and not name.endswith("/"):
                    return name
    except Exception:  # noqa: BLE001 - a zip that will not open holds nothing we can name
        return ""
    return ""


def _fbx_converted_to_glb(
    chosen: Path,
    root: Path,
    blender: object,
    on_log: Optional[Callable[[str], None]],
    stop_event: Optional[threading.Event],
) -> Optional[Path]:
    """`chosen`'s FBX as a GLB, or None when there is no FBX in it.

    A zip is extracted whole rather than by pattern: an FBX names its textures beside
    itself, and Blender needs them there to carry them into the GLB.
    """

    from cdmw.services.model_library_service import safe_extract_model_archive
    from cdmw.domain.cancellation import raise_if_cancelled

    inside = _fbx_inside(chosen)
    if chosen.suffix.casefold() == FBX_EXTENSION:
        source = chosen
    elif inside:
        root.mkdir(parents=True, exist_ok=True)
        safe_extract_model_archive(chosen, root, stop_event=stop_event)
        source = root / inside
        if not source.is_file():
            source = next((path for path in sorted(root.rglob("*")) if path.suffix.casefold() == FBX_EXTENSION), source)
    else:
        return None
    raise_if_cancelled(stop_event)
    return convert_fbx_to_glb(source, blender, output_dir=root, on_log=on_log).glb


def _file_fingerprint(path: Path, stop_event: Optional[threading.Event]) -> str:
    from cdmw.domain.cancellation import raise_if_cancelled

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            raise_if_cancelled(stop_event)
            digest.update(chunk)
    return digest.hexdigest()


def _preview_texture_fingerprint(preview_model: object, stop_event: Optional[threading.Event]) -> str:
    digest = hashlib.sha256()
    paths: set[Path] = set()
    for batch in tuple(getattr(preview_model, "meshes", ()) or ()):
        for name in (
            "preview_texture_path",
            "preview_texture_dds_path",
            "preview_normal_texture_path",
            "preview_normal_texture_dds_path",
            "preview_material_texture_path",
            "preview_material_texture_dds_path",
            "preview_height_texture_path",
            "preview_height_texture_dds_path",
            "preview_emissive_texture_path",
            "preview_emissive_texture_dds_path",
        ):
            value = str(getattr(batch, name, "") or "").strip()
            if value:
                paths.add(Path(value))
    for path in sorted(paths, key=lambda value: str(value).casefold()):
        digest.update(str(path.name).casefold().encode("utf-8", errors="replace"))
        if path.is_file():
            digest.update(_file_fingerprint(path, stop_event).encode("ascii"))
    return digest.hexdigest()


def load_model_import_source(
    chosen_path: Path,
    *,
    extract_root: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
    blender_path: object = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> ModelImportSource:
    """Read `chosen_path` (a model file, or a zip holding one) the way the Model Library
    does: resolve the importable model, run the scene import, bind the source's textures
    to a preview model. Raises ValueError when the file holds no importable model."""

    from cdmw.services.mesh_workflow_service import import_scene_mesh_with_report
    from cdmw.services.preview_workflow_service import attach_scene_preview_textures, parsed_mesh_to_preview_model
    from cdmw.services.preview_workflow_service import scene_import_normalizes_texture_v
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.domain.library.models import IMPORTABLE_MODEL_EXTENSIONS
    from cdmw.services.mesh_dotnet_material_state import set_dotnet_preview_texture_flip_vertical
    from cdmw.services.model_library_service import ModelLibraryService

    chosen = Path(chosen_path)
    owns_root = extract_root is None
    root = Path(extract_root) if extract_root is not None else Path(tempfile.mkdtemp(prefix="cdmw_new_item_model_"))
    try:
        model_path = ModelLibraryService().resolve_importable_model(chosen, extract_root=root, stop_event=stop_event)
        if model_path is None:
            # An FBX is read by asking Blender for it as glTF first, and only with the Blender
            # the reader pointed at: a conversion nobody asked for is one nobody can account
            # for when the result looks wrong.
            if chosen.suffix.casefold() == FBX_EXTENSION or _fbx_inside(chosen):
                model_path = _fbx_converted_to_glb(chosen, root, blender_path, on_log, stop_event)
            if model_path is None:
                raise ValueError(_nothing_to_import(chosen, root))
        raise_if_cancelled(stop_event)
        scene = import_scene_mesh_with_report(Path(model_path), include_external_audit=False)
        raise_if_cancelled(stop_event)
        preview_model = parsed_mesh_to_preview_model(scene.mesh)
        texture_count = int(attach_scene_preview_textures(preview_model, scene, Path(model_path)) or 0)
        from cdmw.services.mesh_workflow_service import copy_extra_submesh_attrs

        set_dotnet_preview_texture_flip_vertical(
            preview_model, scene_import_normalizes_texture_v(getattr(scene.mesh, "format", ""), getattr(scene.mesh, "path", "") or str(model_path)),
        )
        for source, target in zip(
            tuple(getattr(preview_model, "meshes", ()) or ()),
            tuple(getattr(scene.mesh, "submeshes", ()) or ()),
        ):
            copy_extra_submesh_attrs(source, target)
        notes = tuple(str(line) for line in tuple(getattr(scene, "diagnostics", ()) or ())[:6])
        flip_v = scene_import_normalizes_texture_v(getattr(scene.mesh, "format", ""), getattr(scene.mesh, "path", "") or str(model_path))
        analysis = analyze_mesh_geometry(scene.mesh)
        source_fingerprint = _file_fingerprint(Path(model_path), stop_event)
        texture_fingerprint = _preview_texture_fingerprint(preview_model, stop_event)
        return ModelImportSource(
            flip_texture_v=bool(flip_v),
            chosen_path=chosen,
            model_path=Path(model_path),
            scene=scene,
            preview_model=preview_model,
            bounds=analysis.bounds,
            preview_mesh=scene.mesh,
            source_fingerprint=source_fingerprint,
            external_texture_fingerprint=texture_fingerprint,
            texture_count=texture_count,
            notes=notes,
            extract_root=root,
            owns_extract_root=owns_root,
            centroid=analysis.centroid,
            principal_frame=analysis.principal_frame,
        )
    except BaseException:
        if owns_root:
            shutil.rmtree(root, ignore_errors=True)
        raise


# ------------------------------------------------------------------ the build


def build_placed_import(
    entry: ArchiveEntry,
    source: ModelImportSource,
    placement: ModelPlacement,
    *,
    entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    attachment_prefab_data: bytes = b"",
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
):
    """The Builder's import over the template's mesh `entry`, headless: the Full Import
    Model Replacement (the imported model owns the visible mesh, the generated textures
    and the material sidecar; the studio's plain-PBR route rewrites that sidecar's
    wrappers to the plain shaders afterwards) of the source's baked mesh at exactly
    `placement` (the preset's own automatic alignment is replaced by the manual
    transform). Returns the `MeshImportPreviewResult` the Builder's dialog would have
    handed over."""

    from dataclasses import replace as dc_replace

    from cdmw.services.preview_workflow_service import build_mesh_import_preview
    from cdmw.services.mesh_workflow_service import apply_full_import_model_replacement_preset
    from cdmw.services.new_item_variants import bind_static_import_to_attachment

    options = dc_replace(
        apply_full_import_model_replacement_preset(),
        transform=placement.build_transform(origin=source.baked_origin()),
        texture_uv_transforms=list(flip_v_transforms(source.scene.mesh) if source.flip_texture_v else ()),
    )
    if on_progress is not None:
        on_progress(0, 11, "Transform mesh")
    scene = dc_replace(source.scene, mesh=bind_static_import_to_attachment(
        source.baked_scene_mesh(), entry.path, attachment_prefab_data,
    ))

    def forward_progress(current: int, total: int, detail: str) -> None:
        if on_progress is not None:
            on_progress(int(current) + 1, int(total) + 1, detail)

    return build_mesh_import_preview(
        entry,
        Path(source.model_path),
        import_mode="static_replacement",
        static_replacement_options=options,
        scene_import_result=scene,
        source_display_label=source.label,
        archive_entries_by_normalized_path=entries_by_normalized_path,
        texture_entries_by_normalized_path=entries_by_normalized_path,
        texture_entries_by_basename=entries_by_basename,
        stop_event=stop_event,
        on_progress=forward_progress,
    )
