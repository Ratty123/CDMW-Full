"""Exact profile inspection, preview conversion and reversible raw profile edits.

Captured documents stay immutable. Only explicit authoring commands persist raw
XML overrides; preview coefficients and the live game variant are never saved.
"""

from __future__ import annotations

import struct
import hashlib
import math
from dataclasses import replace
from types import SimpleNamespace

from cdmw.core.pbd_cloth import _material_scalar_items, _parse_xml, parse_pbd_sidecar_hints, collect_pbd_config_materials
from cdmw.domain.mesh.physics_profile import PROFILE_VALUE_RANGES, PacPhysicsProfileRule
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.modding._pbd_numeric import f32, round_pbd_half
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from cdmw.modding.pac_cloth_runtime import update_cloth_frame_stiffness
from cdmw.services.mesh_physics_profiles import _xml_text, _profile_path, resolve_saved_physics_profiles
from cdmw.modding.pbd_profile_edit import ProfileXml


_SCALARS = ("simulationmode", "useautoweightingpositionblending") + tuple(
    key.casefold() for key in PROFILE_VALUE_RANGES
)


def _profile_preview(document):
    result = {"path": document.path, "sha256": document.sha256,
              "authored": {}, "preview": None, "reason": ""}
    root = _parse_xml(_xml_text(document.data))
    items = _material_scalar_items(root) if root is not None else ()
    values = {key: value for key, value in items if key in _SCALARS}
    result["authored"] = values
    if values.get("simulationmode", "").casefold() != "cloth":
        result["reason"] = "Only an explicit cloth profile can supply guide-cloth preview settings."
        return result
    required = ("stretchingstiffness", "bendingstiffness", "damping", "gravity", "solveriterationcount")
    if any(key not in values for key in required):
        result["reason"] = "The profile does not explicitly supply all supported preview coefficients."
        return result
    try:
        stretch, bend, damping, gravity = (f32(float(values[key])) for key in required[:4])
        if not all(math.isfinite(value) for value in (stretch, bend, damping, gravity)):
            raise ValueError
        iterations = int(values["solveriterationcount"])
        # The CPU material parser rounds odd XML counts upward. This preview
        # still uses its controlled loop, not the game's LOD/dispatch admission.
        iterations += iterations & 1
        if not (-100 <= gravity <= 100 and 0 <= damping <= 10 and 1 <= iterations <= 8):
            result["reason"] = "Authored values exceed the supported cloth preview range."
            return result
        # Decoded material initialization: alpha enabled; mode processing resets
        # rotation (cloth=on, spline=off) in XML source order.
        alpha, rotation = True, False
        for key, value in items:
            if key == "simulationmode":
                rotation = value.casefold() == "cloth"
            elif key in ("usevertexalphapositionblending", "userotationcorrection"):
                if value not in ("0", "1"):
                    result["reason"] = "A supported profile flag is not an explicit zero or one."
                    return result
                if key == "usevertexalphapositionblending":
                    alpha = value == "1"
                else:
                    rotation = value == "1"
        # Recovered initialization globals, never presented as captured live
        # settings. Read the packed half coefficients actually supplied to GPU.
        frame = update_cloth_frame_stiffness(
            bytes(100), simulation_mode=1, stretching_stiffness=stretch,
            bending_stiffness=bend, area_stiffness=0, restore_angle_stiffness=0,
            underwater_restore_angle_stiffness=-1, stiffness_denominator=4,
            scale_factors=(5, 1, 1, 1), limits=(.6, .06, .6, .06),
            bend_uses_unit_denominator=True,
        )["per_frame"]
        modified_stretch, modified_bend = struct.unpack_from("<2e", frame, 66)
        result["preview"] = {
            "gravity": -round_pbd_half(gravity), "damping": round_pbd_half(damping),
            "stretch": modified_stretch, "bend": max(0., modified_bend),
            "iterations": iterations, "use_vertex_alpha": alpha, "rotate_guides": rotation,
        }
    except (ValueError, OverflowError):
        result["reason"] = "The profile contains invalid or unsupported preview values."
    return result


def _cloth_geometry(data):
    """Report source guides independently of profile metadata or rig availability."""
    try:
        guides = decode_pac_cloth_guides(data)
    except ValueError as exc:
        return {"status": "unsupported", "reason": str(exc)}
    if guides is None or not guides.vertices:
        return {"status": "absent", "guide_count": 0}
    return {"status": "available", "guide_count": len(guides.vertices),
            "fixed_count": guides.channel_b.count(255)}


def physics_profiles_ui_state(authoring, replacement):
    """Project retained sources using original PAC part names and target indices."""
    session = authoring.shadow_service._session(authoring.shadow_session_id)
    incoming = authoring.physics_profile_context
    state = session.replacement_state
    data = session.original_data
    cached = authoring.physics_profile_cache
    if cached is None or cached[0] is not data or cached[1] is not incoming or cached[2] is not state:
        retained = state and (any(part.physics_profiles for part in state.parts) or any(
            file.path.casefold() == "character/descriptors/pbd/pbdconfig.xml" for file in state.dependencies))
        context = resolve_saved_physics_profiles(state) if retained else incoming
        if context is None:
            return {"available": False, "reason": "No exact archive physics profile context is available.",
                    "parts": [], "profiles": [], "sources": [], "groups": [], "variants": []}
        try:
            source = parse_pac(data, context.source_identity.normalized_path)
            names = tuple(part.name for part in source.submeshes)
            problem = ""
            groups = _assignment_groups(context, names)
        except (ValueError, OSError) as exc:
            names, groups, problem = (), [], str(exc)
        sources = []
        for document in context.profiles:
            symbols = dict.fromkeys(binding.profile_name for binding in context.bindings if binding.profile_path == document.path)
            for symbol in symbols:
                sources.append({**_profile_preview(document), "name": symbol})
        metadata = {
            "available": context.sidecar is not None and not problem,
            "reason": problem or context.problem,
            "source": context.source_identity.normalized_path,
            "sidecar": context.sidecar.path if context.sidecar else "",
            "sidecar_sha256": context.sidecar.sha256 if context.sidecar else "",
            "profiles": sources.copy(), "sources": sources, "groups": groups,
            "variants": list(dict.fromkeys(binding.variant_index for binding in context.bindings)),
            "cloth_geometry": _cloth_geometry(data),
        }
        bindings = context.bindings
        if state and any(part.physics_profiles for part in state.parts) and not problem:
            try:
                from cdmw.services.mesh_physics_profile_output import build_physics_profile_files
                files = build_physics_profile_files(state, source, state.companion_files)
                by_path = {file.path.casefold(): file for file in files}
                sidecar = by_path[context.sidecar.path.casefold()]
                config = by_path[context.catalogue.path.casefold()]
                catalogue = collect_pbd_config_materials(_xml_text(config.data))
                paths = {entry.name.casefold(): _profile_path(entry.filename) for entry in catalogue}
                hints = parse_pbd_sidecar_hints(_xml_text(sidecar.data), retain_empty_bindings=True)
                from cdmw.models import PbdProfileBinding
                bindings = tuple(PbdProfileBinding(hint.simulation_material_name, hint.submesh_name,
                    hint.material_name, hint.variant_index, paths.get(hint.simulation_material_name.casefold(), "")) for hint in hints)
                for file in files:
                    if file.archive_location is None and file.path.casefold().startswith("character/descriptors/pbd/material/cdmw/"):
                        document = SimpleNamespace(path=file.path, data=file.data, sha256=hashlib.sha256(file.data).hexdigest())
                        metadata["profiles"].append({**_profile_preview(document), "edited": True})
            except (ValueError, KeyError, AttributeError) as exc:
                metadata["reason"] = str(exc)
        cached = (data, incoming, state, metadata, names, context, bindings)
        authoring.physics_profile_cache = cached
    _, _, _, metadata, names, context, source_bindings = cached
    targets = {part.part_id: part.target_index for part in state.parts} if state else {}
    parts = []
    for part in replacement["parts"]:
        # A renamed/replaced part retains its original target. Unmapped parts
        # never acquire an assignment by matching their current display name.
        index = targets.get(part["id"], -1) if state else part["index"]
        name = names[index] if 0 <= index < len(names) else ""
        bindings = [{"variant": binding.variant_index, "profile": binding.profile_name,
                     "path": binding.profile_path, "material": binding.material_name,
                     "reason": binding.problem}
                    for binding in source_bindings if name and binding.submesh_name.casefold() == name.casefold()]
        parts.append({**part, "source_name": name, "bindings": bindings})
    groups = []
    saved_parts = {part.part_id: part for part in state.parts} if state else {}
    for group in metadata["groups"]:
        group_names = {name.casefold() for name in group["names"]}
        members = [part for part in parts if part["source_name"].casefold() in group_names]
        reason = group["reason"] or metadata["reason"] or replacement["reason"]
        if not reason and (context.catalogue is None or not metadata["sources"]):
            reason = "Physics profiles require their source sidecar and catalogue."
        if len(members) != len(group["names"]):
            reason = "Physics profile assignment is ambiguous or does not match the PAC."
        rules = [next((rule.to_dict() for rule in saved_parts[part["id"]].physics_profiles if rule.variant == group["variant"]), None)
                 if part["id"] in saved_parts else None for part in members]
        saved = rules[0] if rules and all(rule == rules[0] for rule in rules) else None
        if rules and any(rule != rules[0] for rule in rules):
            reason = "Select every part sharing this physics profile assignment."
        groups.append({**group, "reason": reason, "part_ids": [part["id"] for part in members],
                       "rule": saved, "available": not reason})
    return {**metadata, "parts": parts, "groups": groups}


def _assignment_groups(context, names):
    if context.sidecar is None:
        return []
    document = ProfileXml(context.sidecar.data)
    groups = {}
    source_names = tuple(name.casefold() for name in names)
    for node in document.nodes:
        name = node.attributes.get("_subMeshName")
        if not name:
            continue
        owner = document.owner(node, required=False)
        if owner is None:
            continue
        variant = document.variant(node)
        key = (variant, owner.start)
        if key not in groups:
            groups[key] = {"id": f"{context.sidecar.sha256[:16]}:{owner.start}:{variant}",
                "variant": variant, "names": [], "source_profile": owner.attributes.get("_pbdSimulationMaterialName", ""),
                "reason": "" if document.variant(owner) == variant else "Physics profile assignment is ambiguous or does not match the PAC."}
        group = groups[key]
        if name.casefold() in {item.casefold() for item in group["names"]} or source_names.count(name.casefold()) != 1:
            group["reason"] = "Physics profile assignment is ambiguous or does not match the PAC."
        group["names"].append(name)
    for group in groups.values():
        try:
            document.assignment(group["variant"], group["names"])
        except ValueError as exc:
            group["reason"] = str(exc)
    return list(groups.values())


def set_physics_profile_rule(authoring, snapshot, args, *, entry, dependencies, stop_event):
    from cdmw.services.mesh_rust_replacement import replacement_ui_state
    from cdmw.services.mesh_replacement_import import archive_entry, initial_replacement_state, mesh_with_part_ids, commit_replacement
    ui = physics_profiles_ui_state(authoring, replacement_ui_state(authoring))
    group = next((row for row in ui["groups"] if row["id"] == args.get("group_id")), None)
    if group is None or not group["available"]:
        raise ValueError("Physics profile assignment is ambiguous or does not match the PAC.")
    reset = args.get("reset", False)
    if type(reset) is not bool:
        raise ValueError("Invalid physics profile settings.")
    rule = None if reset else PacPhysicsProfileRule.from_dict(args.get("rule"))
    if rule is not None and (rule.variant != group["variant"] or not any(
            row["name"] == rule.source_profile and row["path"] == rule.source_path and row["sha256"] == rule.source_sha256
            for row in ui["sources"])):
        raise ValueError("Physics profile edit source is missing or has changed.")
    state = snapshot.replacement_state or initial_replacement_state(snapshot, entry, dependencies)
    context = authoring.physics_profile_cache[5]
    target = archive_entry(ReplacementFile(state.target_path, b"", state.target_location))
    if target is None or target.identity != context.source_identity:
        raise ValueError("Physics profile edit source is missing or has changed.")
    parts = []
    for part in state.parts:
        if part.part_id in group["part_ids"]:
            rules = tuple(old for old in part.physics_profiles if old.variant != group["variant"])
            part = replace(part, physics_profiles=rules + ((rule,) if rule else ()))
        parts.append(part)
    parts = tuple(parts)
    if parts == state.parts:
        return authoring.shadow_service.session_view(authoring.shadow_session_id)
    files = {}
    for file in state.dependencies:
        key = file.path.casefold()
        if key in files and files[key] != file:
            raise ValueError("Physics profile edit source is missing or has changed.")
        files[key] = file
    for document in (context.sidecar, context.catalogue, *context.profiles):
        if document is None:
            continue
        if document.archive_location is None or hashlib.sha256(document.data).hexdigest() != document.sha256:
            raise ValueError("Physics profile edit source is missing or has changed.")
        file = ReplacementFile(document.path, document.data, document.archive_location)
        if archive_entry(file).identity != document.identity:
            raise ValueError("Physics profile edit source is missing or has changed.")
        key = file.path.casefold()
        if key in files and files[key] != file:
            raise ValueError("Physics profile edit source is missing or has changed.")
        files[key] = file
    state = replace(state, parts=parts, dependencies=tuple(files.values()), revision=state.revision + 1)
    return commit_replacement(authoring.shadow_service, snapshot, mesh_with_part_ids(snapshot, state), state,
        label="Restore physics profile" if reset else "Edit physics profile", stop_event=stop_event)
