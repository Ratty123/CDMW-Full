"""Imported New Item skinning and isolation from template motion."""
from dataclasses import replace
from pathlib import PurePosixPath
import math

from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.modding.mesh_parser import SubMesh, parse_pac, resolve_pac_bone_palette
from cdmw.modding.mesh_skinning import (
    PAC_SKIN_WEIGHT_LAYOUT, SOURCE_VERTEX_MAP_TOPOLOGY, ensure_final_target_skin_weights,
)
from cdmw.modding.skeleton_parser import parse_pab


def validate_imported_skin_physics(parts):
    """Require four skeletal lanes when retaining template simulation bindings."""
    if any(len(row) > 4 for part in parts for row in part.bone_indices):
        raise ValueError("Turn off Template cloth / physics for five or six skeletal influences, or explicitly reduce to four and review loss.")


def strip_template_vertex_physics(data):
    """Keep skeletal attachment weights, but remove donor cloth/jiggle at every LOD.

    The shared replacement writer deliberately retains donor simulation lanes.
    A new imported item with template physics off must not publish those lanes,
    even when it does not copy the separate HKX companion.
    """
    from cdmw.domain.mesh.cloth import PacClothRule
    from cdmw.domain.mesh.jiggle import PacJiggleRule
    from cdmw.modding.pac_cloth import apply_pac_cloth_rules, pac_cloth_lods
    from cdmw.modding.pac_jiggle import apply_pac_jiggle_rules

    levels = pac_cloth_lods(data)
    cloth_parts = {index for level in levels for index, part in enumerate(level.submeshes)
                   if any(data[offset + 39] & 63 != 63 for offset in part.source_vertex_offsets)}
    data = apply_pac_cloth_rules(data, {index: PacClothRule(amount=0) for index in cloth_parts})
    return apply_pac_jiggle_rules(data, {index: PacJiggleRule() for index in range(len(levels[0].submeshes))})


def strip_template_material_physics(data):
    """Clear inherited simulation assignments without changing authored materials."""
    from cdmw.modding.pbd_profile_edit import ProfileXml

    document = ProfileXml(data)
    defaults = {"_pbdSimulationMaterialName": "", "_physicsFileName": "", "_jiggleWindWeight": "0"}
    edits = [document.attribute_edit(node, name, value) for node in document.nodes
             for name, value in defaults.items() if name in node.attributes and node.attributes[name] != value]
    return document.apply(edits) if edits else data


def hide_variant_geometry(snapshot, target_path, *, stop_event=None):
    """Hide one exact family slot using the retained all-LOD placeholder writer."""
    from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementPart, PART_ID_ATTRIBUTE
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.services.new_item_variants import xml_path
    import hashlib

    raise_if_cancelled(stop_event)
    original = snapshot.payload(target_path)
    mesh = parse_pac(original, target_path)
    digest = hashlib.sha256(original).hexdigest()
    parts = tuple(ReplacementPart(f"{digest[:16]}:{index}", index, included=False)
                  for index in range(len(mesh.submeshes)))
    for part, binding in zip(mesh.submeshes, parts, strict=True):
        setattr(part, PART_ID_ATTRIBUTE, binding.part_id)
    # The output preparer expects a frozen dataclass capture for local replaces.
    from cdmw.services.mesh_service import MeshService
    service = MeshService()
    mesh._cdmw_original_data = original
    sid = service.open_edit_session(mesh).session_id
    try:
        captured = service.capture_export_snapshot(sid)
        # Capture clones omit UI-independent part attributes on an initial session.
        for part, binding in zip(captured.mesh.submeshes, parts, strict=True):
            setattr(part, PART_ID_ATTRIBUTE, binding.part_id)
        captured = replace(captured, replacement_state=MeshReplacementState(target_path, digest, parts))
        payload = prepare_replacement_output(captured).data
    finally:
        service.close_edit_session(sid)
    raise_if_cancelled(stop_event)
    sidecar = xml_path(target_path)
    return ModelFiles(payload, side_files={sidecar: snapshot.payload(sidecar)} if snapshot.has_entry(sidecar) else {},
                      material_route="template", notes=(f"Hidden template geometry: {target_path}; every stored LOD retains its slot.",))


def _body_surface(mesh, body_palette, target_palette, *, report=None):
    """Keep supported body triangles and remap their named bones into the armour."""
    failure = "A verified character body with compatible skin weights is required for this armour import."
    if not body_palette or not target_palette or len(set(target_palette)) != len(target_palette):
        raise ValueError(failure)
    metrics = {"partially_filtered_vertices": 0, "unsupported_vertices": 0,
               "maximum_removed_mass": 0.0, "maximum_partial_removed_mass": 0.0,
               "maximum_renormalization_change": 0.0, "removed_body_bones": set(), "excluded_faces": 0}
    target_slots = {bone: slot for slot, bone in enumerate(target_palette)}
    donor = SubMesh(name=PurePosixPath(mesh.path).name, source_vertex_stride=40,
                    source_skin_weight_layout=PAC_SKIN_WEIGHT_LAYOUT)
    for part in mesh.submeshes:
        if (part.source_vertex_stride != 40 or part.source_skin_weight_layout != PAC_SKIN_WEIGHT_LAYOUT
                or len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices)):
            raise ValueError(failure)
        rows = []
        for indices, weights in zip(part.bone_indices, part.bone_weights):
            if (not indices or len(indices) != len(weights)
                    or any(not math.isfinite(weight) or weight < 0 for weight in weights)
                    or sum(weights) <= 0
                    or any(weight > 0 and not 0 <= index < len(body_palette) for index, weight in zip(indices, weights))):
                raise ValueError(failure)
            kept = [(target_slots[body_palette[index]], weight) for index, weight in zip(indices, weights)
                    if weight > 0 and body_palette[index] in target_slots]
            total = sum(weight for _index, weight in kept)
            removed = sum(weight for index, weight in zip(indices, weights)
                          if weight > 0 and body_palette[index] not in target_slots) / sum(weights)
            metrics["maximum_removed_mass"] = max(metrics["maximum_removed_mass"], removed)
            metrics["partially_filtered_vertices"] += int(0 < removed < 1)
            if 0 < removed < 1:
                metrics["maximum_partial_removed_mass"] = max(metrics["maximum_partial_removed_mass"], removed)
                metrics["maximum_renormalization_change"] = max(metrics["maximum_renormalization_change"],
                    *(abs(weight / total - weight / sum(weights)) for _index, weight in kept))
            metrics["unsupported_vertices"] += int(total <= 0)
            metrics["removed_body_bones"].update(body_palette[index] for index, weight in zip(indices, weights)
                                                if weight > 0 and body_palette[index] not in target_slots)
            rows.append((tuple(index for index, _weight in kept), tuple(weight / total for _index, weight in kept))
                        if total > 0 else ((), ()))
        # A hand or face may use bones absent from this armour's palette. Do not
        # invent a replacement bone for it or include its unsupported triangles.
        faces = [face for face in part.faces if all(rows[index][0] for index in face)]
        metrics["excluded_faces"] += len(part.faces) - len(faces)
        used = sorted({index for face in faces for index in face})
        mapping = {old: len(donor.vertices) + offset for offset, old in enumerate(used)}
        donor.vertices.extend(part.vertices[index] for index in used)
        donor.bone_indices.extend(rows[index][0] for index in used)
        donor.bone_weights.extend(rows[index][1] for index in used)
        donor.faces.extend(tuple(mapping[index] for index in face) for face in faces)
    if not donor.faces:
        raise ValueError(failure)
    if report is not None:
        report.update({**metrics, "removed_body_bones": tuple(sorted(metrics["removed_body_bones"]))})
    return donor


def _rig_body_paths(snapshot, rig_folder):
    """The rig's verified body PACs, chosen from the `.pac` listing alone.

    `_body_mesh_paths` keeps only PACs. Walking every entry of the resident catalogue
    to find them decoded about two million paths: 35 s a call on 2026-10-26.
    """
    from cdmw.services.effect_character_reference import _body_mesh_paths, _snapshot_paths
    prefix = str(rig_folder).casefold() + "/nude/"
    return _body_mesh_paths((path for path in _snapshot_paths(snapshot, (".pac",)) if path.startswith(prefix)), {},
                            rig_model=rig_folder.name)


def verified_body_surface(snapshot, skeleton, target_palette):
    """The same provenance-backed body as preview, with quantified palette filtering."""
    paths = _rig_body_paths(snapshot, PurePosixPath(skeleton.path).parent)
    if not paths:
        raise ValueError("No verified character body is available for this target skeleton.")
    body_path = paths[0]
    data = snapshot.payload(body_path)
    report = {}
    donor = _body_surface(parse_pac(data, body_path), resolve_pac_bone_palette(data, skeleton), target_palette, report=report)
    return donor, body_path, report


def rebind_armour_from_body(snapshot, target_path, files, *, stop_event=None):
    """Rebuild a new unrigged import from the verified body used by character preview.

    The caller excludes authored source weights, changed palettes and retained
    template physics. All archive inputs go through the snapshot's provenance.
    Only the in-memory imported PAC changes; the character rig and body stay intact.
    """
    from cdmw.modding.mesh_importer import _build_pac_full_rebuild

    raise_if_cancelled(stop_event, "Armour weight transfer cancelled.")
    by_path, by_basename = snapshot.archive_index_maps()
    target_data = snapshot.payload(target_path)
    entry, _report = resolve_skeleton_for_model(
        snapshot.entry(target_path), archive_entries_by_normalized_path=by_path,
        archive_entries_by_basename=by_basename, pac_data=target_data,
        read_entry_data=lambda candidate: snapshot.payload(candidate.path),
    )
    failure = "A verified character body with compatible skin weights is required for this armour import."
    if entry is None:
        raise ValueError(failure)
    skeleton = parse_pab(snapshot.payload(entry.path), entry.path)
    target_palette = resolve_pac_bone_palette(target_data, skeleton)
    if skeleton.parser_mode != "fixed" or skeleton.parse_warning or not target_palette:
        raise ValueError(failure)
    paths = _rig_body_paths(snapshot, PurePosixPath(entry.path).parent)
    if not paths:
        raise ValueError(failure)
    body_path = paths[0]
    body_data = snapshot.payload(body_path)
    donor_report = {}
    donor = _body_surface(parse_pac(body_data, body_path), resolve_pac_bone_palette(body_data, skeleton), target_palette,
                          report=donor_report)
    original = parse_pac(files.pac_data, target_path)
    working = replace(original, submeshes=[])
    summary = []
    if donor_report["partially_filtered_vertices"] or donor_report["unsupported_vertices"]:
        names = ", ".join(skeleton.bones[index].name for index in donor_report["removed_body_bones"])
        summary.append(f"Warning: skin weights donor filtering renormalized {donor_report['partially_filtered_vertices']} "
                       f"partially supported vertices; excluded {donor_report['unsupported_vertices']} unsupported vertices "
                       f"and {donor_report['excluded_faces']} faces. Maximum partial-row loss "
                       f"{donor_report['maximum_partial_removed_mass']:.2%}; normalization change up to "
                       f"{donor_report['maximum_renormalization_change']:.2%}. Missing donor bones: {names}. Review deformation.")
    for index, part in enumerate(original.submeshes):
        raise_if_cancelled(stop_event, "Armour weight transfer cancelled.")
        updated = replace(part, bone_indices=[], bone_weights=[], source_vertex_map=[],
                          source_vertex_map_authority=SOURCE_VERTEX_MAP_TOPOLOGY)
        ensure_final_target_skin_weights(updated, donor, target_index=index,
                                         summary=summary if len(set(part.vertices)) > 1 else None)
        working.submeshes.append(updated)
    # This is a complete new import, not the protected same-topology edit path.
    # Its serializer owns all influence lanes and keeps the runtime draw layout.
    payload = _build_pac_full_rebuild(original, working, files.pac_data, preserve_runtime_abi=True)
    raise_if_cancelled(stop_event, "Armour weight transfer cancelled.")
    return replace(
        files, pac_data=payload,
        notes=tuple(note for note in files.notes if not note.startswith("Skin weights "))
              + (f"Armour weight donor: {body_path}",)
              + tuple(line for line in summary if not line.startswith("Warning: ")),
        warnings=tuple(warning for warning in files.warnings if not warning.startswith("skin weights "))
                 + ("Armour weights were transferred from the character body. Check fit and deformation; cloth simulation is not rebuilt.",)
                 + tuple(line.removeprefix("Warning: ") for line in summary if line.startswith("Warning: ")),
    )
