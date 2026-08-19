"""New Item Studio: a model of the user's own, placed over the template in the studio itself.

The Model and icon step takes a model file (glTF, GLB, OBJ, DAE, or a zip holding one),
reads it the way the Model Library does (the scene import, the source's own textures), and
shows it in the step's viewport over the template's mesh, where the gizmo and the numbers
place it. Two layers: the *fit* (`fitted_placement`: scaled to the template's length, turned
onto its axes, centred on it) is baked into the mesh itself (`bake_mesh`), so the numbers
the user sees and the gizmo moves start at zero and a ring drag turns the model about a
world axis, the way the Mesh Editor's does; the *placement* on top is one convention
everywhere: scale, then the rotations about x, y and z, then the offset, all about the
baked model's origin (the hand, for a weapon). The helper composes a gizmo drag that way
(`ManualLinearMatrix`), the host's fallback matrix does, and so does the static
replacement pipeline (`_rotate_xyz`), so `ModelPlacement.build_transform()` hands the
numbers over as they are. Applying the placement runs the Builder's import headlessly over
the baked mesh (`build_placed_import`), and what comes back is what the Builder's dialog
would have handed over: the rebuilt mesh and its side files.
"""

from __future__ import annotations

import math
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from cdmw.models import ArchiveEntry
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
]

Vec3 = Tuple[float, float, float]
Bounds = Tuple[Vec3, Vec3]


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

    def matrix(self) -> list:
        """The 4 x 4 row-vector matrix the viewport composes for this placement."""

        from cdmw.ui.preview.dotnet_host import _placement_matrix

        return _placement_matrix(self.offset, self.rotation, self.scale)

    def apply(self, point: Sequence[float]) -> Vec3:
        """`point` under the placement (row vector times the matrix)."""

        m = self.matrix()
        x, y, z = (float(v) for v in point[:3])
        return (
            x * m[0] + y * m[4] + z * m[8] + m[12],
            x * m[1] + y * m[5] + z * m[9] + m[13],
            x * m[2] + y * m[6] + z * m[10] + m[14],
        )

    def build_transform(self) -> StaticReplacementTransform:
        """The static replacement pipeline's transform for this placement: manual mode
        (no anchor, no auto scale, no fit), the same scale, rotation and offset."""

        return StaticReplacementTransform(
            rotate_xyz_degrees=tuple(float(v) for v in self.rotation),
            scale=1.0,
            scale_xyz=tuple(float(v) for v in self.scale),
            offset_xyz=tuple(float(v) for v in self.offset),
            fit_to_original_bbox=False,
            scale_to_original_length=False,
            alignment_mode="manual",
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
) -> ModelPlacement:
    """A first placement: the source scaled (uniformly) so its longest extent matches the
    template's, turned by right angles so its long axis lies along the template's long
    axis and its middle axis along the template's middle one (a blade's face the way the
    template's faces), pointing the way the template points when both centroids say
    which end is the heavy one (a hilt), and moved so the two bounding-box centres
    coincide. The user takes it from there."""

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
        if s_lean is not None and t_lean is not None:
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
    return placement.with_values(offset=tuple(t_centre[i] - moved[i] for i in range(3)))


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


def bake_mesh(mesh: object, placement: ModelPlacement) -> object:
    """A copy of `mesh` (a ParsedMesh) with `placement` applied to its vertices, and its
    normals and tangents turned with it (scale leaves directions alone, up to a renormalise).
    The copy keeps everything else: uvs, faces, bones, the preview texture attributes."""

    from cdmw.modding.mesh_deformer import clone_mesh_for_editing

    baked = clone_mesh_for_editing(mesh)
    m = placement.matrix()

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
    for submesh in baked.submeshes:
        submesh.vertices = [point(v) for v in submesh.vertices]
        submesh.normals = [direction(n) if len(n) >= 3 else n for n in submesh.normals]
        submesh.tangents = [
            (*direction(t), *t[3:]) if len(t) >= 3 else t
            for t in submesh.tangents
        ]
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
    #: the mean vertex, for the fit's sense of which end is the heavy one
    centroid: Optional[Vec3] = None
    #: the fit baked into the mesh the viewport and the build see; the numbers start at zero on top
    bake: ModelPlacement = field(default_factory=ModelPlacement)
    #: flip the source's textures vertically in the build. glTF, GLB, OBJ and DAE put V's
    #: origin at the bottom and the game samples it from the top, so a source in those
    #: formats needs the flip or its textures come out mirrored along the model. The
    #: Builder's own Flip V checkbox is the same switch.
    flip_texture_v: bool = False
    #: how many times the bake changed, for the viewport's token
    bake_generation: int = 0
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

    _baked_scene_mesh: object = field(default=None, repr=False)
    _baked_preview_mesh: object = field(default=None, repr=False)

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


def load_model_import_source(chosen_path: Path, *, extract_root: Optional[Path] = None, stop_event: Optional[threading.Event] = None) -> ModelImportSource:
    """Read `chosen_path` (a model file, or a zip holding one) the way the Model Library
    does: resolve the importable model, run the scene import, bind the source's textures
    to a preview model. Raises ValueError when the file holds no importable model."""

    from cdmw.core.archive_modding import attach_scene_preview_textures, import_scene_mesh_with_report, parsed_mesh_to_preview_model
    from cdmw.core.model_preview_orientation import scene_import_normalizes_texture_v
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.domain.library.models import IMPORTABLE_MODEL_EXTENSIONS
    from cdmw.services.mesh_dotnet_material_state import set_dotnet_preview_texture_flip_vertical
    from cdmw.services.model_library_service import ModelLibraryService

    chosen = Path(chosen_path)
    root = Path(extract_root) if extract_root is not None else Path(tempfile.mkdtemp(prefix="cdmw_new_item_model_"))
    model_path = ModelLibraryService().resolve_importable_model(chosen, extract_root=root, stop_event=stop_event)
    if model_path is None:
        raise ValueError(f"{chosen.suffix or 'This file'} holds no importable model ({', '.join(sorted(IMPORTABLE_MODEL_EXTENSIONS))}).")
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
        centroid=mesh_centroid(scene.mesh),
    )


# ------------------------------------------------------------------ the build


def build_placed_import(
    entry: ArchiveEntry,
    source: ModelImportSource,
    placement: ModelPlacement,
    *,
    entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    stop_event: Optional[threading.Event] = None,
):
    """The Builder's import over the template's mesh `entry`, headless: the Full Import
    Model Replacement (the imported model owns the visible mesh, the generated textures
    and the material sidecar; the studio's plain-PBR route rewrites that sidecar's
    wrappers to the plain shaders afterwards) of the source's baked mesh at exactly
    `placement` (the preset's own automatic alignment is replaced by the manual
    transform). Returns the `MeshImportPreviewResult` the Builder's dialog would have
    handed over."""

    from dataclasses import replace as dc_replace

    from cdmw.core.archive_mesh_import_build import build_mesh_import_preview
    from cdmw.modding.full_import_model_replacement import apply_full_import_model_replacement_preset

    options = dc_replace(
        apply_full_import_model_replacement_preset(),
        transform=placement.build_transform(),
        texture_uv_transforms=list(flip_v_transforms(source.scene.mesh) if source.flip_texture_v else ()),
    )
    scene = dc_replace(source.scene, mesh=bake_mesh(source.scene.mesh, source.bake))
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
    )
