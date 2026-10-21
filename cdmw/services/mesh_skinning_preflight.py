"""Shared authored-skin preflight. Preparation owns copies; no donor fallback."""

import copy
import hashlib
from dataclasses import replace
from types import SimpleNamespace

from cdmw.domain.mesh.skin_policy import SkinningChoice, SkinningPartReport, reduce_influences
from cdmw.modding.mesh_parser import parse_pac, _decode_pac_skin_influences, resolve_pac_bone_palette
from cdmw.modding.mesh_skinning import pack_pac_skin_weights
from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.services.mesh_replacement_skinning import retain_imported_skinning, _target_bind_frame


def has_authored_skin(mesh):
    return any(part.interchange_skin or part.bone_indices or part.bone_weights for part in mesh.submeshes)


def preflight_imported_skin(mesh, target_data, skeleton, target_path, *, choices=(), stop_event=None,
                            palette_extension_bones=(), body_donor=None, body_path="", body_report=None,
                            transfer_transform=None):
    """Map preserved parts through the existing rig proof; transfer is deliberate."""
    source = copy.deepcopy(mesh)
    captured_hash = hashlib.sha256(target_data).hexdigest()
    if palette_extension_bones:
        from cdmw.modding.pac_palette_extension import extend_pac_palette
        target_data, source.interchange_palette_extension = extend_pac_palette(target_data, skeleton, palette_extension_bones)
        source.interchange_skeleton = skeleton
    target = parse_pac(target_data, target_path)
    target.interchange_skeleton = skeleton
    snapshot = SimpleNamespace(mesh=target, original_data=target_data)
    state = SimpleNamespace(neutral_coordinates=False)
    decisions = {choice.part_index: choice for choice in choices}
    if len(decisions) != len(choices) or any(not 0 <= index < len(source.submeshes) for index in decisions):
        raise ValueError("Skinning choices must identify each imported part uniquely.")
    palette = resolve_pac_bone_palette(target_data, skeleton)
    reports = []
    missing_parts = {}
    for index, part in enumerate(source.submeshes):
        from cdmw.domain.cancellation import raise_if_cancelled
        raise_if_cancelled(stop_event)
        authored = bool(part.interchange_skin or part.bone_indices or part.bone_weights)
        choice = decisions.get(index, SkinningChoice(index, "preserve" if authored else "transfer"))
        transfer = choice.policy in {"transfer", "body_transfer"}
        if not transfer and not authored:
            raise ValueError(f"{part.name} has no imported weights to preserve; choose template transfer.")
        report = SkinningPartReport(index, part.name, choice.policy, target_path,
                                    donor_part_names=tuple(p.name for p in target.submeshes),
                                    target_sha256=captured_hash, skeleton_path=skeleton.path)
        if authored:
            skin = part.interchange_skin
            if not skin:
                raise ValueError(f"{part.name} has weights without their imported rig identity.")
            identities = tuple(str(skin["nodes"][joint].get("name", "")) for joint in skin["joints"])
            if len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices):
                raise ValueError(f"{part.name} has incomplete imported weight rows.")
            if any(type(joint) is not int or not 0 <= joint < len(identities)
                   for row in part.bone_indices for joint in row):
                raise ValueError(f"{part.name} has an invalid imported joint.")
            required = tuple(sorted({identities[joint] for row in part.bone_indices for joint in row}))
            report = replace(report, required_bones=required)
            if choice.policy == "reduce":
                rows = [reduce_influences(a, b, choice.capacity, identities)
                        for a, b in zip(part.bone_indices, part.bone_weights, strict=True)]
                part.bone_indices = [row[0] for row in rows]
                part.bone_weights = [row[1] for row in rows]
                report = replace(report, reduced_vertices=sum(row[2] > 0 for row in rows),
                                 maximum_removed_mass=max((row[2] for row in rows), default=0.),
                                 over_one_percent=sum(row[2] > .01 for row in rows),
                                 over_five_percent=sum(row[2] > .05 for row in rows),
                                 removed_bones=tuple(sorted({name for row in rows for name in row[3]})),
                                 maximum_normalization_change=max((row[4] for row in rows), default=0.))
                report = replace(report, required_bones=tuple(sorted({identities[joint]
                    for row in part.bone_indices for joint in row})))
            if transfer:
                from cdmw.modding.mesh_glb_assets import skeleton_skin
                from cdmw.modding.scene_geometry_utils import _copy_submesh_with_transform
                part = _copy_submesh_with_transform(part, _target_bind_frame(skin, skeleton_skin(skeleton)))
            else:
                names = {skeleton.bones[bone].name for bone in palette}
                missing = sorted(set(report.required_bones) - names)
                if missing:
                    missing_parts[part.name] = missing
                    continue
                single = replace(source, submeshes=[part])
                part = retain_imported_skinning(single, snapshot, state).submeshes[0]
                quantization = 0.
                for joints, weights in zip(part.bone_indices, part.bone_weights, strict=True):
                    record = bytearray(40)
                    record[39] = 63
                    pack_pac_skin_weights(record, joints, weights, context=part.name)
                    slots, values = _decode_pac_skin_influences(record, 0)
                    encoded = dict(zip(slots, values))
                    quantization = max(quantization, *(abs(encoded[joint] - weight) for joint, weight in zip(joints, weights)))
                report = replace(report, maximum_quantization_change=quantization)
        if transfer:
            part = copy.copy(part)
            part.bone_indices, part.bone_weights, part.interchange_skin = [], [], {}
            part.source_vertex_map, part.source_vertex_map_authority = [], "topology"
            if authored or has_authored_skin(mesh) or index in decisions or choice.donor_parts or choice.policy == "body_transfer":
                # Transfer on the selected surface before any material merge.
                from cdmw.modding.mesh_skinning import ensure_final_target_skin_weights
                from cdmw.modding.static_mesh_runtime_builder import _template_skin_surface, _merge_source_submeshes
                if len(set(choice.donor_parts)) != len(choice.donor_parts) or any(
                        not 0 <= donor < len(target.submeshes) for donor in choice.donor_parts):
                    raise ValueError("The selected template donor parts are invalid.")
                donor = target.submeshes[choice.donor_parts[0] if choice.donor_parts else 0]
                if choice.policy == "body_transfer":
                    if body_donor is None or not body_path:
                        raise ValueError("Choose a verified character body resolved through this target's snapshot.")
                    if choice.donor_parts:
                        raise ValueError("Template part restrictions cannot select a body region.")
                    donor = body_donor
                    metrics = body_report or {}
                    report = replace(report, donor_path=body_path, transfer_details=(
                        f"Donor filtering: {metrics.get('partially_filtered_vertices',0)} partially supported vertices, "
                        f"{metrics.get('unsupported_vertices',0)} unsupported vertices, "
                        f"{metrics.get('excluded_faces',0)} excluded faces; partial loss up to "
                        f"{metrics.get('maximum_partial_removed_mass',0):.2%}, normalization change "
                        f"{metrics.get('maximum_renormalization_change',0):.2%}.",))
                elif choice.donor_parts:
                    surface = _merge_source_submeshes([target.submeshes[i] for i in choice.donor_parts], donor)
                    donor = replace(donor, vertices=surface.vertices, faces=surface.faces,
                                    bone_indices=surface.bone_indices, bone_weights=surface.bone_weights)
                else:
                    donor = _template_skin_surface(target, donor)
                details = []
                weighted = part
                if transfer_transform is not None:
                    from cdmw.modding.scene_geometry_utils import _copy_submesh_with_transform
                    weighted = _copy_submesh_with_transform(part, transfer_transform)
                ensure_final_target_skin_weights(weighted, donor, target_index=index, summary=details)
                part.bone_indices, part.bone_weights = weighted.bone_indices, weighted.bone_weights
                report = replace(report, transfer_details=report.transfer_details + tuple(details))
        source.submeshes[index] = part
        reports.append(report)
    if missing_parts:
        names = sorted({name for missing in missing_parts.values() for name in missing})
        raise ValueError(f"Missing equipment palette bones: {', '.join(names)}. "
                         "Keep imported weights cannot substitute bones. Palette extension requires separate validation. "
                         + "; ".join(f"{part}: {', '.join(missing)}" for part, missing in missing_parts.items()))
    refresh_mesh_totals(source)
    source.has_bones = any(part.bone_weights for part in source.submeshes)
    return source, tuple(reports)


def prepare_new_item_skin(mesh, snapshot, target_path, *, choices=(), stop_event=None, palette_extension_bones=(),
                          transfer_transform=None):
    """Resolve the exact captured template/PAB through snapshot provenance."""
    from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
    from cdmw.domain.cancellation import raise_if_cancelled
    from cdmw.modding.skeleton_parser import parse_pab

    raise_if_cancelled(stop_event)
    by_path, by_basename = snapshot.archive_index_maps()
    original = snapshot.payload(target_path)
    entry, _report = resolve_skeleton_for_model(
        snapshot.entry(target_path), archive_entries_by_normalized_path=by_path,
        archive_entries_by_basename=by_basename, pac_data=original,
        read_entry_data=lambda item: snapshot.payload(item.path),
    )
    if entry is None:
        raise ValueError("Keep imported weights needs the selected template's unique matching skeleton.")
    skeleton_data = snapshot.payload(entry.path)
    skeleton = parse_pab(skeleton_data, entry.path)
    if skeleton.parser_mode != "fixed" or skeleton.parse_warning:
        raise ValueError("Keep imported weights needs a complete fixed-layout target skeleton.")
    body = {}
    if any(choice.policy == "body_transfer" for choice in choices):
        from cdmw.services.new_item_skinning import verified_body_surface
        donor_target = original
        if palette_extension_bones:
            from cdmw.modding.pac_palette_extension import extend_pac_palette
            donor_target, _contract = extend_pac_palette(original, skeleton, palette_extension_bones)
        donor, path, report = verified_body_surface(snapshot, skeleton, resolve_pac_bone_palette(donor_target, skeleton))
        body = dict(body_donor=donor, body_path=path, body_report=report)
    mapped, reports = preflight_imported_skin(mesh, original, skeleton, target_path, choices=choices,
        stop_event=stop_event, palette_extension_bones=palette_extension_bones, transfer_transform=transfer_transform, **body)
    result = mapped, tuple(replace(report, skeleton_sha256=hashlib.sha256(skeleton_data).hexdigest()) for report in reports)
    raise_if_cancelled(stop_event)
    return result
