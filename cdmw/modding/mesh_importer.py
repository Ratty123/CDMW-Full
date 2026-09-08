"""Compatibility facade for mesh round-trip import and rebuild helpers."""

from __future__ import annotations

import copy
import math
import dataclasses
import hashlib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field

from cdmw.domain.mesh.operations import (
    MeshEditOperation,
    mesh_edit_operation_changed_channel,
    mesh_edit_operations_from_dicts,
    mesh_edit_operations_to_dicts,
    validate_mesh_edit_operation_coverage,
    validate_mesh_edit_operations,
)

from .mesh_parser import ParsedMesh, parse_pac, parse_pam, parse_pamlod
from .mesh_builder_common import (
    _align_static_vertex_sequences,
    _align_submesh_order_like_original,
    _apply_quantized_vertex_patches,
    _build_spatial_hash,
    _choose_static_donor_indices,
    _combine_static_submeshes,
    _collect_vertex_offset_refs,
    _compute_bbox,
    _expand_bbox_to_vertices,
    _make_temp_mesh,
    _make_vertex_template_record,
    _merge_partial_static_import,
    _nearby_point_indices,
    _nearest_point_index,
    _pack_static_vertex_record,
    _percentile,
    _quantize_u16,
    _replace_all_in_region,
    _reorder_submeshes_to_match_original,
    _resolve_pam_alias_vertex,
    _spatial_cell_key,
    _static_alignment_match_cost,
    _static_submesh_match_score,
    _submesh_uvs_match,
)
from .mesh_obj_importer import (
    _load_obj_material_texture_map,
    _load_obj_roundtrip_sidecar,
    _match_obj_roundtrip_sidecar_submeshes,
    _normalize_obj_sidecar_source_vertex_map,
    _obj_texture_key,
    _validate_obj_sidecar_topology,
    _normalize_obj_sidecar_texture_name,
    _obj_roundtrip_sidecar_candidates,
    _resolve_obj_index,
    _resolve_obj_material_library_paths,
    import_obj,
    validate_obj_sidecar_source_identity,
)
from cdmw.domain.mesh.topology import topology_contract_submesh_indices

from .mesh_pac_topology_builder import build_pac_topology_rebuild
from .mesh_pac_builder import (
    _append_pac_cloned_descriptors,
    _build_pac_full_rebuild,
    _build_pac_in_place,
    _build_pac_output_descriptors,
    _choose_pac_donor_indices,
    _format_roundtrip_topology_error,
    _length_prefixed_ascii,
    _merge_partial_pac_import,
    _pac_descriptor_record_length,
    _pac_lod_submesh_variant,
    _pac_lod_variants_for_submesh,
    _pac_needs_full_rebuild,
    _pac_submesh_match_score,
    _pack_pac_normal,
    _patch_pac_descriptor_bounds,
    _quantize_pac_u16,
    build_pac,
)
from .mesh_pac_legacy_builder import _rebuild_pac_section0, build_pac as _legacy_build_pac
from .mesh_pam_builder import (
    _inspect_pam_layout,
    _pam_needs_full_rebuild,
    _serialize_pam_backward_scan_combined_layout,
    _serialize_pam_combined_layout,
    _serialize_pam_local_layout,
    _serialize_pam_scan_combined_layout,
    _sync_pam_geom_size_header,
    _sync_pam_header_mirrors,
    build_pam,
)
from .mesh_pamlod_builder import (
    _inspect_pamlod_lod0_layout,
    _pamlod_lod0_original_parts,
    _pamlod_needs_full_rebuild,
    _serialize_pamlod_lod0_full_rebuild,
    _split_pamlod_lod0_edit_by_entries,
    build_pamlod,
    transfer_pam_edit_to_pamlod_mesh,
)


@dataclass(frozen=True, slots=True)
class MeshRebuildReport:
    mesh_format: str
    source_asset_hash: str
    rebuilt_asset_hash: str
    source_size: int
    rebuilt_size: int
    parse_confidence: str
    validation_status: str
    byte_identical: bool
    changed_byte_ranges: tuple[tuple[int, int], ...]
    edited_lods: tuple[int, ...] = ()
    edited_submeshes: tuple[str, ...] = ()
    changed_channels: tuple[str, ...] = ()
    recomputed_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    developer_overrides: tuple[str, ...] = ()
    edit_operations: tuple[dict[str, object], ...] = ()
    output_path: str = ""
    export_snapshot: Mapping[str, object] = field(default_factory=dict)
    # Present only when the exact PAC LOD0 topology serializer produced the
    # bytes. Empty for every same-count rebuild.
    topology_rebuild: Mapping[str, object] = field(default_factory=dict)

    @property
    def changed_range_count(self) -> int:
        return len(self.changed_byte_ranges)


@dataclass(frozen=True, slots=True)
class MeshRebuildResult:
    data: bytes
    report: MeshRebuildReport


def build_mesh(mesh: ParsedMesh, original_data: bytes) -> bytes:
    """Auto-detect format and rebuild binary from modified mesh."""
    return _build_mesh_bytes(mesh, original_data)


def rebuild_mesh_with_report(
    mesh: ParsedMesh,
    original_data: bytes,
    *,
    validation_status: str = "not_run",
    output_path: str = "",
    original_mesh: ParsedMesh | None = None,
) -> MeshRebuildResult:
    """Rebuild mesh bytes and return the structured binary-diff report."""
    fmt, rebuild_mesh, parsed_original = _prepare_mesh_for_rebuild(
        mesh,
        original_data,
        original_mesh=original_mesh,
    )
    topology_report: dict[str, object] = {}
    rebuilt = (
        original_data
        if parsed_original is not None and _mesh_matches_no_edit(parsed_original, rebuild_mesh)
        else _build_prepared_mesh_bytes(
            fmt,
            rebuild_mesh,
            original_data,
            original_mesh=parsed_original,
            topology_report=topology_report,
        )
    )
    report = _build_rebuild_report(
        rebuild_mesh,
        original_data,
        rebuilt,
        validation_status=validation_status,
        output_path=output_path,
        original_mesh=parsed_original,
    )
    if topology_report:
        report = dataclasses.replace(report, topology_rebuild=dict(topology_report))
    return MeshRebuildResult(data=rebuilt, report=report)


def _build_mesh_bytes(mesh: ParsedMesh, original_data: bytes) -> bytes:
    fmt, rebuild_mesh, original_mesh = _prepare_mesh_for_rebuild(mesh, original_data)
    if original_mesh is not None and _mesh_matches_no_edit(original_mesh, rebuild_mesh):
        return original_data
    return _build_prepared_mesh_bytes(fmt, rebuild_mesh, original_data, original_mesh=original_mesh)


def _prepare_mesh_for_rebuild(
    mesh: ParsedMesh,
    original_data: bytes,
    *,
    original_mesh: ParsedMesh | None = None,
) -> tuple[str, ParsedMesh, ParsedMesh | None]:
    fmt = mesh.format.lower()
    validate_obj_sidecar_source_identity(mesh, original_data, validate_topology=False)
    _validate_mesh_rebuild_sidecar_warnings(mesh)
    if original_mesh is None:
        try:
            original_mesh = _parse_original_mesh_for_no_edit(fmt, original_data, mesh.path)
        except Exception:
            original_mesh = None
    if original_mesh is not None:
        if (
            fmt == "pac"
            and bool(getattr(mesh, "_cdmw_imported_from_obj", False))
            and not bool(getattr(mesh, "_cdmw_obj_sidecar_present", False))
            and any(
                bool(tuple(getattr(submesh, "bone_indices", ()) or ()))
                or bool(tuple(getattr(submesh, "bone_weights", ()) or ()))
                or bool(str(getattr(submesh, "source_skin_weight_layout", "") or "").strip())
                for submesh in tuple(getattr(original_mesh, "submeshes", ()) or ())
            )
        ):
            raise ValueError(
                "Skinned PAC OBJ round-trip requires the matching <edited>.obj.meta.json sidecar. "
                "Keep or rename the sidecar beside the Blender-exported OBJ, then import it as Round-trip edit."
            )
        mesh = _restore_obj_source_channels(mesh, original_mesh)
        sidecar = getattr(mesh, "_cdmw_obj_sidecar_payload", None)
        if isinstance(sidecar, dict):
            _validate_obj_sidecar_topology(mesh, sidecar)
        _validate_mesh_rebuild_operations(mesh, original_mesh=original_mesh)
        if _has_topology_contract(mesh):
            # Channel re-application rebuilds the original and copies the named
            # channels back onto it, which is a same-count idea. A topology edit
            # has no channel to re-apply: its geometry is the authored result,
            # and reconstructing from the original would hand the writer the
            # unedited mesh while still calling it a rebuild.
            return fmt, mesh, original_mesh
        return fmt, _apply_operation_channels_to_original(original_mesh, mesh), original_mesh
    else:
        sidecar = getattr(mesh, "_cdmw_obj_sidecar_payload", None)
        if isinstance(sidecar, dict):
            _validate_obj_sidecar_topology(mesh, sidecar)
        _validate_mesh_rebuild_operations(mesh, original_mesh=None)
        return fmt, mesh, None


def _restore_obj_source_channels(mesh: ParsedMesh, original: ParsedMesh) -> ParsedMesh:
    """Restore channels OBJ cannot carry, after validating its source identity.

    Existing channel data is checked by operation validation. Skin/tangent data
    is copied only when absent. Proven Blender slot/face cleanup recovers the
    donor layout; any source normals retained for split corners are reported.
    """
    if (
        not getattr(mesh, "_cdmw_imported_from_obj", False)
        or not getattr(mesh, "_cdmw_obj_sidecar_present", False)
        or _has_topology_contract(mesh)
        or len(mesh.submeshes) != len(original.submeshes)
    ):
        return mesh
    restored = copy.deepcopy(mesh)
    sidecar = getattr(mesh, "_cdmw_obj_sidecar_payload", {}) or {}
    exported_textures = sidecar.get("exported_material_textures", {})
    if not isinstance(exported_textures, dict):
        exported_textures = {}
    appearance_payload = sidecar.get("neutral_appearance")
    displayed = None
    recovered_parts = []

    def triangles(faces):
        return Counter(min(tuple(face[i:]) + tuple(face[:i]) for i in range(3)) for face in faces)

    for part_index, (part, donor) in enumerate(zip(restored.submeshes, original.submeshes)):
        count = len(donor.vertices)
        if len(part.vertices) > count:
            if displayed is None:
                displayed = (_load_obj_neutral_appearance(appearance_payload).to_neutral(original)
                             if appearance_payload is not None else original)
            if _collapse_obj_normal_splits(part, donor, displayed.submeshes[part_index]):
                recovered_parts.append(part_index)
        source_map = list(getattr(part, "source_vertex_map", ()) or ())
        if len(part.vertices) != count or sorted(source_map) != list(range(count)):
            continue
        for attr in ("name", "material", "texture"):
            if str(getattr(part, attr, "")).strip() == str(getattr(donor, attr, "")).strip():
                setattr(part, attr, getattr(donor, attr))
        # Scene preview resolves an OBJ's image path onto the mesh. That is
        # still the exported material, not an authored PAC texture change.
        texture_keys = {_obj_texture_key(donor.texture)}
        published_texture = exported_textures.get(str(donor.material or donor.name).strip(), "")
        if published_texture:
            texture_keys.add(_obj_texture_key(str(published_texture)))
        if _obj_texture_key(part.texture) in texture_keys:
            part.texture = donor.texture
        # Preserve the PAC's vertex slots if the importer supplied a permutation.
        if source_map != list(range(count)):
            order = sorted(range(count), key=source_map.__getitem__)
            for attr in ("vertices", "normals", "uvs", "tangents", "bone_indices", "bone_weights"):
                values = getattr(part, attr, ()) or ()
                if len(values) == count:
                    setattr(part, attr, [values[index] for index in order])
            part.faces = [tuple(source_map[index] for index in face) for face in part.faces]
            part.source_vertex_map = list(range(count))
            part.source_vertex_offsets = list(donor.source_vertex_offsets)
        for attr in ("bone_indices", "bone_weights", "tangents"):
            if not getattr(part, attr, ()):
                setattr(part, attr, copy.deepcopy(getattr(donor, attr, [])))
        observed, expected = triangles(part.faces), triangles(donor.faces)
        if ({tuple(sorted(face)) for face in observed} == {tuple(sorted(face)) for face in expected}
                and all(1 <= count <= expected[face] for face, count in observed.items())):
            # Blender removes repeated triangles, including opposite-facing
            # copies. Every surviving face must still have source winding.
            part.faces = copy.deepcopy(donor.faces)
            part.face_count = len(part.faces)
    if recovered_parts:
        # Import records operations only for parts already having the source
        # count. Add their missing declarations after proven slot recovery.
        operations = list(mesh_edit_operations_from_dicts(getattr(restored, "_cdmw_edit_operations", ()) or ()))
        existing = {(op.operation, op.lod_index, op.submesh_index) for op in operations}
        for index in recovered_parts:
            part = restored.submeshes[index]
            for channel, attr in (("positions", "vertices"), ("normals", "normals"), ("uv0", "uvs")):
                name = f"replace_{channel}_same_count"
                if len(getattr(part, attr)) == len(part.vertices) and (name, 0, index) not in existing:
                    operations.append(MeshEditOperation(name, lod_index=0, submesh_index=index,
                                                        vertex_count=len(part.vertices), source="OBJ source-normal recovery"))
        restored._cdmw_edit_operations = mesh_edit_operations_to_dicts(operations)
        mesh._cdmw_obj_normal_recovery_notes = tuple(
            f"Retained source normals for Blender corner-normal splits in {original.submeshes[index].name}. "
            "Separate hard-edge normals require a topology replacement."
            for index in recovered_parts
        )
    if appearance_payload is not None:
        restored = _restore_obj_neutral_coordinates(restored, original, appearance_payload, displayed=displayed)
    if original.lod_levels and not restored.lod_levels:
        restored.lod_levels = [restored.submeshes, *copy.deepcopy(original.lod_levels[1:])]
    restored.has_bones = original.has_bones
    _refresh_mesh_counts(restored)
    return restored


def _collapse_obj_normal_splits(part, donor, reference) -> bool:
    """Recover source slots only when OBJ split normals retain source evidence."""
    def direction(values):
        length = math.hypot(*values)
        return tuple(value / length for value in values) if length > 1e-12 else values

    count, actual = len(donor.vertices), len(part.vertices)
    source_map = list(part.source_vertex_map)
    if (len(source_map) != actual or set(source_map) != set(range(count))
            or len(part.normals) != actual or len(reference.normals) != count):
        return False
    groups = [[] for _ in range(count)]
    for index, source_index in enumerate(source_map):
        groups[source_index].append(index)
    order = [indices[0] for indices in groups]
    for source_index, indices in enumerate(groups):
        if len(indices) == 1:
            continue
        # New UV seams, displaced copies, or changed protected channels cannot
        # be collapsed into the PAC's one record per vertex.
        for attr in ("vertices", "uvs", "tangents", "bone_indices", "bone_weights", "source_vertex_offsets"):
            values = getattr(part, attr, ()) or ()
            if values and (len(values) != actual or any(values[i] != values[indices[0]] for i in indices)):
                raise ValueError(f"OBJ split vertex {source_index} changes {attr}; use topology replacement.")
        normal = reference.normals[source_index]
        source_direction = direction(normal)
        # PAC normal packing and Blender's custom-normal compression can round
        # a near-zero component away. Require the source direction within that
        # precision (about 0.1 degree), then retain its original packed normal.
        if not any(math.dist(direction(part.normals[i]), source_direction) <= 2e-3 for i in indices):
            raise ValueError(f"OBJ split vertex {source_index} has no matching source normal; use topology replacement.")
        part.normals[indices[0]] = normal
    for attr in ("vertices", "normals", "uvs", "tangents", "bone_indices", "bone_weights", "source_vertex_offsets"):
        values = getattr(part, attr, ()) or ()
        if len(values) == actual:
            setattr(part, attr, [values[index] for index in order])
    part.faces = [tuple(source_map[index] for index in face) for face in part.faces]
    part.source_vertex_map = list(range(count))
    part.vertex_count = count
    return True


def _load_obj_neutral_appearance(payload: object):
    from .mesh_neutral_appearance import NeutralMeshAppearance

    try:
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("unsupported neutral appearance version")
        matrices = tuple(tuple(float(value) for value in row) for row in payload["skin_matrices"])
        palette = tuple(int(value) for value in payload["bone_palette"])
        if not matrices or not palette or any(len(row) != 16 or not all(math.isfinite(v) for v in row) for row in matrices):
            raise ValueError("invalid neutral appearance matrices")
        if any(index < 0 or index >= len(matrices) for index in palette):
            raise ValueError("invalid neutral appearance bone palette")
        return NeutralMeshAppearance(str(payload.get("source", "")), palette, matrices)
    except (KeyError, TypeError, OverflowError, ValueError) as exc:
        raise ValueError(f"OBJ neutral appearance reconstruction failed: {exc}") from exc


def _restore_obj_neutral_coordinates(
    mesh: ParsedMesh, original: ParsedMesh, payload: object, *, displayed: ParsedMesh | None = None,
) -> ParsedMesh:
    appearance = _load_obj_neutral_appearance(payload)
    try:
        for part, donor in zip(mesh.submeshes, original.submeshes):
            if (part.name != donor.name or len(part.vertices) != len(donor.vertices)
                    or list(part.source_vertex_map) != list(donor.source_vertex_map)
                    or list(part.source_vertex_offsets) != list(donor.source_vertex_offsets)
                    or part.bone_indices != donor.bone_indices or part.bone_weights != donor.bone_weights):
                raise ValueError("neutral appearance source mapping changed")
        # OBJ text and Blender's float32 storage round displayed coordinates.
        # Snap only values within that serialization precision before inversion.
        if displayed is None:
            displayed = appearance.to_neutral(original)
        for part, reference in zip(mesh.submeshes, displayed.submeshes):
            for attr in ("vertices", "normals"):
                values, baseline = getattr(part, attr), getattr(reference, attr)
                if len(values) == len(baseline):
                    setattr(part, attr, [b if all(abs(x-y) <= 6e-7 for x, y in zip(a,b)) else a
                                         for a,b in zip(values, baseline)])
        restored = appearance.to_source(mesh, original)
        restored._cdmw_obj_display_vertices = tuple(tuple(part.vertices) for part in mesh.submeshes)
        # OBJ does not author tangents; keep the protected donor channel.
        for part, donor in zip(restored.submeshes, original.submeshes):
            part.tangents = copy.deepcopy(donor.tangents)
        return restored
    except (KeyError, TypeError, OverflowError, ValueError) as exc:
        raise ValueError(f"OBJ neutral appearance reconstruction failed: {exc}") from exc


def _build_prepared_mesh_bytes(
    fmt: str,
    mesh: ParsedMesh,
    original_data: bytes,
    *,
    original_mesh: ParsedMesh | None = None,
    topology_report: dict[str, object] | None = None,
) -> bytes:
    # A validated topology contract routes to the exact LOD0 writer and to
    # nothing else. Falling through to the native builder or the generic PAC
    # rebuild would replace an exact result with a plausible one, so a contract
    # that cannot be served here raises instead of being quietly ignored.
    if _has_topology_contract(mesh):
        if fmt != "pac":
            raise ValueError(
                f"Topology provenance is only rebuildable into PAC; this mesh is {fmt or 'unknown'}."
            )
        if original_mesh is None:
            raise ValueError(
                "Exact PAC LOD0 topology rebuild needs the original parsed mesh, and it is unavailable. "
                "Refusing to fall back to the generic rebuild, which would choose donor records."
            )
        return build_pac_topology_rebuild(
            original_mesh, mesh, original_data, report=topology_report
        )
    operations = mesh_edit_operations_from_dicts(
        getattr(mesh, "_cdmw_edit_operations", ()) or ()
    )
    requires_python_skin_writer = fmt == "pac" and any(
        mesh_edit_operation_changed_channel(operation.operation) == "skin_weights"
        for operation in operations
    )
    native_data = None
    if not requires_python_skin_writer:
        try:
            from cdmw.core.mesh_native import build_mesh_native

            native_data = build_mesh_native(mesh, original_data)
            if native_data is not None:
                if fmt == "pac":
                    parsed_native = parse_pac(native_data, mesh.path)
                elif fmt == "pam":
                    parsed_native = parse_pam(native_data, mesh.path)
                elif fmt == "pamlod":
                    parsed_native = parse_pamlod(native_data, mesh.path)
                else:
                    parsed_native = None
                if parsed_native is None or len(parsed_native.submeshes) != len(mesh.submeshes):
                    native_data = None
        except Exception:
            native_data = None
    if native_data is not None:
        rebuilt = native_data
    elif fmt == "pac":
        rebuilt = build_pac(mesh, original_data)
    elif fmt == "pam":
        rebuilt = build_pam(mesh, original_data)
    elif fmt == "pamlod":
        rebuilt = build_pamlod(mesh, original_data)
    else:
        raise ValueError(f"Unsupported mesh format for rebuild: {fmt}")
    _validate_pac_obj_protected_vertex_bytes(fmt, mesh, original_data, rebuilt)
    _validate_exact_pac_skin_weight_byte_ownership(
        fmt,
        mesh,
        original_data,
        rebuilt,
    )
    _validate_neutral_obj_rebuild(fmt, mesh, rebuilt)
    return rebuilt


def _validate_neutral_obj_rebuild(fmt: str, mesh: ParsedMesh, rebuilt_data: bytes) -> None:
    expected = getattr(mesh, "_cdmw_obj_display_vertices", ())
    if fmt != "pac" or not expected:
        return
    payload = getattr(mesh, "_cdmw_obj_sidecar_payload", {})["neutral_appearance"]
    displayed = _load_obj_neutral_appearance(payload).to_neutral(parse_pac(rebuilt_data, mesh.path))
    for part, positions in zip(displayed.submeshes, expected, strict=True):
        scale = max(1.0, max((abs(value) for vertex in positions for value in vertex), default=1.0))
        error = max((math.dist(actual, wanted) for actual, wanted in zip(part.vertices, positions, strict=True)), default=0.0)
        if error > 5e-5 * scale:
            raise ValueError(
                f"Neutral OBJ edit exceeds PAC position precision for {part.name} "
                f"(reconstructed displacement {error:.6g}). Use a source-coordinate OBJ or Mesh Replacement for this edit."
            )


def _has_topology_contract(mesh: ParsedMesh) -> bool:
    """True when any submesh carries a contract that describes its own geometry."""
    return bool(topology_contract_submesh_indices(mesh))


def _validate_pac_obj_protected_vertex_bytes(
    fmt: str,
    mesh: ParsedMesh,
    original_data: bytes,
    rebuilt_data: bytes,
) -> None:
    if (
        fmt != "pac"
        or not bool(getattr(mesh, "_cdmw_imported_from_obj", False))
        or not bool(getattr(mesh, "_cdmw_obj_sidecar_present", False))
    ):
        return
    operations = mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ())
    if not operations:
        return
    if len(rebuilt_data) != len(original_data):
        raise ValueError(
            "OBJ round-trip changed the PAC file size; protected vertex-byte preservation could not be proven."
        )

    editable_ranges = {
        "positions": range(0, 6),
        "uv0": range(8, 12),
        "normals": range(16, 20),
        # Only the six proven palette slots and their six u8 weights are owned
        # by replace_skin_weights_same_count.  The two extra influence lanes at
        # 12:16 and 34:36 remain protected.
        "skin_weights": tuple(range(20, 34)),
    }
    editable_by_submesh: dict[int, set[int]] = {}
    for operation in operations:
        channel = mesh_edit_operation_changed_channel(operation.operation)
        byte_range = editable_ranges.get(channel)
        if byte_range is None or operation.submesh_index < 0:
            continue
        editable_by_submesh.setdefault(operation.submesh_index, set()).update(byte_range)

    for submesh_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
        stride = int(getattr(submesh, "source_vertex_stride", 0) or 0)
        offsets = tuple(int(value) for value in tuple(getattr(submesh, "source_vertex_offsets", ()) or ()))
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        if stride < 20 or len(offsets) != len(vertices):
            raise ValueError(
                "OBJ round-trip could not prove protected PAC vertex-byte preservation for "
                f"submesh {submesh_index}: source offsets or stride are incomplete."
            )
        editable = editable_by_submesh.get(submesh_index, set())
        protected_spans: list[tuple[int, int]] = []
        span_start = -1
        for byte_index in range(stride + 1):
            protected = byte_index < stride and byte_index not in editable
            if protected and span_start < 0:
                span_start = byte_index
            elif not protected and span_start >= 0:
                protected_spans.append((span_start, byte_index))
                span_start = -1
        for vertex_index, offset in enumerate(offsets):
            if offset < 0 or offset + stride > len(original_data):
                raise ValueError(
                    "OBJ round-trip could not prove protected PAC vertex-byte preservation for "
                    f"submesh {submesh_index} vertex {vertex_index}: source record is outside the file."
                )
            for start, end in protected_spans:
                if original_data[offset + start : offset + end] != rebuilt_data[offset + start : offset + end]:
                    raise ValueError(
                        "OBJ round-trip changed protected PAC vertex bytes for "
                        f"submesh {submesh_index} vertex {vertex_index} at record bytes {start}:{end}."
                    )


def _validate_exact_pac_skin_weight_byte_ownership(
    fmt: str,
    mesh: ParsedMesh,
    original_data: bytes,
    rebuilt_data: bytes,
) -> None:
    """Prove that a skin-weight-only PAC rebuild changed only owned lanes."""

    if fmt != "pac":
        return
    operations = mesh_edit_operations_from_dicts(
        getattr(mesh, "_cdmw_edit_operations", ()) or ()
    )
    if not operations:
        return
    changed_channels = {
        mesh_edit_operation_changed_channel(operation.operation)
        for operation in operations
    }
    if changed_channels != {"skin_weights"}:
        return
    if len(rebuilt_data) != len(original_data):
        raise ValueError(
            "Exact PAC skin-weight replacement changed the file size; byte ownership could not be proven."
        )

    if any(
        operation.lod_index != 0 or operation.submesh_index < 0
        for operation in operations
    ):
        raise ValueError(
            "Exact PAC skin-weight replacement may target only valid LOD 0 submeshes."
        )
    target_submeshes = {
        operation.submesh_index
        for operation in operations
        if operation.lod_index == 0 and operation.submesh_index >= 0
    }

    owned_ranges: list[tuple[int, int]] = []
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    for submesh_index in sorted(target_submeshes):
        if not 0 <= submesh_index < len(submeshes):
            raise ValueError(
                f"Exact PAC skin-weight replacement targets missing submesh {submesh_index}."
            )
        submesh = submeshes[submesh_index]
        stride = int(getattr(submesh, "source_vertex_stride", 0) or 0)
        offsets = tuple(
            int(value)
            for value in tuple(
                getattr(submesh, "source_vertex_offsets", ()) or ()
            )
        )
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        if stride != 40 or len(offsets) != len(vertices):
            raise ValueError(
                "Exact PAC skin-weight replacement lacks the proven 40-byte source records for "
                f"submesh {submesh_index}."
            )
        for vertex_index, offset in enumerate(offsets):
            start = offset + 20
            end = offset + 34
            if offset < 0 or end > len(original_data):
                raise ValueError(
                    "Exact PAC skin-weight replacement source record is outside the file for "
                    f"submesh {submesh_index} vertex {vertex_index}."
                )
            owned_ranges.append((start, end))

    owned_ranges.sort()
    merged_ranges: list[tuple[int, int]] = []
    for start, end in owned_ranges:
        if merged_ranges and start <= merged_ranges[-1][1]:
            previous_start, previous_end = merged_ranges[-1]
            merged_ranges[-1] = (previous_start, max(previous_end, end))
        else:
            merged_ranges.append((start, end))

    range_index = 0
    for offset, (original_byte, rebuilt_byte) in enumerate(
        zip(original_data, rebuilt_data)
    ):
        if original_byte == rebuilt_byte:
            continue
        while (
            range_index < len(merged_ranges)
            and merged_ranges[range_index][1] <= offset
        ):
            range_index += 1
        if (
            range_index >= len(merged_ranges)
            or offset < merged_ranges[range_index][0]
        ):
            raise ValueError(
                "Exact PAC skin-weight replacement changed an unowned byte at "
                f"file offset {offset}; only record bytes 20:34 are authorized."
            )


def _build_rebuild_report(
    mesh: ParsedMesh,
    original_data: bytes,
    rebuilt_data: bytes,
    *,
    validation_status: str,
    output_path: str,
    original_mesh: ParsedMesh | None = None,
) -> MeshRebuildReport:
    fmt = str(mesh.format or "").lower()
    changed_ranges = _diff_byte_ranges(original_data, rebuilt_data)
    if original_mesh is None:
        original_mesh = _parse_original_mesh_for_report(fmt, original_data, mesh.path)
    edited_lods, edited_submeshes, changed_channels = _merge_mesh_scopes(
        _changed_mesh_scope(original_mesh, mesh),
        _operation_mesh_scope(mesh),
    )
    return MeshRebuildReport(
        mesh_format=fmt,
        source_asset_hash=_sha256(original_data),
        rebuilt_asset_hash=_sha256(rebuilt_data),
        source_size=len(original_data),
        rebuilt_size=len(rebuilt_data),
        parse_confidence=_parse_confidence(mesh, original_data),
        validation_status=str(validation_status or "not_run"),
        byte_identical=not changed_ranges,
        changed_byte_ranges=changed_ranges,
        edited_lods=edited_lods,
        edited_submeshes=edited_submeshes,
        changed_channels=changed_channels,
        edit_operations=_mesh_edit_operation_payloads(mesh),
        output_path=str(output_path or ""),
    )


def _validate_mesh_rebuild_operations(mesh: ParsedMesh, *, original_mesh: ParsedMesh | None) -> None:
    operations = mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ())
    if not operations:
        if bool(getattr(mesh, "_cdmw_imported_from_obj", False)) and bool(getattr(mesh, "_cdmw_obj_sidecar_present", False)):
            raise ValueError("Imported OBJ sidecar rebuild requires explicit Mesh Editor v2 edit operations.")
        return
    allowed_operations = getattr(mesh, "_cdmw_sidecar_allowed_edit_operations", None)
    issues = validate_mesh_edit_operations(
        operations,
        mesh=mesh,
        allowed_operations=allowed_operations if allowed_operations is not None else None,
    )
    if original_mesh is not None:
        issues += validate_mesh_edit_operation_coverage(operations, mesh=mesh, original_mesh=original_mesh)
    blockers = tuple(issue for issue in issues if issue.severity == "blocker")
    if blockers:
        raise ValueError(f"Mesh edit operation blocked rebuild: {blockers[0].message}")


def _apply_operation_channels_to_original(
    original_mesh: ParsedMesh,
    edited_mesh: ParsedMesh,
    *,
    active_lod_index: int | None = None,
) -> ParsedMesh:
    operations = mesh_edit_operations_from_dicts(getattr(edited_mesh, "_cdmw_edit_operations", ()) or ())
    if not operations:
        return edited_mesh
    rebuilt = copy.deepcopy(original_mesh)
    _copy_cdmw_attrs(edited_mesh, rebuilt)
    rebuilt.path = str(edited_mesh.path or rebuilt.path or "")
    rebuilt.format = str(edited_mesh.format or rebuilt.format or "")
    try:
        resolved_active_lod_index = int(
            active_lod_index
            if active_lod_index is not None
            else getattr(
                edited_mesh,
                "active_lod_index",
                getattr(edited_mesh, "displayed_lod_index", 0),
            )
            or 0
        )
    except (TypeError, ValueError, OverflowError):
        resolved_active_lod_index = 0
    for operation in operations:
        channel = mesh_edit_operation_changed_channel(operation.operation)
        if not channel or channel == "visibility":
            continue
        source = _operation_target_submesh(
            edited_mesh,
            operation.lod_index,
            operation.submesh_index,
            active_lod_index=resolved_active_lod_index,
        )
        target = _operation_target_submesh(rebuilt, operation.lod_index, operation.submesh_index)
        if source is None or target is None:
            continue
        _copy_operation_channel(source, target, channel)
    lod_levels = getattr(rebuilt, "lod_levels", None) or []
    if lod_levels:
        if 0 <= resolved_active_lod_index < len(lod_levels):
            rebuilt.active_lod_index = resolved_active_lod_index
            rebuilt.submeshes = lod_levels[resolved_active_lod_index]
    _refresh_mesh_counts(rebuilt)
    return rebuilt


def apply_operation_channels_to_original(
    original_mesh: ParsedMesh,
    edited_mesh: ParsedMesh,
    *,
    active_lod_index: int | None = None,
) -> ParsedMesh:
    return _apply_operation_channels_to_original(
        original_mesh,
        edited_mesh,
        active_lod_index=active_lod_index,
    )


def _copy_cdmw_attrs(source: ParsedMesh, target: ParsedMesh) -> None:
    for name, value in vars(source).items():
        if name.startswith("_cdmw_"):
            setattr(target, name, copy.deepcopy(value))


def _operation_target_submesh(
    mesh: ParsedMesh,
    lod_index: int,
    submesh_index: int,
    *,
    active_lod_index: int | None = None,
) -> object | None:
    if submesh_index < 0:
        return None
    if active_lod_index is not None and lod_index == active_lod_index:
        active_submeshes = getattr(mesh, "submeshes", None) or []
        if 0 <= submesh_index < len(active_submeshes):
            return active_submeshes[submesh_index]
    lod_levels = getattr(mesh, "lod_levels", None) or []
    if lod_levels:
        if not 0 <= lod_index < len(lod_levels):
            return None
        lod_submeshes = lod_levels[lod_index] or []
        return lod_submeshes[submesh_index] if 0 <= submesh_index < len(lod_submeshes) else None
    submeshes = getattr(mesh, "submeshes", None) or []
    return submeshes[submesh_index] if 0 <= submesh_index < len(submeshes) else None


def _copy_operation_channel(source: object, target: object, channel: str) -> None:
    if channel == "positions":
        target.vertices = copy.deepcopy(getattr(source, "vertices", []) or [])
    elif channel == "normals":
        target.normals = copy.deepcopy(getattr(source, "normals", []) or [])
    elif channel == "tangents":
        target.tangents = copy.deepcopy(getattr(source, "tangents", []) or [])
    elif channel == "uv0":
        target.uvs = copy.deepcopy(getattr(source, "uvs", []) or [])
    elif channel == "skin_weights":
        # This branch is reachable only through the explicit operation mapping;
        # there is deliberately no inference from changed rows.
        target.bone_indices = copy.deepcopy(getattr(source, "bone_indices", []) or [])
        target.bone_weights = copy.deepcopy(getattr(source, "bone_weights", []) or [])
    elif channel == "bounds":
        target.source_bbox_min = tuple(getattr(source, "source_bbox_min", ()) or getattr(target, "source_bbox_min", ()))
        target.source_bbox_extent = tuple(getattr(source, "source_bbox_extent", ()) or getattr(target, "source_bbox_extent", ()))


def _refresh_mesh_counts(mesh: ParsedMesh) -> None:
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        submesh.vertex_count = len(getattr(submesh, "vertices", ()) or ())
        submesh.face_count = len(getattr(submesh, "faces", ()) or ())
    mesh.total_vertices = sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in tuple(getattr(mesh, "submeshes", ()) or ()))
    mesh.total_faces = sum(len(getattr(submesh, "faces", ()) or ()) for submesh in tuple(getattr(mesh, "submeshes", ()) or ()))
    mesh.has_uvs = any(bool(getattr(submesh, "uvs", ()) or ()) for submesh in tuple(getattr(mesh, "submeshes", ()) or ()))
    mesh.has_bones = any(
        bool(getattr(submesh, "bone_indices", ()) or ()) or bool(getattr(submesh, "bone_weights", ()) or ())
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ())
    )


def _validate_mesh_rebuild_sidecar_warnings(mesh: ParsedMesh) -> None:
    for warning in tuple(getattr(mesh, "_cdmw_sidecar_warnings", ()) or ()):
        if not isinstance(warning, dict) or not bool(warning.get("blocks_rebuild")):
            continue
        message = str(warning.get("message") or "Sidecar metadata changed.").strip()
        raise ValueError(f"Mesh sidecar metadata drift blocked rebuild: {message}")


def _mesh_edit_operation_payloads(mesh: ParsedMesh) -> tuple[dict[str, object], ...]:
    operations = mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ())
    return mesh_edit_operations_to_dicts(operations)


def _parse_original_mesh_for_no_edit(fmt: str, original_data: bytes, path: str) -> ParsedMesh | None:
    if fmt == "pac":
        return parse_pac(original_data, path)
    if fmt == "pam":
        return parse_pam(original_data, path)
    if fmt == "pamlod":
        return parse_pamlod(original_data, path)
    return None


def _parse_original_mesh_for_report(fmt: str, original_data: bytes, path: str) -> ParsedMesh | None:
    try:
        return _parse_original_mesh_for_no_edit(fmt, original_data, path)
    except Exception:
        return None


def _mesh_matches_no_edit(original: ParsedMesh, edited: ParsedMesh) -> bool:
    return (
        str(original.format or "").lower() == str(edited.format or "").lower()
        and list(original.submeshes or []) == list(edited.submeshes or [])
        and list(original.lod_levels or []) == list(edited.lod_levels or [])
        and int(original.total_vertices or 0) == int(edited.total_vertices or 0)
        and int(original.total_faces or 0) == int(edited.total_faces or 0)
        and bool(original.has_uvs) == bool(edited.has_uvs)
        and bool(original.has_bones) == bool(edited.has_bones)
    )


def _diff_byte_ranges(original_data: bytes, rebuilt_data: bytes) -> tuple[tuple[int, int], ...]:
    from .mesh_roundtrip import diff_byte_ranges

    return tuple((int(start), int(end)) for start, end in diff_byte_ranges(original_data, rebuilt_data))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_confidence(mesh: ParsedMesh, original_data: bytes) -> str:
    raw = str(getattr(mesh, "_cdmw_mesh_asset_parse_confidence", "") or "").strip()
    if raw:
        return raw
    try:
        from .mesh_asset import mesh_asset_from_parsed_mesh

        return mesh_asset_from_parsed_mesh(mesh, original_data).parse_confidence
    except Exception:
        return ""


def _changed_mesh_scope(
    original: ParsedMesh | None,
    edited: ParsedMesh,
) -> tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]:
    if original is None:
        return (), (), ()
    edited_lods: set[int] = set()
    edited_submeshes: set[str] = set()
    changed_channels: set[str] = set()
    original_lods = _submeshes_by_lod(original)
    updated_lods = _submeshes_by_lod(edited)
    for lod_index in range(max(len(original_lods), len(updated_lods))):
        original_submeshes = original_lods[lod_index] if lod_index < len(original_lods) else ()
        updated_submeshes = updated_lods[lod_index] if lod_index < len(updated_lods) else ()
        if len(original_submeshes) != len(updated_submeshes):
            edited_lods.add(lod_index)
            changed_channels.add("submesh_count")
        for submesh_index in range(max(len(original_submeshes), len(updated_submeshes))):
            before = original_submeshes[submesh_index] if submesh_index < len(original_submeshes) else None
            after = updated_submeshes[submesh_index] if submesh_index < len(updated_submeshes) else None
            changes = _changed_submesh_channels(before, after)
            if not changes:
                continue
            edited_lods.add(lod_index)
            edited_submeshes.add(_submesh_stable_id(lod_index, submesh_index, after or before))
            changed_channels.update(changes)
    return tuple(sorted(edited_lods)), tuple(sorted(edited_submeshes)), tuple(sorted(changed_channels))


def _operation_mesh_scope(mesh: ParsedMesh) -> tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]:
    operations = mesh_edit_operations_from_dicts(getattr(mesh, "_cdmw_edit_operations", ()) or ())
    if not operations:
        return (), (), ()
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    edited_lods: set[int] = set()
    edited_submeshes: set[str] = set()
    changed_channels: set[str] = set()
    for operation in operations:
        channel = _operation_changed_channel(operation.operation)
        if not channel:
            continue
        lod_index = max(0, int(operation.lod_index or 0))
        edited_lods.add(lod_index)
        changed_channels.add(channel)
        submesh_index = int(operation.submesh_index)
        if 0 <= submesh_index < len(submeshes):
            edited_submeshes.add(_submesh_stable_id(lod_index, submesh_index, submeshes[submesh_index]))
    return tuple(sorted(edited_lods)), tuple(sorted(edited_submeshes)), tuple(sorted(changed_channels))


def _merge_mesh_scopes(
    *scopes: tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]
) -> tuple[tuple[int, ...], tuple[str, ...], tuple[str, ...]]:
    edited_lods: set[int] = set()
    edited_submeshes: set[str] = set()
    changed_channels: set[str] = set()
    for lods, submeshes, channels in scopes:
        edited_lods.update(int(value) for value in lods)
        edited_submeshes.update(str(value) for value in submeshes if str(value))
        changed_channels.update(str(value) for value in channels if str(value))
    return tuple(sorted(edited_lods)), tuple(sorted(edited_submeshes)), tuple(sorted(changed_channels))


def _operation_changed_channel(operation: str) -> str:
    return mesh_edit_operation_changed_channel(operation)


def _submeshes_by_lod(mesh: ParsedMesh) -> tuple[tuple[object, ...], ...]:
    lod_levels = tuple(getattr(mesh, "lod_levels", ()) or ())
    if lod_levels:
        return tuple(tuple(level or ()) for level in lod_levels)
    return (tuple(getattr(mesh, "submeshes", ()) or ()),)


def _changed_submesh_channels(before: object | None, after: object | None) -> tuple[str, ...]:
    if before is None or after is None:
        return ("topology",)
    fields = (
        ("vertices", "positions"),
        ("normals", "normals"),
        ("tangents", "tangents"),
        ("uvs", "uv0"),
        ("faces", "indices"),
        ("bone_indices", "bone_indices"),
        ("bone_weights", "bone_weights"),
    )
    changed = [
        channel
        for attr, channel in fields
        if tuple(getattr(before, attr, ()) or ()) != tuple(getattr(after, attr, ()) or ())
    ]
    if str(getattr(before, "material", "") or "") != str(getattr(after, "material", "") or ""):
        changed.append("material")
    if str(getattr(before, "texture", "") or "") != str(getattr(after, "texture", "") or ""):
        changed.append("texture")
    if int(getattr(before, "vertex_count", 0) or 0) != int(getattr(after, "vertex_count", 0) or 0):
        changed.append("vertex_count")
    if int(getattr(before, "face_count", 0) or 0) != int(getattr(after, "face_count", 0) or 0):
        changed.append("index_count")
    return tuple(changed)


def _submesh_stable_id(lod_index: int, submesh_index: int, submesh: object | None) -> str:
    raw = str(getattr(submesh, "stable_id", "") or "").strip() if submesh is not None else ""
    return raw or f"lod{lod_index}_submesh{submesh_index}"
