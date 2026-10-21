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
    inverse = _invert_affine_matrix(matrix)
    if (len(matrix) != 16 or not all(math.isfinite(v) for v in matrix)
            or any(abs(matrix[12 + i] - (1.0 if i == 3 else 0.0)) > 1e-6 for i in range(4))
            or inverse is None or not all(math.isfinite(v) for v in inverse)):
        raise ValueError("Imported skin has an invalid or singular inverse bind matrix.")
    return matrix


def _parents(nodes):
    parents = {}
    for index, node in enumerate(nodes):
        for child in node.get("children", ()):
            if not isinstance(child, int) or not 0 <= child < len(nodes) or child in parents:
                raise ValueError("Imported rig has invalid or ambiguous joint parents.")
            parents[child] = index
    return parents


def _nearest_joint_parent(index, parents, names):
    seen = {index}
    while index in parents:
        index = parents[index]
        if index in seen:
            raise ValueError("Imported rig hierarchy contains a cycle.")
        seen.add(index)
        if index in names:
            return names[index]
    return None


def _target_bind_frame(skin, target_skin):
    """Prove the model frame using all known incoming joints, not just used ones.

    Blender can change each bone's local basis while keeping the same named
    hierarchy and bind-joint centers. Imported animation is discarded, so a
    proper similarity fitted to those centers is sufficient for game-space
    geometry. It is not permission to retarget a different rest skeleton.
    """
    target_by_name = {}
    for index, node in enumerate(target_skin["nodes"]):
        target_by_name.setdefault(str(node.get("name", "")), []).append(index)
    source_names, target_names, matches = {}, {}, []
    inverses = skin.get("inverse_bind_matrices", ())
    for slot, node_index in enumerate(skin["joints"]):
        name = str(skin["nodes"][node_index].get("name", ""))
        targets = target_by_name.get(name, ())
        if not targets:
            continue  # An unused foreign joint does not define the game rig.
        if not name or len(targets) != 1 or name in source_names.values():
            raise ValueError("Imported rig has ambiguous matching joint names.")
        target = targets[0]
        source_names[node_index], target_names[target] = name, name
        source_inverse = _bind_matrix(inverses[slot]) if inverses else _identity_matrix()
        target_inverse = _bind_matrix(target_skin["inverse_bind_matrices"][target])
        matches.append((_invert_affine_matrix(source_inverse), _invert_affine_matrix(target_inverse), source_inverse))
    source_parents, target_parents = _parents(skin["nodes"]), _parents(target_skin["nodes"])
    source_parent_names = {name: _nearest_joint_parent(index, source_parents, source_names)
                           for index, name in source_names.items()}
    target_parent_names = {name: _nearest_joint_parent(index, target_parents, target_names)
                           for index, name in target_names.items()}
    if source_parent_names != target_parent_names:
        raise ValueError("Imported joint hierarchy differs from the matching game skeleton.")
    frames = [_multiply_matrix(target, source_inverse) for _source, target, source_inverse in matches]
    if not frames:
        raise ValueError("Imported rig has no matching bind joints.")
    if all(abs(a - b) <= 2e-5 * max(1.0, abs(a), abs(b)) for other in frames[1:] for a, b in zip(frames[0], other)):
        return frames[0]

    import numpy as np

    source = np.asarray([(matrix[3], matrix[7], matrix[11]) for matrix, _target, _inverse in matches])
    target = np.asarray([(matrix[3], matrix[7], matrix[11]) for _source, matrix, _inverse in matches])
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("Imported rig has non-finite rest-joint centers.")
    centered_source, centered_target = source - source.mean(axis=0), target - target.mean(axis=0)
    # Two axes must be measurable. Collinear/coincident joints leave a model
    # rotation unresolved even when the weighted part uses only one bone.
    for points in (centered_source, centered_target):
        singular = np.linalg.svd(points, compute_uv=False)
        if len(singular) < 2 or singular[0] <= 1e-8 or singular[1] <= singular[0] * 1e-5:
            raise ValueError("Rest-joint centers are degenerate; a common model transform cannot be proven.")
    left, _singular, right = np.linalg.svd(centered_source.T @ centered_target)
    rotation = right.T @ left.T
    if np.linalg.det(rotation) < 0:
        right[-1] *= -1
        rotation = right.T @ left.T
    scale = float(np.sum((centered_source @ rotation.T) * centered_target) / np.sum(centered_source * centered_source))
    translation = target.mean(axis=0) - scale * (rotation @ source.mean(axis=0))
    extent = float(np.max(np.linalg.norm(centered_target, axis=1)))
    error = np.linalg.norm(scale * (source @ rotation.T) + translation - target, axis=1)
    if not math.isfinite(scale) or scale <= 0 or not np.isfinite(error).all() or float(error.max()) > max(1e-7, extent * 2e-5):
        raise ValueError("Rest-joint positions do not match one rigid or uniform-scale game-rig transform.")
    return tuple(float(scale * rotation[row, column]) if column < 3 else float(translation[row])
                 for row in range(3) for column in range(4)) + (0., 0., 0., 1.)


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
        used = {joint for row in part.bone_indices for joint in row}
        remap, used_names = {}, set()
        for joint in sorted(used):
            if not 0 <= joint < len(joints):
                raise ValueError(f"Imported skin references an invalid joint in {part.name}.")
            name = str(nodes[joints[joint]].get("name", ""))
            matches = slots_by_name.get(name, ())
            if not name or name in used_names or len(matches) != 1:
                raise ValueError(f"Imported joint {name or '<unnamed>'} has no unique match in the target PAC bone palette. Use the matching game armature and target item.")
            used_names.add(name)
            slot, _bone_index = matches[0]
            remap[joint] = slot
        if not remap:
            raise ValueError(f"Imported skin has no non-zero influences in {part.name}.")
        try:
            frame = _target_bind_frame(skin, target_skin)
        except ValueError as exc:
            raise ValueError(f"Imported joint bind frames disagree in {part.name}: {exc} Rig retargeting is unavailable.") from exc
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
