"""Experimental jiggle controls using the editor's reversible PAC output state."""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import struct

from cdmw.domain.mesh.jiggle import PacJiggleRule
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_jiggle import PAC_JIGGLE_MASK, PAC_JIGGLE_OFFSET, reduce_pac_jiggle_byte
from cdmw.services.mesh_replacement_import import (
    commit_replacement, initial_replacement_state, mesh_with_part_ids,
)


def _decoded_preview_state(authoring, session, metadata, appearance, eligible):
    """Publish an owned, immutable-input snapshot on the existing host worker.

    Positions are bound from the current Rust draw mesh at Play. Only rig and
    retained vertex records belong in this file, not large recurring UI state.
    """
    from cdmw.modding.mesh_parser import resolve_pac_bone_palette
    from cdmw.modding.mesh_skinning import pack_pac_skin_weights
    from cdmw.modding.pac_cloth_preview import (
        build_cloth_body_collider_snapshot, build_cloth_preview_snapshot, select_cloth_body_volumes,
    )
    from cdmw.modding.pac_jiggle_rig import prepare_jiggle_rig
    from cdmw.services.mesh_rust_authoring import _atomic_write_payload
    from cdmw.services.mesh_rust_cloth_guides import authored_cloth_source

    skeleton = session.skeleton
    if skeleton is None:
        return {"available": False, "reason": "Decoded motion needs a matching fixed-layout PAB skeleton."}
    revision = authoring.shadow_service.session_view(authoring.shadow_session_id).revision
    part_key = (authoring.replacement_comparison, tuple(index for index, _, _ in eligible))
    cached = metadata.get("decoded_cache")
    if cached is not None and cached[0] is skeleton and cached[1:3] == (revision, part_key):
        return dict(cached[3])
    try:
        cloth_data, generated_parts = authored_cloth_source(authoring, session)
        if not eligible or sum(len(current.vertices) for _, _, current in eligible) > 100_000:
            raise ValueError("Decoded motion needs retained PAC geometry within 100,000 vertices.")
        rig_cached = metadata.get("decoded_rig")
        if rig_cached is None or rig_cached[0] is not skeleton or rig_cached[2] is not cloth_data:
            palette = resolve_pac_bone_palette(session.original_data, skeleton)
            rig = prepare_jiggle_rig(skeleton, palette, appearance=appearance)
            rows = lambda matrices: [[list(matrix[i:i + 4]) for i in range(0, 16, 4)] for matrix in matrices]
            rig_payload = {"bone_palette": list(rig.bone_palette), "parents": list(rig.parents),
                           "inverse_bind_matrices": rows(rig.inverse_bind_matrices),
                           "neutral_global_matrices": rows(rig.neutral_global_matrices),
                           "neutral_local_matrices": rows(rig.neutral_local_matrices)}
            metadata["decoded_rig"] = (skeleton, rig_payload, cloth_data)
            try:
                cloth = build_cloth_preview_snapshot(cloth_data, rig_payload)
                collider_reason = ""
                collider_source = ""
                try:
                    inputs = {role: value[1] for role, value in authoring.cloth_collision_inputs.items()}
                    volumes, collider_source = select_cloth_body_volumes(session.original_data, skeleton, **inputs)
                    cloth["body_colliders"] = build_cloth_body_collider_snapshot(skeleton, rig_payload, volumes=volumes)
                except (ValueError, OverflowError, struct.error) as exc:
                    cloth["body_colliders"] = []
                    collider_reason = str(exc)
                metadata["decoded_cloth"] = (cloth, {
                    "available": True, "reason": "", "guide_count": len(cloth["fixed"]),
                    "fixed_count": sum(cloth["fixed"]),
                    "area_constraint_count": sum(row["kind"] == "triangle" for row in cloth["constraints"]),
                    "rotation_available": all(row is not None for row in cloth["orientation_neighbors"]),
                    "body_collider_count": len(cloth["body_colliders"]),
                    "body_collider_source": collider_source,
                    "body_collider_reason": collider_reason,
                })
            except ValueError as exc:
                metadata["decoded_cloth"] = (None, {"available": False, "reason": str(exc)})
        else:
            rig_payload = rig_cached[1]
        parts = []
        for index, original, current in eligible:
            count = len(current.vertices)
            if any(len(rows) != count for rows in (original.bone_indices, original.bone_weights,
                                                   current.bone_indices, current.bone_weights)):
                raise ValueError("Decoded motion needs complete retained skeletal weights.")
            records = []
            record_source = generated_parts[index] if generated_parts is not None else original
            if len(record_source.vertices) != count or record_source.faces != current.faces:
                raise ValueError("Generated guide preview requires unchanged render topology.")
            for vertex, offset in enumerate(record_source.source_vertex_offsets):
                record = bytearray(cloth_data[offset:offset + 40])
                if len(record) != 40 or original.source_vertex_stride != 40:
                    raise ValueError("Decoded motion needs complete 40-byte PAC records.")
                slots, weights = current.bone_indices[vertex], current.bone_weights[vertex]
                if generated_parts is None and (tuple(slots) != tuple(original.bone_indices[vertex])
                        or tuple(weights) != tuple(original.bone_weights[vertex])):
                    if (len(slots) != len(weights) or not slots
                            or any(type(slot) is not int or not 0 <= slot < len(rig_payload["bone_palette"]) for slot in slots)
                            or any(not math.isfinite(weight) or weight < 0 for weight in weights)):
                        raise ValueError("Decoded motion has invalid current skeletal weights.")
                    pack_pac_skin_weights(record, slots, weights, context="jiggle preview")
                # Keep every unchanged lane byte-for-byte, including guide data.
                records.append(record.hex())
            parts.append({"index": index, "records": records})
        payload = {"version": 1, "rig": rig_payload, "parts": parts}
        cloth, cloth_state = metadata["decoded_cloth"]
        if cloth is not None:
            payload["cloth"] = cloth
        file_cache = metadata.get("decoded_file")
        if file_cache is None or file_cache[0] != payload:
            reference = _atomic_write_payload(
                authoring.root, "jiggle-rig.json", payload, data_type="jiggle_rig_json",
                element_count=len(parts), expected_root_identity=authoring.root_identity)
            metadata["decoded_file"] = (payload, reference)
        result = {"available": True, "reason": "", "file": dict(metadata["decoded_file"][1]), "cloth": cloth_state}
    except ValueError as exc:
        result = {"available": False, "reason": str(exc)}
    metadata["decoded_cache"] = (skeleton, revision, part_key, result)
    return dict(result)


def jiggle_ui_state(authoring, replacement):
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    state = session.replacement_state
    reason = replacement["reason"]
    if session.mesh_format != "pac":
        reason = "Jiggle editing requires an original PAC mesh."
    elif session.hair_state is not None:
        reason = "Finish the hair workflow before editing jiggle."
    if reason:
        return {"available": False, "reason": reason, "parts": [], "overlay_parts": []}
    data = session.original_data
    appearance = state.neutral_appearance if state and state.neutral_appearance is not None else authoring.neutral_appearance
    cached = authoring.jiggle_source_cache
    if cached is None or cached[0] is not data or cached[1] is not appearance:
        try:
            levels = pac_cloth_lods(data)
            displayed = appearance.to_neutral(levels[0]) if appearance is not None else levels[0]
            rows = []
            source_heights = []
            for index, part in enumerate(levels[0].submeshes):
                heights = [point[1] for point in displayed.submeshes[index].vertices]
                source_heights.append(heights)
                counts = [sum(data[offset + PAC_JIGGLE_OFFSET] & PAC_JIGGLE_MASK != PAC_JIGGLE_MASK
                              for offset in level.submeshes[index].source_vertex_offsets) for level in levels]
                rows.append({"lod_counts": counts,
                             "relative_available": True,
                             "min_y": min(heights, default=0.0), "max_y": max(heights, default=0.0)})
            metadata = {"parts": rows, "lod_count": len(levels), "reason": ""}
            # Retain the parsed LOD0 privately: source record ownership is required
            # before supplying vertex flags to the renderer (counts are not proof).
            metadata["source_parts"] = levels[0].submeshes
            metadata["source_heights"] = source_heights
        except ValueError as exc:
            metadata = {"parts": [], "lod_count": 0, "reason": str(exc)}
        authoring.jiggle_source_cache = (data, appearance, metadata)
    else:
        metadata = cached[2]
    bindings = {part.part_id: part for part in state.parts} if state else {}
    from cdmw.services.mesh_rust_cloth_guides import authored_cloth_source
    generated_error = ""
    try:
        generated_data, generated_parts = authored_cloth_source(authoring, session)
    except ValueError as exc:
        generated_data, generated_parts, generated_error = data, None, str(exc)
    parts = []
    overlay_parts = []
    eligible = []
    for part in replacement["parts"]:
        binding = bindings.get(part["id"])
        index = binding.target_index if binding else part["index"]
        if not 0 <= index < len(metadata["parts"]):
            continue
        source = metadata["parts"][index]
        original = metadata["source_parts"][index]
        current = session.working_mesh.submeshes[part["index"]]
        rule = binding.jiggle if binding else None
        preview = {"available": False}
        if (not (binding and binding.import_positions)
                and current.topology_provenance is None
                and len(current.vertices) == len(original.vertices)
                and current.source_vertex_map == list(range(len(original.vertices)))
                and current.source_vertex_offsets == original.source_vertex_offsets
                and current.faces == original.faces):
            original_bytes = [data[offset + PAC_JIGGLE_OFFSET] for offset in original.source_vertex_offsets]
            current_bytes = [reduce_pac_jiggle_byte(value, rule.retained)
                             if rule and (rule.below_y is None or current.vertices[i][1] < rule.below_y)
                             else value for i, value in enumerate(original_bytes)]
            candidates = [i for i, value in enumerate(original_bytes) if value & PAC_JIGGLE_MASK != PAC_JIGGLE_MASK]
            active = [i for i, value in enumerate(current_bytes) if value & PAC_JIGGLE_MASK != PAC_JIGGLE_MASK]
            original_cloth = [data[offset + 39] & 63 for offset in original.source_vertex_offsets]
            authored_cloth = original_cloth
            if generated_parts is not None:
                generated = generated_parts[index]
                if len(generated.vertices) != len(current.vertices) or generated.faces != current.faces:
                    overlay_parts.append({"index": part["index"], "preview": {"available": False}})
                    continue
                authored_cloth = [generated_data[offset + 39] & 63 for offset in generated.source_vertex_offsets]
            cloth_rule = binding.cloth if binding else None
            current_cloth = [cloth_rule.blend(value, metadata["source_heights"][index][i]) if cloth_rule else value
                             for i, value in enumerate(authored_cloth)]
            preview = {"available": True, "vertex_count": len(current.vertices),
                       "original_vertices": candidates, "current_vertices": active,
                       "original_bytes": original_bytes, "current_bytes": current_bytes,
                       "original_cloth_bytes": original_cloth, "current_cloth_bytes": current_cloth}
            eligible.append((part["index"], original, current))
        overlay_parts.append({"index": part["index"], "preview": preview})
        if not any(source["lod_counts"]) and not (binding and binding.jiggle):
            continue
        parts.append({**part, **source, "rule": rule.to_dict() if rule else None, "preview": preview})
    reason = metadata["reason"] or ("This PAC has zero vertex jiggle contribution on every vertex." if not parts else "")
    return {"available": not reason, "reason": reason, "parts": parts,
            "overlay_parts": overlay_parts, "lod_count": metadata["lod_count"],
            "collision_inputs": {role: value[0] for role, value in authoring.cloth_collision_inputs.items()},
            "decoded": ({"available": False, "reason": generated_error} if generated_error else
                        _decoded_preview_state(authoring, session, metadata, appearance, eligible))}


def set_cloth_collision_input(authoring, args, stop_event):
    """Validate a bounded, explicit preview input before atomically publishing it.

    Runs on the existing host command worker. Input snapshots are session-only;
    source meshes, output rules and the mesh undo stack are never changed.
    """
    from cdmw.modding.pabv_parser import decode_pabv
    from cdmw.modding.pac_cloth_preview import build_cloth_body_collider_snapshot, select_cloth_body_volumes
    from cdmw.services.mesh_rust_authoring import _atomic_write_payload
    from cdmw.services.mesh_rust_replacement import replacement_ui_state

    clear = args == {"clear": True} and type(args["clear"]) is bool
    if not clear and (set(args) != {"role", "path"} or args.get("role") not in ("body", "head")
                      or not isinstance(args.get("path"), str) or not args["path"]):
        raise ValueError("Choose a body or head PABV input, or clear the preview inputs.")
    candidate = {} if clear else dict(authoring.cloth_collision_inputs)
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    ui = jiggle_ui_state(authoring, replacement_ui_state(authoring))
    decoded = ui.get("decoded", {})
    cloth_state = decoded.get("cloth", {})
    if not clear:
        if not decoded.get("available") or not cloth_state.get("available"):
            raise ValueError("Collision inputs need a decoded cloth preview and matching rig.")
        if cloth_state.get("body_collider_source") == "pac_model":
            raise ValueError("This model's embedded collision volumes take precedence over appearance inputs.")
        path = Path(args["path"])
        if not path.is_absolute() or path.suffix.lower() != ".pabv":
            raise ValueError("Choose an absolute path to a PABV file.")
        authoring._raise_if_cancelled(stop_event)
        with path.open("rb") as source:
            data = source.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("Collision preview inputs must be at most 8 MiB.")
        authoring._raise_if_cancelled(stop_event)
        candidate[args["role"]] = (path.name, decode_pabv(data))
    authoring._raise_if_cancelled(stop_event)
    if candidate == authoring.cloth_collision_inputs:
        return {"changed": False}
    cached = authoring.jiggle_source_cache
    updated = None
    if decoded.get("available") and cloth_state.get("available"):
        metadata = dict(cached[2])
        rig = metadata["decoded_rig"][1]
        source_name, reason = "", ""
        try:
            volumes, source_name = select_cloth_body_volumes(
                session.original_data, session.skeleton, **{role: value[1] for role, value in candidate.items()})
            if not clear and source_name == "pac_model":
                raise ValueError("This model's embedded collision volumes take precedence over appearance inputs.")
            colliders = build_cloth_body_collider_snapshot(session.skeleton, rig, volumes=volumes)
        except (ValueError, OverflowError, struct.error) as exc:
            if not clear:
                raise
            # Clearing also works when the default source has no supported contacts.
            colliders, reason = [], str(exc)
        cloth = {**metadata["decoded_cloth"][0], "body_colliders": colliders}
        state = {**cloth_state, "body_collider_count": len(colliders),
                 "body_collider_source": source_name, "body_collider_reason": reason}
        payload = {**metadata["decoded_file"][0], "cloth": cloth}
        authoring._raise_if_cancelled(stop_event)
        reference = _atomic_write_payload(authoring.root, "jiggle-rig.json", payload,
                                         data_type="jiggle_rig_json", element_count=len(payload["parts"]),
                                         expected_root_identity=authoring.root_identity)
        metadata["decoded_cloth"] = (cloth, state)
        metadata["decoded_file"] = (payload, reference)
        metadata["decoded_cache"] = (session.skeleton, session.revision + 1, metadata["decoded_cache"][2],
                                     {**decoded, "file": dict(reference), "cloth": state})
        updated = (cached[0], cached[1], metadata)
    else:
        authoring._raise_if_cancelled(stop_event)
    # No cancellation points after the atomic file publication.
    authoring.cloth_collision_inputs = candidate
    authoring.jiggle_source_cache = updated
    with session.export_lock:
        session.revision += 1
    return {"changed": True}


def set_jiggle_rule(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    ui = jiggle_ui_state(authoring, replacement_ui_state(authoring))
    if not ui["available"]:
        raise ValueError(ui["reason"])
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError("Invalid jiggle reset request.")
    keys = args.get("part_ids")
    if (not isinstance(keys, (list, tuple)) or not keys
            or any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys)):
        raise ValueError("Choose unique jiggle parts.")
    available = {part["id"] for part in ui["parts"] if part["included"]}
    if not set(keys) <= available:
        raise ValueError("Choose included parts with editable jiggle data.")
    rule = None if reset else PacJiggleRule.from_dict(args.get("rule"))
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    parts = tuple(replace(part, jiggle=rule) if part.part_id in keys else part for part in state.parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    state = replace(state, parts=parts, revision=state.revision + 1)
    mesh = mesh_with_part_ids(snapshot, state)
    return commit_replacement(authoring.shadow_service, snapshot, mesh, state,
                              label="Restore original jiggle" if reset else "Set jiggle contribution",
                              stop_event=stop_event)
