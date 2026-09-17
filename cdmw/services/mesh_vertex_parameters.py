"""Authoritative vertex inspection and candidate-only batch authoring.

The Rust render document intentionally omits skin/cloth and may supply display
defaults for missing channels. This service never reads that document.
"""

from __future__ import annotations

import copy
import math
from dataclasses import replace

from cdmw.domain.mesh.vertex_parameters import NumericSummary, channel_edit, edit_weights, selected_vertices
from cdmw.domain.mesh.replacement import bound_part_indices
from cdmw.domain.mesh.topology import validate_topology_provenance
from cdmw.modding.mesh_skinning import source_vertex_map_is_target_donor_lineage
from cdmw.modding.pac_cloth import pac_cloth_binding
from cdmw.modding.mesh_parser import PAC_SKIN_WEIGHT_LAYOUT
from cdmw.services.mesh_rust_contract import RUST_MESH_EDIT_BACKEND

MAX_PAGE_SIZE = 128
_CHANNELS = {"position": ("vertices", 3), "uv0": ("uvs", 2), "normal": ("normals", 3), "tangent": ("tangents", 3)}
_OPERATIONS = {"position": "replace_positions_same_count", "uv0": "replace_uv0_same_count",
               "normal": "replace_normals_same_count", "weights": "replace_skin_weights_same_count"}


def inspection_token(authoring):
    view = authoring.shadow_service.session_view(authoring.shadow_session_id)
    return {"session_id": authoring.session_id, "mesh_revision": int(view.revision),
            "selection_revision": int(view.selection_revision), "topology_generation": int(view.topology_generation)}


def _require_token(authoring, token):
    if (not isinstance(token, dict) or any(type(token.get(key)) is not int for key in
            ("mesh_revision", "selection_revision", "topology_generation")) or token != inspection_token(authoring)):
        raise ValueError("Vertex selection or mesh changed. Inspect the current selection again.")


def _row(part, index, channel):
    attribute, width = _CHANNELS[channel]
    rows = getattr(part, attribute, ())
    if len(rows) != len(part.vertices):
        return None
    row = rows[index]
    return tuple(row) if len(row) == width and all(math.isfinite(v) for v in row) else None


def _context(authoring, check):
    from cdmw.services.mesh_rust_authoring import _rust_skin_weight_capability
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    check()
    mesh = session.working_mesh
    scope = selected_vertices(mesh, session.selection, check)
    view = authoring.shadow_service.session_view(authoring.shadow_session_id)
    reason = "" if view.authoring_enabled else view.output_policy_reason or "Authoring is unavailable."
    if authoring.replacement_comparison != "edit":
        raise ValueError("Return to Edit comparison to inspect the current editable vertices.")
    if session.hair_state is not None and not session.hair_state.payload["converted"]:
        reason = "Convert hair guides to ordinary geometry before editing vertex parameters."
    if view.lod_index != 0 and view.output_policy != "free_edit_rebuild":
        reason = "Vertex edits require the active supported LOD 0."
    capability = _rust_skin_weight_capability(session)
    return session, mesh, scope, view, reason, capability


def _capabilities(session, mesh, scope, view, reason, skin, neutral_appearance):
    total = sum(map(len, scope.values()))
    editable_format = view.mesh_format.lower() in {"pac", "pam", "pamlod"} or view.output_policy == "free_edit_rebuild"
    unproven_map = view.output_policy == "exact_game_asset" and any(
        len(mesh.submeshes[p].source_vertex_map) != len(mesh.submeshes[p].vertices)
        or any(type(index) is not int or index < 0 for index in mesh.submeshes[p].source_vertex_map)
        for p in scope)
    result = {}
    for channel in _CHANNELS:
        missing = any(len(getattr(mesh.submeshes[p], _CHANNELS[channel][0], ())) != len(mesh.submeshes[p].vertices) for p in scope)
        why = reason
        if not why and unproven_map:
            why = "This selection has no proven source mapping for same-count channel edits."
        if not why and (not editable_format or channel == "tangent" or channel == "normal" and view.mesh_format.lower() in {"pam", "pamlod"} and view.output_policy != "free_edit_rebuild"):
            why = "This channel has no proven writeback in the current output format."
        if missing:
            why = "This channel is missing from one or more selected parts."
        result[channel] = {"editable": bool(total and not why), "reason": why,
                           "available": bool(total and not missing)}
    why = reason or (skin.reason if not skin.enabled else "")
    if not why and neutral_appearance is not None and len({
        tuple(neutral_appearance.skin_matrices[index]) for index in neutral_appearance.bone_palette
        if 0 <= index < len(neutral_appearance.skin_matrices)
    }) > 1:
        why = "Skin weights are read-only while neutral appearance uses different bone transforms; changing them could move saved vertices."
    if not why and any(p not in skin.eligible_submesh_indices for p in scope):
        why = "One or more selected parts cannot preserve exact PAC skin weights."
    result["weights"] = {"editable": bool(total and not why), "reason": why}
    for channel, why in (("cloth", "Read-only; use Cloth controls to change saved influence rules."),
                         ("uv1", "UV1 is not decoded in the working mesh."),
                         ("colours", "Vertex colours are not decoded in the working mesh."),
                         ("undecoded", "Undecoded fields are preserved; raw-byte editing is unsupported.")):
        result[channel] = {"editable": False, "reason": why}
    result["tangent"]["reason"] = "Read-only. Authored tangent writeback is not supported by the PAC save path."
    return result


def _source_context(session):
    base = session.source_coordinate_base_mesh or session.base_mesh
    bindings = {}
    if session.replacement_state is not None:
        indices = bound_part_indices(session.working_mesh, session.replacement_state)
        bindings = {indices[part.part_id]: part for part in session.replacement_state.parts}
    return base, bindings


def _source_mapping(part, vertex, binding, donor_lineage, topology_lineage):
    replaced = bool(binding and binding.import_positions)
    provenance = getattr(part, "topology_provenance", None)
    if provenance is not None and vertex < len(provenance.vertex_origins):
        origin = provenance.vertex_origins[vertex]
        if origin.derived:
            return {"kind": "generated", "original_index": None,
                    "parents": list(origin.parents) if topology_lineage else []}
        if topology_lineage:
            return {"kind": "copied", "original_index": origin.direct_parent}
    if donor_lineage:
        index = part.source_vertex_map[vertex]
        return {"kind": "replacement donor" if replaced else "source", "original_index": index}
    return {"kind": "replaced" if replaced else "unmapped", "original_index": None}


def _cloth_output(authoring, session, check):
    """Use the saved output rule, including quantization and neutral transforms.

    Only needed for saved rules. The pure replacement builder operates on a
    snapshot: no material staging, history, document publication or archive I/O.
    """
    state = session.replacement_state
    if state is None or not any(part.cloth is not None and part.cloth.fixed_above is not None for part in state.parts):
        return None
    check()
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.services.mesh_service_state import MeshExportSnapshot
    # The protocol and export locks pin these inputs for the query. Do not
    # capture textures/material resources just to resolve a cloth threshold.
    snapshot = MeshExportSnapshot(
        session_id=session.session_id, mesh_revision=session.revision, native_edit_revision=0,
        material_generation=session.material_generation, texture_revisions=(), mesh=session.working_mesh,
        base_mesh=session.base_mesh, original_data=session.original_data, replacement_state=state,
        hair_state=session.hair_state, edit_operations=tuple(session.edit_operations))
    output = prepare_replacement_output(snapshot)
    check()
    return output.data, parse_pac(output.data, state.target_path)


def _cloth_row(session, part, vertex, original, mapping, binding, output):
    index = mapping["original_index"]
    unavailable = {"available": False, "reason": "No proven source cloth mapping for this vertex."}
    if (session.mesh_format != "pac" or original is None or original.source_vertex_stride != 40
            or index is None or not 0 <= index < len(original.source_vertex_offsets)):
        return unavailable
    try:
        source = pac_cloth_binding(session.original_data, original.source_vertex_offsets[index])
        source_blend = source[0] if source else 63
        effective = source_blend
        if binding is not None and binding.cloth is not None:
            if not binding.included:
                return {**unavailable, "reason": "This part has no proven cloth output."}
            if binding.cloth.fixed_above is None:
                effective = binding.cloth.blend(source_blend, 0.0)
            else:
                if output is None:
                    return unavailable
                data, written = output
                target = written.submeshes[binding.target_index]
                if len(target.vertices) != len(part.vertices) or len(target.source_vertex_offsets) != len(part.vertices):
                    return unavailable
                saved = pac_cloth_binding(data, target.source_vertex_offsets[vertex])
                effective = saved[0] if saved else 63
        return {"available": True, "original_influence": (63 - source_blend) / 63,
                "effective_influence": (63 - effective) / 63, "fixed": effective == 63,
                "guide_indices": list(source[1]) if source else [],
                "guide_weights": list(source[2]) if source else []}
    except (ValueError, IndexError):
        return unavailable


def _weight_row(part, vertex, skin, bones):
    if len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices):
        return None
    indices, weights = part.bone_indices[vertex], part.bone_weights[vertex]
    if len(indices) != len(weights) or any(not math.isfinite(w) for w in weights):
        return None
    rows = []
    for slot, weight in zip(indices, weights):
        ordinal = skin.palette[slot] if 0 <= slot < len(skin.palette) else -1
        bone = bones[ordinal] if 0 <= ordinal < len(bones) else None
        rows.append({"slot": slot, "bone": bone.index if bone else None,
                     "name": bone.name if bone else None, "weight": weight})
    return {"influences": rows, "total": sum(weights), "resolved": all(row["bone"] is not None for row in rows)}


def inspect_vertices(authoring, args, check):
    if set(args) - {"token", "page", "page_size"}:
        raise ValueError("Unsupported vertex inspection arguments.")
    _require_token(authoring, args.get("token"))
    page, size = args.get("page", 0), args.get("page_size", MAX_PAGE_SIZE)
    if type(page) is not int or page < 0 or type(size) is not int or not 1 <= size <= MAX_PAGE_SIZE:
        raise ValueError("Vertex inspection pages contain at most 128 rows.")
    session, mesh, scope, view, reason, skin = _context(authoring, check)
    count = sum(map(len, scope.values()))
    page = min(page, max(0, (count - 1) // size))
    summaries = {channel: NumericSummary(width) for channel, (_, width) in _CHANNELS.items()}
    weight_summary = NumericSummary(1)
    influences = {}
    cloth_summaries = {key: NumericSummary(1) for key in ("original_influence", "effective_influence")}
    fixed_count = 0
    base, bindings = _source_context(session)
    descriptors = {}
    for index, original in enumerate(base.submeshes):
        descriptor = original.source_descriptor_offset
        if descriptor >= 0:
            descriptors[descriptor] = None if descriptor in descriptors else index
    bones = tuple(getattr(session.skeleton, "bones", ()) or ())
    rows, ordinal = [], 0
    output, cloth_error = None, ""
    if count:
        try:
            output = _cloth_output(authoring, session, check)
        except ValueError as exc:
            cloth_error = str(exc)
    for part_index, indices in scope.items():
        part = mesh.submeshes[part_index]
        binding = bindings.get(part_index)
        source_index = binding.target_index if binding else descriptors.get(part.source_descriptor_offset)
        original = base.submeshes[source_index] if source_index is not None and 0 <= source_index < len(base.submeshes) else None
        donor_lineage = original is not None and source_vertex_map_is_target_donor_lineage(original, part)
        provenance = part.topology_provenance
        topology_lineage = bool(original is not None and provenance is not None
            and not (binding and binding.import_positions)
            and part.source_descriptor_offset == original.source_descriptor_offset >= 0
            and provenance.original_vertex_count == len(original.vertices)
            and provenance.original_face_count == len(original.faces)
            and not validate_topology_provenance(provenance, output_vertex_count=len(part.vertices),
                                                output_face_count=len(part.faces), enforce_pac_index_limit=False))
        for vertex in indices:
            if ordinal % 128 == 0:
                check()
            values = {channel: _row(part, vertex, channel) for channel in _CHANNELS}
            for channel, summary in summaries.items():
                summary.add(values[channel])
            weights = _weight_row(part, vertex, skin, bones)
            weight_summary.add((weights["total"],) if weights else None)
            if weights:
                for influence in weights["influences"]:
                    summary = influences.setdefault(influence["slot"], (influence, NumericSummary(1)))[1]
                    summary.add((influence["weight"],))
            mapping = _source_mapping(part, vertex, binding, donor_lineage, topology_lineage)
            cloth = _cloth_row(session, part, vertex, original, mapping, binding, output)
            if cloth_error:
                cloth = {"available": False, "reason": cloth_error}
            if cloth["available"]:
                fixed_count += int(cloth["fixed"])
                for key, summary in cloth_summaries.items():
                    summary.add((cloth[key],))
            if page * size <= ordinal < (page + 1) * size:
                rows.append({"part": part_index, "part_name": part.name, "vertex": vertex,
                             "source": {"part": source_index if donor_lineage or topology_lineage else None, **mapping},
                             **values, "weights": weights, "cloth": cloth})
            ordinal += 1
    check()
    _require_token(authoring, args.get("token"))
    weight_summaries = []
    for slot, (influence, summary) in sorted(influences.items()):
        if summary.count < weight_summary.count:
            summary.add((0.0,))
            summary.count = weight_summary.count
        weight_summaries.append({"slot": slot, "bone": influence["bone"], "name": influence["name"], **summary.payload(count)})
    return {"token": inspection_token(authoring), "count": count, "page": page, "page_size": size,
            "rows": rows, "summaries": {**{k: v.payload(count) for k, v in summaries.items()}, "weight_total": weight_summary.payload(count)},
            "weight_summaries": weight_summaries,
            "cloth_summary": {**{key: value.payload(count) for key, value in cloth_summaries.items()}, "fixed_count": fixed_count},
            "capabilities": _capabilities(session, mesh, scope, view, reason, skin, authoring.neutral_appearance),
            "bones": [{"bone": bone, "slot": slot, "name": bones[skin.palette[slot]].name}
                      for bone, slot in skin.skeleton_bone_to_palette_slot.items()],
            "space": "Model editing space (neutral appearance)" if authoring.neutral_appearance is not None else "Model editing space",
            "lod": view.lod_index}


def edit_vertices(authoring, args, check):
    from cdmw.services.mesh_rust_authoring import _pac_skin_row_capacity, _validation_blockers
    from cdmw.services.mesh_service import _invalidate_tangents_after_edit
    if set(args) != {"token", "edits"}:
        raise ValueError("Vertex edits require the inspected token and channel edits.")
    _require_token(authoring, args["token"])
    session, mesh, scope, view, reason, skin = _context(authoring, check)
    edits = args["edits"]
    if not isinstance(edits, dict) or not edits or set(edits) - set(_OPERATIONS):
        raise ValueError("Choose supported vertex channels to edit.")
    capabilities = _capabilities(session, mesh, scope, view, reason, skin, authoring.neutral_appearance)
    for channel in edits:
        if not capabilities[channel]["editable"]:
            raise ValueError(capabilities[channel]["reason"] or "Select vertices before applying an edit.")
    candidate = authoring.shadow_service.working_mesh(authoring.shadow_session_id, clone=True)
    operations = list(session.edit_operations)
    changed = set()
    changed_geometry = set()
    for part_index, indices in scope.items():
        part = candidate.submeshes[part_index]
        for channel, edit in edits.items():
            # Native snapshot caching tracks channel container identity. Publish
            # fresh candidate lists, just like the existing geometry transaction.
            # In-place row assignment in a cached list can restore old values.
            attributes = ("bone_indices", "bone_weights") if channel == "weights" else (_CHANNELS[channel][0],)
            for attribute in attributes:
                setattr(part, attribute, list(getattr(part, attribute)))
            channel_changed = False
            for ordinal, vertex in enumerate(indices):
                if ordinal % 128 == 0:
                    check()
                if channel == "weights":
                    if not isinstance(edit, dict):
                        raise ValueError("Invalid skin-weight edit.")
                    bone = edit.get("bone")
                    if edit.get("mode") != "normalize" and (type(bone) is not int or bone not in skin.skeleton_bone_to_palette_slot):
                        raise ValueError("The chosen bone has no resolved PAC palette mapping.")
                    before = part.bone_indices[vertex], part.bone_weights[vertex]
                    after = edit_weights(*before, edit, slot=skin.skeleton_bone_to_palette_slot.get(bone),
                                         capacity=_pac_skin_row_capacity(session.original_data, part.source_vertex_offsets[vertex]))
                    if before != after:
                        part.bone_indices[vertex], part.bone_weights[vertex] = after
                        channel_changed = True
                else:
                    row = _row(part, vertex, channel)
                    if row is None:
                        raise ValueError(f"{channel} is missing or invalid in part {part_index}, vertex {vertex}.")
                    limit = 65504.0 if view.mesh_format.lower() in {"pac", "pam", "pamlod"} and view.output_policy != "free_edit_rebuild" else None
                    result = channel_edit(row, edit, channel=channel, uv_limit=limit)
                    if row != result:
                        getattr(part, _CHANNELS[channel][0])[vertex] = result
                        channel_changed = True
            if channel_changed:
                changed.add(part_index)
                if channel != "weights":
                    changed_geometry.add(part_index)
                operations.append({"operation": _OPERATIONS[channel], "lod_index": view.lod_index,
                                   "submesh_index": part_index, "vertex_count": len(part.vertices),
                                   "source": RUST_MESH_EDIT_BACKEND, "created_by": "CDMW Vertex Parameters",
                                   **({"metadata": {"contract": "cdmw_exact_pac_skin_weights_v1", "layout": PAC_SKIN_WEIGHT_LAYOUT,
                                                     "vertex_stride": 40, "palette_size": len(skin.palette),
                                                     "service_action": "vertex_edit"}} if channel == "weights" else {})})
    if not changed:
        return {"changed": False, "count": sum(map(len, scope.values()))}
    _invalidate_tangents_after_edit(candidate, "transform", changed_geometry, {}, topology_changed=False)
    candidate._cdmw_edit_operations = tuple(operations)
    candidate._cdmw_requires_edit_operations = True
    prepared = authoring.shadow_service.prepare_working_mesh_replacement(authoring.shadow_session_id, candidate)
    blockers = _validation_blockers(prepared.validation_report)
    if blockers:
        raise ValueError(blockers[0])
    size = authoring._preflight_mesh_document_capacity(prepared.working_mesh)
    check()
    _require_token(authoring, args["token"])
    authoring.shadow_service.commit_prepared_working_mesh_replacement(
        replace(prepared, selection=session.selection), history_action="rust_transaction",
        history_label=f"Vertex Parameters ({sum(map(len, scope.values()))} vertices)",
        object_transform=copy.deepcopy(session.object_transform), require_reversible_history=True)
    authoring.max_state_document_bytes = max(authoring.max_state_document_bytes, size)
    return {"changed": True, "count": sum(map(len, scope.values()))}
