"""Resolve authored glTF influences against a retained PAC rig, without retargeting."""

from __future__ import annotations

import math

from cdmw.modding.mesh_glb_assets import skeleton_skin, transpose
from cdmw.modding.mesh_parser import PAC_SKIN_MAX_BONE_INDEX, PAC_SKIN_PALETTE_SLOTS, resolve_pac_bone_palette
from cdmw.modding.mesh_skinning import SOURCE_VERTEX_MAP_TOPOLOGY
from cdmw.modding.mesh_totals import refresh_mesh_totals
from cdmw.modding.scene_geometry_utils import (
    _copy_submesh_with_transform, _identity_matrix, _invert_affine_matrix, _multiply_matrix,
)


def _bind_matrix(values):
    if len(values) != 16:
        raise ValueError("Imported skin has an incomplete inverse bind matrix.")
    matrix = transpose(values)
    if (len(matrix) != 16 or not all(math.isfinite(v) for v in matrix)
            or any(abs(matrix[12 + i] - (1.0 if i == 3 else 0.0)) > 1e-6 for i in range(4))
            or _invert_affine_matrix(matrix) is None):
        raise ValueError("Imported skin has an invalid or singular inverse bind matrix.")
    return matrix


def retain_imported_skinning(source, snapshot, state):
    """Map used joints by exact name and one common bind-space transform.

    PAC vertex influences address palette slots, never skeleton indices. The
    captured target bytes are authoritative for that palette. No bone-name
    guessing, palette extension, posed-geometry bake or donor-weight fallback
    is allowed for an authored skin.
    """
    skinned = {id(part) for part in source.submeshes if part.interchange_skin or part.bone_indices or part.bone_weights}
    if not skinned:
        return source
    if str(source.format).casefold() not in {"gltf", "glb"}:
        raise ValueError("Skinned replacement requires a GLB/glTF exported from the matching game armature; use editable-package import for round-trip packages.")
    if str(snapshot.mesh.format).casefold() != "pac":
        raise ValueError("Imported skin weights require a PAC target with a resolved bone palette.")
    skeleton = getattr(snapshot.mesh, "interchange_skeleton", None)
    bones = tuple(getattr(skeleton, "bones", ()) or ())
    palette = tuple(resolve_pac_bone_palette(snapshot.original_data, skeleton))
    if not bones or not palette:
        raise ValueError("Imported skin weights need the target's matching skeleton and resolved PAC bone palette. Open the target with its skeleton before importing.")
    if len(palette) > PAC_SKIN_MAX_BONE_INDEX + 1 or len(set(palette)) != len(palette):
        raise ValueError("Target PAC bone palette is ambiguous or exceeds the supported influence slots.")
    target_skin = skeleton_skin(skeleton)
    slots_by_name = {}
    for slot, bone_index in enumerate(palette):
        slots_by_name.setdefault(str(bones[bone_index].name), []).append((slot, bone_index))
    for index, part in enumerate(source.submeshes):
        if id(part) not in skinned:
            continue
        skin = part.interchange_skin
        if not skin or len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices):
            raise ValueError(f"Imported skin requires complete joint weights in {part.name}.")
        nodes, joints = skin["nodes"], skin["joints"]
        inverses = skin.get("inverse_bind_matrices", ())
        used = {joint for row in part.bone_indices for joint in row}
        remap, frames, used_names = {}, [], set()
        for joint in sorted(used):
            if not 0 <= joint < len(joints):
                raise ValueError(f"Imported skin references an invalid joint in {part.name}.")
            name = str(nodes[joints[joint]].get("name", ""))
            matches = slots_by_name.get(name, ())
            if not name or name in used_names or len(matches) != 1:
                raise ValueError(f"Imported joint {name or '<unnamed>'} has no unique match in the target PAC bone palette. Use the matching game armature and target item.")
            used_names.add(name)
            slot, bone_index = matches[0]
            remap[joint] = slot
            incoming_inverse = _bind_matrix(inverses[joint]) if inverses else _identity_matrix()
            target_inverse = _bind_matrix(target_skin["inverse_bind_matrices"][bone_index])
            frames.append(_multiply_matrix(_invert_affine_matrix(target_inverse), incoming_inverse))
        if not frames:
            raise ValueError(f"Imported skin has no non-zero influences in {part.name}.")
        frame = frames[0]
        if any(abs(a - b) > 2e-5 * max(1.0, abs(a), abs(b)) for other in frames[1:] for a, b in zip(frame, other)):
            raise ValueError(f"Imported joint bind frames disagree in {part.name}. Export using the matching game armature in its rest pose; rig retargeting is unavailable.")
        indices, weights = [], []
        for joints_row, weights_row in zip(part.bone_indices, part.bone_weights):
            if len(joints_row) != len(weights_row):
                raise ValueError(f"Imported skin has incomplete influence rows in {part.name}.")
            merged = {}
            for joint, weight in zip(joints_row, weights_row):
                if not math.isfinite(weight) or weight <= 0:
                    raise ValueError(f"Imported skin has invalid weights in {part.name}.")
                slot = remap[joint]
                merged[slot] = merged.get(slot, 0.0) + weight
            if not merged or len(merged) > PAC_SKIN_PALETTE_SLOTS or abs(sum(merged.values()) - 1.0) > 1e-3:
                raise ValueError(f"Imported skin requires normalized non-zero weights with at most six influences per vertex in {part.name}.")
            indices.append(tuple(merged))
            weights.append(tuple(merged.values()))
        mapped = _copy_submesh_with_transform(part, frame)
        mapped.bone_indices, mapped.bone_weights = indices, weights
        mapped.source_vertex_map_authority = SOURCE_VERTEX_MAP_TOPOLOGY
        # Indices now address the game PAC palette, not the glTF joint array.
        mapped.interchange_skin = {}
        source.submeshes[index] = mapped
    refresh_mesh_totals(source)
    if state.neutral_coordinates:
        if state.neutral_appearance is None or tuple(state.neutral_appearance.bone_palette) != palette:
            raise ValueError("The displayed target rig does not match its resolved PAC palette.")
        return state.neutral_appearance.to_neutral(source)
    return source
