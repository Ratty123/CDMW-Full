"""Pure authored-target and fitting-recipe identity rules.

Targets use the exact native float32 neutral coordinates, vertex order, faces,
and available source/skin identity. No mesh parsing, file I/O, or fitting runs here.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import math
import struct
from typing import Iterable

from cdmw.core.streaming_json import write_json

from .morph import (
    MeshMorphDefinition,
    MeshMorphFittingRecipe,
    MeshMorphRule,
    MeshMorphSparseField,
    MeshMorphVertexWeight,
    Vec3,
    _point3,
    _strict_mesh_index,
    generate_procedural_morph_fields,
    mesh_morph_driver_topology_fingerprint,
    mesh_topology_fingerprint,
    procedural_morph_pivot,
)


def _parts(mesh: object, submesh_indices: Iterable[int]) -> tuple[tuple[int, object], ...]:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    indices = tuple(_strict_mesh_index(item, "Morph identity submesh") for item in submesh_indices)
    if not indices or len(set(indices)) != len(indices):
        raise ValueError("Morph identity requires nonempty unique part indices.")
    result = []
    for index in sorted(indices):
        if index >= len(submeshes):
            raise ValueError("Morph identity submesh is out of range.")
        part = submeshes[index]
        positions = tuple(getattr(part, "vertices", ()) or ())
        if not positions:
            raise ValueError("Morph identity has an empty part.")
        for raw_face in tuple(getattr(part, "faces", ()) or ()):
            face = tuple(raw_face)
            if len(face) != 3:
                raise ValueError("Morph identity requires exact triangle topology.")
            if any(_strict_mesh_index(vertex, "Morph face vertex") >= len(positions) for vertex in face):
                raise ValueError("Morph topology references an out-of-range vertex.")
        result.append((index, part))
    return tuple(result)


def mesh_morph_role_topology_fingerprint(mesh: object, submesh_indices: Iterable[int]) -> str:
    """Validate selected roles, then hash their exact ordered triangle topology."""
    parts = _parts(mesh, submesh_indices)
    return mesh_topology_fingerprint(mesh, (index for index, _part in parts))


def _source_identity(part: object) -> bytes:
    payload = {
        name: getattr(part, name, default)
        for name, default in (
            ("source_vertex_map", ()),
            ("source_vertex_map_authority", ""),
            ("source_bone_palette", ()),
            ("source_skin_weight_layout", ""),
            ("bone_indices", ()),
            ("bone_weights", ()),
            ("interchange_skin", {}),
        )
    }
    try:
        buffer = io.BytesIO()

        class Sink:
            def write(self, text):
                buffer.write(text.encode("utf-8"))

        write_json(Sink(), payload)
        return buffer.getvalue()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Morph source/skin identity contains invalid or non-finite data.") from exc


def _native_point(value: object) -> Vec3:
    point = _point3(value)
    try:
        packed = struct.pack("<3f", *point)
    except (struct.error, OverflowError) as exc:
        raise ValueError("Morph geometry is outside the native coordinate range.") from exc
    native = struct.unpack("<3f", packed)
    if not all(math.isfinite(component) for component in native):
        raise ValueError("Morph geometry is outside the finite native coordinate range.")
    return tuple(0.0 if component == 0.0 else component for component in native)  # type: ignore[return-value]


def mesh_morph_base_fingerprint(mesh: object, submesh_indices: Iterable[int]) -> str:
    """Hash neutral geometry and source/skin identity at native float32 precision."""
    parts = _parts(mesh, submesh_indices)
    digest = hashlib.sha256(b"cdmw.morph-native-base.v1\0")
    digest.update(mesh_topology_fingerprint(mesh, (index for index, _part in parts)).encode("ascii"))
    for index, part in parts:
        digest.update(struct.pack("<I", index))
        identity = _source_identity(part)
        digest.update(struct.pack("<Q", len(identity)))
        digest.update(identity)
        for point in tuple(getattr(part, "vertices", ()) or ()):
            digest.update(struct.pack("<3f", *_native_point(point)))
    return digest.hexdigest()



def _validate_morph_target_parts(
    base_mesh: object,
    target_mesh: object,
    submesh_indices: Iterable[int],
    *,
    require_source_mapping: bool,
) -> tuple[tuple[tuple[int, object], ...], tuple[tuple[int, object], ...]]:
    if len(tuple(getattr(base_mesh, "submeshes", ()) or ())) != len(tuple(getattr(target_mesh, "submeshes", ()) or ())):
        raise ValueError("Authored target part count differs from the captured baseline.")
    indices = tuple(submesh_indices)
    base_parts = _parts(base_mesh, indices)
    target_parts = _parts(target_mesh, indices)
    if mesh_topology_fingerprint(base_mesh, indices) != mesh_topology_fingerprint(target_mesh, indices):
        raise ValueError("Authored target topology differs from the captured baseline.")
    for (_index, base), (_target_index, target) in zip(base_parts, target_parts):
        for part in (base, target):
            source_map = tuple(getattr(part, "source_vertex_map", ()) or ())
            if not source_map:
                if require_source_mapping:
                    raise ValueError("Authored target source vertex mapping is unavailable.")
                continue
            if len(source_map) != len(part.vertices):
                raise ValueError("Authored target source vertex mapping is incomplete.")
            for vertex in source_map:
                _strict_mesh_index(vertex, "Authored target source vertex mapping")
        if _source_identity(base) != _source_identity(target):
            raise ValueError("Authored target source/skin identity differs from the captured baseline.")
    return base_parts, target_parts


def validate_morph_target_identity(
    base_mesh: object,
    target_mesh: object,
    *,
    submesh_indices: Iterable[int],
    require_source_mapping: bool = False,
) -> None:
    """Check exact indexed identity while permitting position and normal edits.

    Every replacement must retain the total part count. Selected parts must
    retain ordered topology and source/skin metadata. Any available source map
    must be complete and valid. External targets may require explicit mapping;
    an acknowledged native sculpt can retain an existing absent map.
    """
    _validate_morph_target_parts(
        base_mesh, target_mesh, submesh_indices,
        require_source_mapping=require_source_mapping,
    )


def build_morph_sparse_difference(
    base_mesh: object,
    target_mesh: object,
    *,
    definition_id: str,
    submesh_indices: Iterable[int],
) -> tuple[MeshMorphSparseField, ...]:
    """Capture exact-index target differences; never guess correspondence."""
    base_parts, target_parts = _validate_morph_target_parts(
        base_mesh, target_mesh, submesh_indices, require_source_mapping=False,
    )
    fields = []
    for (submesh_index, base), (_target_index, target) in zip(base_parts, target_parts):
        entries = []
        for index, (left, right) in enumerate(zip(base.vertices, target.vertices)):
            source = _native_point(left)
            destination = _native_point(right)
            delta = tuple(destination[axis] - source[axis] for axis in range(3))
            if any(component != 0.0 for component in delta):
                entries.append((index, delta))
        if entries:
            fields.append(MeshMorphSparseField(
                definition_id=definition_id,
                submesh_index=submesh_index,
                vertex_indices=tuple(item[0] for item in entries),
                deltas=tuple(item[1] for item in entries),
            ))
    return tuple(fields)


def create_authored_morph_definition(
    base_mesh: object,
    target_mesh: object,
    *,
    definition_id: str,
    label: str,
    category: str = "Authored",
    submesh_indices: Iterable[int],
    min_percent: float = -100.0,
    max_percent: float = 100.0,
    default_percent: float = 0.0,
) -> MeshMorphDefinition:
    """Author a sparse 100-percent body target from a captured neutral baseline."""
    fields = build_morph_sparse_difference(
        base_mesh, target_mesh, definition_id=definition_id, submesh_indices=submesh_indices,
    )
    if not fields:
        raise ValueError("No body vertex changes were found for the authored slider.")
    vertices = tuple(
        MeshMorphVertexWeight(item.submesh_index, index, 1.0)
        for item in fields for index in item.vertex_indices
    )
    return MeshMorphDefinition(
        definition_id=definition_id,
        label=label,
        category=category,
        vertices=vertices,
        pivot=procedural_morph_pivot(base_mesh, vertices),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule(kind="move", amount=0.0, feather=0),
        source_kind="authored",
        authored_fields=fields,
        base_geometry_fingerprint=mesh_morph_base_fingerprint(base_mesh, (item.submesh_index for item in fields)),
        min_percent=min_percent,
        max_percent=max_percent,
        default_percent=default_percent,
    )


def validate_morph_definition_geometry(base_mesh: object, definition: MeshMorphDefinition) -> None:
    """Reject targets/corrections for a different native neutral mesh or ordering."""
    if definition.source_kind == "authored":
        indices = tuple(item.submesh_index for item in definition.authored_fields)
        if definition.base_geometry_fingerprint != mesh_morph_base_fingerprint(base_mesh, indices):
            raise ValueError("Authored slider base geometry or source/skin identity does not match.")
    if definition.garment_corrections:
        indices = tuple(item.submesh_index for item in definition.garment_corrections)
        if definition.correction_topology_fingerprint != mesh_morph_role_topology_fingerprint(base_mesh, indices):
            raise ValueError("Garment correction topology does not match.")
        if definition.correction_base_geometry_fingerprint != mesh_morph_base_fingerprint(base_mesh, indices):
            raise ValueError("Garment correction base geometry or source/skin identity does not match.")
    submeshes = tuple(getattr(base_mesh, "submeshes", ()) or ())
    for field in (*definition.authored_fields, *definition.garment_corrections):
        if field.submesh_index >= len(submeshes) or any(index >= len(submeshes[field.submesh_index].vertices) for index in field.vertex_indices):
            raise ValueError("Authored sparse field vertex is out of range.")


def generate_morph_fields(base_mesh: object, definition: MeshMorphDefinition) -> tuple[MeshMorphSparseField, ...]:
    """Return body fields; garment corrections are uploaded in the post-refit stage."""
    validate_morph_definition_geometry(base_mesh, definition)
    if definition.source_kind == "authored":
        return definition.authored_fields
    return generate_procedural_morph_fields(base_mesh, definition)


def with_morph_garment_corrections(
    definition: MeshMorphDefinition,
    base_mesh: object,
    fields: Iterable[MeshMorphSparseField],
) -> MeshMorphDefinition:
    """Replace a slider's corrections with identity-bound post-refit fields."""
    corrections = tuple(fields)
    indices = tuple(item.submesh_index for item in corrections)
    return replace(
        definition,
        garment_corrections=corrections,
        correction_topology_fingerprint=mesh_morph_role_topology_fingerprint(base_mesh, indices) if corrections else "",
        correction_base_geometry_fingerprint=mesh_morph_base_fingerprint(base_mesh, indices) if corrections else "",
    )


def validate_mesh_morph_fitting_recipe(mesh: object, recipe: MeshMorphFittingRecipe) -> None:
    """Validate every role, mask and restricted surface before a recipe mutates state."""
    indices = tuple(sorted(set(recipe.driver_submesh_indices).union(item.submesh_index for item in recipe.garment_settings)))
    if recipe.topology_fingerprint != mesh_morph_role_topology_fingerprint(mesh, indices):
        raise ValueError("Fitting recipe role topology does not match the loaded parts.")
    if recipe.base_geometry_fingerprint != mesh_morph_base_fingerprint(mesh, indices):
        raise ValueError("Fitting recipe neutral geometry or source/skin identity does not match.")
    if recipe.profile.topology_fingerprint != mesh_morph_driver_topology_fingerprint(mesh, recipe.profile.definitions):
        raise ValueError("Fitting recipe profile driver topology does not match.")
    for definition in recipe.profile.definitions:
        validate_morph_definition_geometry(mesh, definition)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    for settings in recipe.garment_settings:
        if settings.island_settings:
            from .islands import mesh_islands
            groups = mesh_islands(submeshes[settings.submesh_index])
            if any(island.face_indices not in groups for island in settings.island_settings):
                raise ValueError("Fitting recipe island overrides must identify whole source islands.")
        if settings.vertex_mask is not None and any(index >= len(submeshes[settings.submesh_index].vertices) for index, _weight in settings.vertex_mask):
            raise ValueError("Fitting recipe mask vertex is out of range.")
        if settings.vertex_mask is not None:
            part = submeshes[settings.submesh_index]
            weights = dict(settings.vertex_mask)
            overrides = {face: island for island in settings.island_settings for face in island.face_indices}
            for face_index, face in enumerate(part.faces):
                effective = overrides.get(face_index, settings)
                if not effective.enabled or effective.mode != "rigid_component":
                    continue
                values = [weights.get(index, 0.0) for index in face]
                if max(values) - min(values) > 1e-8:
                    raise ValueError("Rigid component masks must be uniform within each connected component.")
    for _garment_index, regions in recipe.garment_regions:
        triangle_count = 0
        for region in regions:
            part = submeshes[region.submesh_index]
            selected = set(region.vertex_indices)
            if max(selected) >= len(part.vertices):
                raise ValueError("Fitting recipe driver region vertex is out of range.")
            triangle_count += sum(all(index in selected for index in face) for face in part.faces)
        if regions and not triangle_count:
            raise ValueError("Fitting recipe driver regions contain no complete triangles.")


__all__ = [
    "build_morph_sparse_difference",
    "create_authored_morph_definition",
    "generate_morph_fields",
    "mesh_morph_base_fingerprint",
    "mesh_morph_role_topology_fingerprint",
    "validate_mesh_morph_fitting_recipe",
    "validate_morph_definition_geometry",
    "validate_morph_target_identity",
    "with_morph_garment_corrections",
]
