"""New Item Studio: a model of the user's own, placed over the template in the studio itself.

The Model and icon step takes a model file (glTF, GLB, OBJ, DAE, or a zip holding one),
reads it the way the Model Library does (the scene import, the source's own textures), and
shows it in the step's viewport over the template's mesh, where the gizmo and the numbers
place it. Two layers: the *fit* (`fitted_placement`: scaled to the template's length, turned
onto its axes, and centred or grip-aligned for the template family) is baked into the mesh
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
from cdmw.core.model_preview_orientation import scene_import_normalizes_texture_v
from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions, StaticReplacementTransform, StaticTextureUvTransform

__all__ = [
    "ModelImportSource",
    "ModelPlacement",
    "Vec3",
    "bake_mesh",
    "build_placed_import",
    "flip_v_transforms",
    "fitted_placement",
    "load_model_import_source",
    "mesh_bounds",
    "mesh_centroid",
    "prepare_model_import_mesh_edit",
]

Vec3 = Tuple[float, float, float]
Bounds = Tuple[Vec3, Vec3]


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


def mesh_bounds(mesh: object) -> Optional[Bounds]:
    """The axis-aligned bounds of a ParsedMesh (or anything with `submeshes` carrying
    `vertices`); None when there is no vertex."""

    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for vertex in tuple(getattr(submesh, "vertices", ()) or ()):
            for axis in range(3):
                value = float(vertex[axis])
                if value < lo[axis]:
                    lo[axis] = value
                if value > hi[axis]:
                    hi[axis] = value
    if lo[0] is math.inf or hi[0] == -math.inf:
        return None
    return (tuple(lo), tuple(hi))


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
            for axis in range(3):
                total[axis] += float(vertex[axis])
            count += 1
    if not count:
        return None
    return tuple(value / count for value in total)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def fitted_placement(
    source_bounds: Optional[Bounds],
    template_bounds: Optional[Bounds],
    *,
    source_centroid: Optional[Vec3] = None,
    template_centroid: Optional[Vec3] = None,
    match_grip: bool = True,
) -> ModelPlacement:
    """A first placement: scale uniformly to the template's longest extent, turn by right
    angles so the long and middle axes match, then centre the bounding boxes. Weapon
    families additionally use the two centroids to point their heavy ends the same way
    and align the opposite grip ends. Armour and accessories keep the generic centred
    fit, without treating one end as a handle. The user takes it from there."""

    if source_bounds is None or template_bounds is None:
        return ModelPlacement()
    s_lo, s_hi = source_bounds
    t_lo, t_hi = template_bounds
    s_ext = tuple(max(0.0, s_hi[i] - s_lo[i]) for i in range(3))
    t_ext = tuple(max(0.0, t_hi[i] - t_lo[i]) for i in range(3))
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

    from cdmw.modding.mesh_deformer import clone_mesh_for_editing

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
    texture_count: int = 0
    notes: Tuple[str, ...] = ()
    extract_root: Optional[Path] = None
    #: True only when the loader created ``extract_root``. A caller-provided extraction
    #: directory belongs to that caller and must never be removed here.
    owns_extract_root: bool = False
    #: the mean vertex, for the fit's sense of which end is the heavy one
    centroid: Optional[Vec3] = None
    #: immutable template facts prepared with the import on its worker. Re-fit uses these
    #: instead of reading and parsing the template PAC again on the UI thread.
    fit_template_bounds: Optional[Bounds] = None
    fit_template_centroid: Optional[Vec3] = None
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
            self._baked_scene_mesh = bake_mesh(self.scene.mesh, self.bake)
        return self._baked_scene_mesh

    def baked_preview_mesh(self) -> object:
        """The textured preview mesh with the bake applied (what the viewport shows)."""

        if self._baked_preview_mesh is None:
            from cdmw.services.mesh_dotnet_preview_package import parsed_mesh_from_model_preview

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
) -> tuple[object, object, Optional[Bounds], Optional[Vec3], int]:
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
    set_dotnet_preview_texture_flip_vertical(
        preview_model,
        scene_import_normalizes_texture_v(
            getattr(mesh, "format", ""),
            getattr(mesh, "path", "") or str(model_path),
        ),
    )
    raise_if_cancelled(stop_event)
    return edited_scene, preview_model, mesh_bounds(mesh), mesh_centroid(mesh), texture_count


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

    from cdmw.core.model_catalogue import safe_extract_zip
    from cdmw.domain.cancellation import raise_if_cancelled

    inside = _fbx_inside(chosen)
    if chosen.suffix.casefold() == FBX_EXTENSION:
        source = chosen
    elif inside:
        root.mkdir(parents=True, exist_ok=True)
        safe_extract_zip(chosen, root, stop_event=stop_event)
        source = root / inside
        if not source.is_file():
            source = next((path for path in sorted(root.rglob("*")) if path.suffix.casefold() == FBX_EXTENSION), source)
    else:
        return None
    raise_if_cancelled(stop_event)
    return convert_fbx_to_glb(source, blender, output_dir=root, on_log=on_log).glb


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
    from cdmw.core.model_preview_orientation import scene_import_normalizes_texture_v
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
        set_dotnet_preview_texture_flip_vertical(
            preview_model, scene_import_normalizes_texture_v(getattr(scene.mesh, "format", ""), getattr(scene.mesh, "path", "") or str(model_path)),
        )
        notes = tuple(str(line) for line in tuple(getattr(scene, "diagnostics", ()) or ())[:6])
        flip_v = scene_import_normalizes_texture_v(getattr(scene.mesh, "format", ""), getattr(scene.mesh, "path", "") or str(model_path))
        return ModelImportSource(
            flip_texture_v=bool(flip_v),
            chosen_path=chosen,
            model_path=Path(model_path),
            scene=scene,
            preview_model=preview_model,
            bounds=mesh_bounds(scene.mesh),
            texture_count=texture_count,
            notes=notes,
            extract_root=root,
            owns_extract_root=owns_root,
            centroid=mesh_centroid(scene.mesh),
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
    from cdmw.modding.full_import_model_replacement import apply_full_import_model_replacement_preset

    options = dc_replace(
        apply_full_import_model_replacement_preset(),
        transform=placement.build_transform(origin=source.baked_origin()),
        texture_uv_transforms=list(flip_v_transforms(source.scene.mesh) if source.flip_texture_v else ()),
    )
    if on_progress is not None:
        on_progress(0, 11, "Transform mesh")
    scene = dc_replace(source.scene, mesh=bake_mesh(source.scene.mesh, source.bake))

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
