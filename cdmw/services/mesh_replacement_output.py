"""Prepare one complete, immutable archive replacement output from a snapshot."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import copy
import struct
from pathlib import PurePosixPath

from cdmw.domain.mesh.export_validation import MeshExportValidationIssue, validate_mesh_export
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementFile, bound_part_indices
from cdmw.modding.mesh_importer import MeshRebuildReport, _build_rebuild_report
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions, StaticReplacementTransform, StaticSubmeshMapping,
    build_static_mesh_replacement,
)


@dataclass(frozen=True, slots=True)
class MeshReplacementOutput:
    data: bytes
    report: MeshRebuildReport
    companion_files: tuple[ReplacementFile, ...]
    revision: tuple[int, int, int]


def manual_replacement_options(mappings=(), *, removed=()):
    # These defaults are local to Mesh Editor. New Item retains its own fitting.
    return StaticMeshReplacementOptions(
        transform=StaticReplacementTransform(scale_to_original_length=False, alignment_mode="manual"),
        submesh_mappings=list(mappings), removed_target_submesh_indices=list(removed),
        material_mapping_mode="keep_original", strict_static_only=False,
    )


def replacement_source_mesh(mesh, state, original):
    """Invert the displayed skin transform once, using the candidate's weights."""
    if not state.neutral_coordinates:
        return mesh
    if state.neutral_appearance is None:
        raise ValueError("Experimental replacement is missing its neutral coordinate transform.")
    indices = bound_part_indices(mesh, state)
    reference = copy.copy(original)
    reference.submeshes = [None] * len(mesh.submeshes)
    for part in state.parts:
        reference.submeshes[indices[part.part_id]] = original.submeshes[part.target_index]
    reference.lod_levels = [reference.submeshes, *original.lod_levels[1:]] if original.lod_levels else []
    return state.neutral_appearance.to_source(mesh, reference)


def validate_replacement_geometry(mesh, state: MeshReplacementState, original_data: bytes):
    report = validate_mesh_export(
        mesh, exact_output=False, edit_operations=(), requires_edit_operations=False,
        require_operation_source_mapping=False,
    )
    issues = list(report.issues)
    try:
        bound_part_indices(mesh, state)
        if hashlib.sha256(original_data).hexdigest() != state.target_sha256:
            raise ValueError("Replacement target bytes no longer match the captured archive asset.")
        if str(mesh.path).replace("\\", "/").casefold() != state.target_path.replace("\\", "/").casefold():
            raise ValueError("Replacement target identity changed.")
        targets = [part.target_index for part in state.parts]
        if len(targets) != len(set(targets)) or any(index < 0 for index in targets):
            raise ValueError("Replacement target mapping is invalid or ambiguous.")
        if any(part.material_choice not in {"original", "imported"} for part in state.parts):
            raise ValueError("Unknown replacement material choice.")
    except ValueError as exc:
        issues.append(MeshExportValidationIssue("blocker", "replacement_mapping", str(exc)))
    return replace(report, issues=tuple(issues))


def _preserve_pam_index_convention(data, original_data):
    """Retain proven per-section indexing in combined PAM targets.

    The retained full writer emits global indices. A source whose sections use
    local indices needs those rebased before its normal parser/runtime handoff.
    This adaptation belongs only to the optional replacement output path.
    """
    from cdmw.modding.mesh_pam_builder import _inspect_pam_layout
    before, after = _inspect_pam_layout(original_data), _inspect_pam_layout(data)
    if before["kind"] != "combined" or after["kind"] != "combined":
        return data
    old_base = before["geom_off"] + sum(row["nv"] for row in before["entries"]) * before["stride"]
    new_base = after["geom_off"] + sum(row["nv"] for row in after["entries"]) * after["stride"]
    result = bytearray(data)
    for old, new in zip(before["entries"], after["entries"], strict=True):
        old_indices = struct.unpack_from(f'<{old["ni"]}H', original_data, old_base + old["ie"] * 2)
        if old["ve"] and old_indices and min(old_indices) < old["ve"] and max(old_indices) < old["nv"]:
            offset = new_base + new["ie"] * 2
            indices = struct.unpack_from(f'<{new["ni"]}H', data, offset)
            if all(new["ve"] <= index < new["ve"] + new["nv"] for index in indices):
                struct.pack_into(f'<{new["ni"]}H', result, offset, *(index - new["ve"] for index in indices))
            elif any(index >= new["nv"] for index in indices):
                raise ValueError("PAM replacement index conversion could not be proven.")
    return bytes(result)


def _build_replacement_pamlod(mesh, original_data, state, original_target):
    """Use the retained LOD0 writer, then patch the preserved lower-level records."""
    from cdmw.modding.mesh_pamlod_builder import build_pamlod
    from cdmw.modding.static_mesh_runtime_builder import _build_removed_runtime_placeholder_submesh

    original = parse_mesh(original_data, mesh.path)
    requested_levels = mesh.lod_levels or original.lod_levels
    lod0 = copy.copy(mesh)
    lod0.lod_levels = []
    data = build_pamlod(lod0, original_data)
    if len(original.lod_levels) < 2:
        return data
    prepared = parse_mesh(data, mesh.path)
    by_material = {}
    for binding in state.parts:
        material = original_target.submeshes[binding.target_index].material
        if material in by_material:
            raise ValueError(f"Lower LOD material mapping is ambiguous: {material}")
        by_material[material] = binding
    for level_index, (level, requested) in enumerate(zip(prepared.lod_levels[1:], requested_levels[1:], strict=True), 1):
        if len(level) != len(requested):
            raise ValueError(f"Lower LOD {level_index} changed its required section layout.")
        for part_index, (part, desired) in enumerate(zip(level, requested, strict=True)):
            binding = by_material.get(part.material)
            if binding is None:
                raise ValueError(f"Lower LOD material has no target mapping: {part.material}")
            if not binding.included:
                triangle = _build_removed_runtime_placeholder_submesh(original.lod_levels[level_index][part_index])
                # Preserve lower-LOD topology and its indices, collapsing positions
                # into the very same retained tiny triangle used for LOD0.
                part.vertices = [triangle.vertices[index % 3] for index in range(len(part.vertices))]
            else:
                if len(part.vertices) != len(desired.vertices):
                    raise ValueError(f"Lower LOD geometry transfer is unsupported: {part.material}")
                part.vertices = list(desired.vertices)
    result = build_pamlod(prepared, data)
    checked = parse_mesh(result, mesh.path)
    if [len(level) for level in checked.lod_levels] != [len(level) for level in original.lod_levels]:
        raise ValueError("Replacement writer changed the required LOD section layout.")
    return result


def prepare_replacement_output(snapshot) -> MeshReplacementOutput:
    state = snapshot.replacement_state
    if state is None:
        raise ValueError("This session has no replacement output state.")
    validation = validate_replacement_geometry(snapshot.mesh, state, snapshot.original_data)
    if not validation.ok:
        raise ValueError("; ".join(issue.message for issue in validation.blockers))
    original = parse_mesh(snapshot.original_data, state.target_path)
    indices = bound_part_indices(snapshot.mesh, state)
    if {part.target_index for part in state.parts} != set(range(len(original.submeshes))):
        raise ValueError("Replacement mappings do not cover the original target sections.")
    snapshot = replace(snapshot, mesh=replacement_source_mesh(snapshot.mesh, state, original))
    mappings = [StaticSubmeshMapping(
        part.target_index, original.submeshes[part.target_index].name,
        [indices[part.part_id]] if part.included else [], part.target_index,
    ) for part in state.parts]
    options = manual_replacement_options(mappings, removed=[part.target_index for part in state.parts if not part.included])
    options.global_transform_exempt_source_indices = list(range(len(snapshot.mesh.submeshes)))
    if original.format.lower() == "pamlod":
        from cdmw.modding.static_mesh_runtime_builder import _build_mapped_replacement_mesh
        prepared = _build_mapped_replacement_mesh(original, snapshot.mesh, mappings, options)
        prepared.lod_levels = []  # The editor owns LOD0; the writer retains other levels.
        data = _build_replacement_pamlod(prepared, snapshot.original_data, state, original)
    else:
        preserved = ()
        original_parts = False
        if original.format.lower() == "pac":
            from cdmw.modding.mesh_pac_builder import _pac_submesh_channels_unchanged
            original_parts = all(_pac_submesh_channels_unchanged(
                original.submeshes[part.target_index], snapshot.mesh.submeshes[indices[part.part_id]])
                for part in state.parts)
            preserved = tuple(part.target_index for part in state.parts if part.included and
                _pac_submesh_channels_unchanged(original.submeshes[part.target_index], snapshot.mesh.submeshes[indices[part.part_id]]))
        hair = getattr(snapshot, "hair_state", None)
        preserve_hair_records = (original.format.lower() == "pac" and hair is not None
            and all(group["mode"] == "existing" for group in hair.payload["groups"])
            and all(part.included for part in state.parts)
            and all(len(before.vertices) == len(after.vertices) and before.faces == after.faces
                    and before.uvs == after.uvs and before.bone_indices == after.bone_indices
                    and before.bone_weights == after.bone_weights
                    for before, after in zip(original.submeshes, snapshot.mesh.submeshes, strict=True)))
        if original_parts and all(part.included for part in state.parts):
            # Mod inclusion does not author geometry or skin weights. Restoring
            # all original parts must retain skeletal and cloth guide lanes.
            data = snapshot.original_data
        elif preserve_hair_records:
            # Geometry-only grooming retains the exact skeletal and guide
            # records rather than passing them through a weight writer.
            from cdmw.modding.mesh_pac_builder import build_pac
            data = build_pac(snapshot.mesh, snapshot.original_data)
        elif (original_parts or (original.format.lower() == "pac" and hair is not None
                and all(group["mode"] == "existing" for group in hair.payload["groups"]))):
            from cdmw.modding.mesh_pac_builder import _build_pac_full_rebuild
            from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TARGET_DONOR
            from cdmw.modding.static_mesh_runtime_builder import _build_removed_runtime_placeholder_submesh
            prepared = copy.deepcopy(original if original_parts else snapshot.mesh)
            for binding in state.parts:
                index = binding.target_index
                output_index = index if original_parts else indices[binding.part_id]
                part = prepared.submeshes[output_index]
                if not binding.included:
                    placeholder = _build_removed_runtime_placeholder_submesh(original.submeshes[index])
                    # Retain the established hidden-section package contract,
                    # including the donor's skeletal and cloth guide records.
                    placeholder.source_vertex_map = [0] * len(placeholder.vertices)
                    placeholder.source_vertex_map_authority = SOURCE_VERTEX_MAP_TARGET_DONOR
                    placeholder.bone_indices = [original.submeshes[index].bone_indices[0]] * len(placeholder.vertices) if original.submeshes[index].bone_indices else []
                    placeholder.bone_weights = [original.submeshes[index].bone_weights[0]] * len(placeholder.vertices) if original.submeshes[index].bone_weights else []
                    prepared.submeshes[output_index] = placeholder
                elif len(part.source_vertex_map) != len(part.vertices):
                    raise ValueError("Existing hair lost its original vertex record provenance.")
            data = _build_pac_full_rebuild(original, prepared, snapshot.original_data,
                preserve_original_submesh_indices=preserved,
                preserve_source_skin_record_indices=tuple(range(len(prepared.submeshes))))
        else:
            data, _ = build_static_mesh_replacement(snapshot.original_data, original, snapshot.mesh, options,
                                                  preserve_original_pac_submesh_indices=preserved)
        if original.format.lower() == "pam":
            data = _preserve_pam_index_convention(data, snapshot.original_data)
    cloth_rules = {part.target_index: part.cloth for part in state.parts
                   if part.included and part.cloth is not None}
    if cloth_rules:
        if original.format.lower() != "pac":
            raise ValueError("Cloth influence editing is supported only for PAC meshes.")
        from cdmw.modding.pac_cloth import apply_pac_cloth_rules
        data = apply_pac_cloth_rules(data, cloth_rules, appearance=state.neutral_appearance)
    parsed = parse_mesh(data, state.target_path)
    if not parsed.submeshes or len(parsed.submeshes) != len(original.submeshes):
        raise ValueError("Replacement writer changed the required target section layout.")
    final_report = validate_mesh_export(parsed, exact_output=False, edit_operations=(), requires_edit_operations=False)
    if not final_report.ok:
        raise ValueError("Rebuilt replacement is invalid: " + "; ".join(i.message for i in final_report.blockers))
    files = list(state.companion_files)
    if original.format.lower() == "pam":
        paired_path = str(PurePosixPath(state.target_path).with_suffix(".pamlod"))
        paired = next((file for file in state.dependencies if file.path.casefold() == paired_path.casefold()), None)
        if paired is not None:
            from cdmw.modding.mesh_pamlod_builder import transfer_pam_edit_to_pamlod_mesh, build_pamlod
            try:
                lod_mesh = transfer_pam_edit_to_pamlod_mesh(parsed, snapshot.original_data, paired.data, paired.path)
                original_lod = parse_mesh(paired.data, paired.path)
                by_material = {}
                for part in state.parts:
                    material = original.submeshes[part.target_index].material
                    if material in by_material:
                        raise ValueError(f"Paired LOD material mapping is ambiguous: {material}")
                    by_material[material] = part
                for level_index, (level, original_level) in enumerate(zip(lod_mesh.lod_levels, original_lod.lod_levels, strict=True)):
                    for index, lod_part in enumerate(level):
                        binding = by_material.get(lod_part.material)
                        if binding is None:
                            raise ValueError(f"Paired LOD material has no target mapping: {lod_part.material}")
                        current = snapshot.mesh.submeshes[indices[binding.part_id]]
                        baseline = original.submeshes[binding.target_index]
                        if not binding.included and level_index == 0:
                            from cdmw.modding.static_mesh_runtime_builder import _build_removed_runtime_placeholder_submesh
                            level[index] = _build_removed_runtime_placeholder_submesh(original_level[index])
                        elif list(current.vertices) == list(baseline.vertices) and list(current.faces) == list(baseline.faces):
                            level[index] = original_level[index]
                lod_mesh.submeshes = lod_mesh.lod_levels[0]
                lod_data = _build_replacement_pamlod(lod_mesh, paired.data, state, original)
                checked_lod = parse_mesh(lod_data, paired.path)
                if len(checked_lod.submeshes) != len(original_lod.submeshes):
                    raise ValueError("Paired LOD writer changed the required section layout.")
            except Exception as exc:
                raise ValueError(f"Required companion {paired.path} could not be rebuilt: {exc}") from exc
            files.append(replace(paired, data=lod_data))
    seen = {state.target_path.casefold()}
    for file in files:
        path = PurePosixPath(file.path.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or ":" in str(path) or not file.data:
            raise ValueError(f"Invalid replacement companion: {file.path}")
        if str(path).casefold() in seen:
            raise ValueError(f"Duplicate replacement companion: {file.path}")
        seen.add(str(path).casefold())
    report = _build_rebuild_report(parsed, snapshot.original_data, data, validation_status="passed", output_path="", original_mesh=original)
    report = replace(report, export_snapshot={
        "session_id": snapshot.session_id, "mesh_revision": snapshot.mesh_revision,
        "replacement_revision": state.revision, "policy": "replacement_game_asset",
        "files": [{"path": f.path, "sha256": hashlib.sha256(f.data).hexdigest()} for f in files],
    })
    return MeshReplacementOutput(data, report, tuple(files), (snapshot.mesh_revision, snapshot.native_edit_revision, snapshot.material_generation))
