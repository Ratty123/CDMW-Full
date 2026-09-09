"""Body-surface weights for new armour whose template binding is not encodable."""
from dataclasses import replace
from pathlib import PurePosixPath

from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.modding.mesh_parser import SubMesh, parse_pac, resolve_pac_bone_palette
from cdmw.modding.mesh_skinning import (
    PAC_SKIN_WEIGHT_LAYOUT, SOURCE_VERTEX_MAP_TOPOLOGY, ensure_final_target_skin_weights,
)
from cdmw.modding.skeleton_parser import parse_pab


def _body_surface(mesh, body_palette, target_palette):
    """Keep supported body triangles and remap their named bones into the armour."""
    failure = "A verified character body with compatible skin weights is required for this armour import."
    if not body_palette or not target_palette:
        raise ValueError(failure)
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
                    or any(weight > 0 and not 0 <= index < len(body_palette) for index, weight in zip(indices, weights))):
                raise ValueError(failure)
            kept = [(target_slots[body_palette[index]], weight) for index, weight in zip(indices, weights)
                    if weight > 0 and body_palette[index] in target_slots]
            total = sum(weight for _index, weight in kept)
            rows.append((tuple(index for index, _weight in kept), tuple(weight / total for _index, weight in kept))
                        if total > 0 else ((), ()))
        # A hand or face may use bones absent from this armour's palette. Do not
        # invent a replacement bone for it or include its unsupported triangles.
        faces = [face for face in part.faces if all(rows[index][0] for index in face)]
        used = sorted({index for face in faces for index in face})
        mapping = {old: len(donor.vertices) + offset for offset, old in enumerate(used)}
        donor.vertices.extend(part.vertices[index] for index in used)
        donor.bone_indices.extend(rows[index][0] for index in used)
        donor.bone_weights.extend(rows[index][1] for index in used)
        donor.faces.extend(tuple(mapping[index] for index in face) for face in faces)
    if not donor.faces:
        raise ValueError(failure)
    return donor


def rebind_armour_from_body(snapshot, target_path, files, *, stop_event=None):
    """Rebuild a new unrigged import from the verified body used by character preview.

    The caller excludes authored source weights, changed palettes and retained
    template physics. All archive inputs go through the snapshot's provenance.
    Only the in-memory imported PAC changes; the character rig and body stay intact.
    """
    from cdmw.modding.mesh_importer import _build_pac_full_rebuild
    from cdmw.services.effect_character_reference import _body_mesh_paths

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
    rig_folder = PurePosixPath(entry.path).parent
    prefix = str(rig_folder).casefold() + "/nude/"
    paths = _body_mesh_paths((path for path in snapshot.entries if path.startswith(prefix)), {}, rig_model=rig_folder.name)
    if not paths:
        raise ValueError(failure)
    body_path = paths[0]
    body_data = snapshot.payload(body_path)
    donor = _body_surface(parse_pac(body_data, body_path), resolve_pac_bone_palette(body_data, skeleton), target_palette)
    original = parse_pac(files.pac_data, target_path)
    working = replace(original, submeshes=[])
    summary = []
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
