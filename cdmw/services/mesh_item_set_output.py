"""Fold editor parts into their own PAC sections before the existing exact writer."""
from __future__ import annotations

import copy
from dataclasses import replace

from cdmw.domain.mesh.operations import MeshEditOperation
from cdmw.domain.mesh.topology import (
    SubmeshTopologyProvenance, VertexOrigin, TOPOLOGY_PROVENANCE_VERSION,
    TOPOLOGY_OPERATION_PASTE_COPIES, topology_operation_metadata,
)
from cdmw.services.mesh_asset_context import PART_ATTRIBUTE, ORIGIN_ATTRIBUTE


def _provenance(part, original):
    lineage = part.topology_provenance
    if lineage is not None:
        if (lineage.original_vertex_count != len(original.vertices)
                or lineage.original_face_count != len(original.faces)):
            raise ValueError(f"Part topology no longer belongs to its source: {part.name}")
        return lineage
    # Direct copied/partitioned source records have an independently verifiable
    # mapping. Never infer derived vertices or new faces from nearest geometry.
    parents = list(part.source_vertex_map)
    if len(parents) != len(part.vertices) or any(i < 0 or i >= len(original.vertices) for i in parents):
        raise ValueError(f"Part lost its original vertex mapping: {part.name}")
    original_faces = {tuple(sorted(face)): i for i, face in enumerate(original.faces)}
    faces = [original_faces.get(tuple(sorted(parents[i] for i in face)), -1) for face in part.faces]
    if any(index < 0 for index in faces):
        raise ValueError(f"Part lost its original face mapping: {part.name}")
    return SubmeshTopologyProvenance(TOPOLOGY_PROVENANCE_VERSION, len(original.vertices), len(original.faces),
        tuple(VertexOrigin((i,), (1.0,)) for i in parents), tuple(faces))


def fold_asset_parts(asset, parts, operations):
    output, inclusion, folded_rows = [], [], []
    for index, original in enumerate(asset.source.mesh.submeshes):
        identity = asset.source_part_id(index)
        fragments = [part for part in parts if getattr(part, ORIGIN_ATTRIBUTE) == identity and part.vertices and part.faces]
        if not fragments:
            output.append(copy.deepcopy(original))
            inclusion.append(False)
            continue
        inclusion.append(True)
        # Flip Normals also reverses winding. Its existing normal-only row does
        # not authorize index writes; use the same verified original-relative
        # fragment rebuild as split/paste, even when only one fragment remains.
        winding_edit = (len(fragments) == 1 and fragments[0].faces != original.faces
                        and any(row.metadata.get("asset_part_id") == identity
                                and row.metadata.get("service_action") == "flip_normals" for row in operations))
        if len(fragments) == 1 and getattr(fragments[0], PART_ATTRIBUTE) == identity and not winding_edit:
            output.append(fragments[0])
            for row in operations:
                if row.metadata.get("asset_part_id") == identity:
                    folded_rows.append(replace(row, submesh_index=index))
            continue
        merged = copy.deepcopy(original)
        for channel in ("vertices", "normals", "uvs", "tangents", "tangent_signs", "bone_indices", "bone_weights",
                        "shader_masks", "source_vertex_map", "source_vertex_offsets"):
            values = [getattr(part, channel, ()) for part in fragments]
            setattr(merged, channel, [value for rows in values for value in rows]
                    if all(len(rows) == len(part.vertices) for rows, part in zip(values, fragments)) else [])
        merged.faces = []
        origins, face_origins, vertex_offset = [], [], 0
        for part in fragments:
            lineage = _provenance(part, original)
            origins.extend(lineage.vertex_origins)
            face_origins.extend(lineage.face_origins)
            merged.faces.extend(tuple(i + vertex_offset for i in face) for face in part.faces)
            vertex_offset += len(part.vertices)
        merged.topology_provenance = SubmeshTopologyProvenance(TOPOLOGY_PROVENANCE_VERSION,
            len(original.vertices), len(original.faces), tuple(origins), tuple(face_origins))
        merged.source_vertex_map_authority = "topology"
        merged.source_vertex_map = [origin.direct_parent for origin in origins]
        merged.source_vertex_offsets = [original.source_vertex_offsets[i] if i >= 0 else -1
                                        for i in merged.source_vertex_map]
        merged.vertex_count, merged.face_count = len(merged.vertices), len(merged.faces)
        output.append(merged)
        folded_rows.append(MeshEditOperation(TOPOLOGY_OPERATION_PASTE_COPIES, submesh_index=index,
            vertex_count=len(merged.vertices), source="item_set_parts", metadata=topology_operation_metadata(
                input_vertex_count=len(original.vertices), input_face_count=len(original.faces),
                output_vertex_count=len(merged.vertices), output_face_count=len(merged.faces),
                source_revision=0, result_revision=1)))
    return output, tuple(inclusion), tuple(folded_rows)


def apply_part_inclusion(rebuilt, snapshot):
    """Exclude sections only after the exact geometry writer has accepted them."""
    import hashlib
    from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementPart, PART_ID_ATTRIBUTE
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.services.mesh_replacement_output import prepare_replacement_output

    flags = snapshot.asset_part_inclusion
    if not flags or all(flags):
        return rebuilt
    mesh = parse_pac(rebuilt.data, snapshot.mesh.path)
    if len(mesh.submeshes) != len(flags) or not any(flags):
        raise ValueError("Item set output inclusion no longer matches its source sections")
    bindings = []
    for index, (part, included) in enumerate(zip(mesh.submeshes, flags, strict=True)):
        identity = f"item-set-output:{index}"
        setattr(part, PART_ID_ATTRIBUTE, identity)
        bindings.append(ReplacementPart(identity, index, included=included))
    state = MeshReplacementState(mesh.path, hashlib.sha256(rebuilt.data).hexdigest(), tuple(bindings))
    intermediate = replace(snapshot, original_data=rebuilt.data, mesh=mesh, base_mesh=copy.deepcopy(mesh),
        replacement_state=state, edit_operations=(), asset_part_inclusion=())
    included = prepare_replacement_output(intermediate)
    from cdmw.modding.mesh_importer import _build_rebuild_report
    report = _build_rebuild_report(parse_pac(included.data, snapshot.mesh.path), snapshot.original_data,
        included.data, validation_status=rebuilt.report.validation_status,
        output_path=rebuilt.report.output_path, original_mesh=snapshot.base_mesh)
    report = replace(report, topology_rebuild=rebuilt.report.topology_rebuild,
                     edit_operations=rebuilt.report.edit_operations)
    return replace(rebuilt, data=included.data, report=report)
