"""Owned guide snapshot for a controlled native cloth preview, never PAC edits."""

from __future__ import annotations

import math
import struct

from ._pbd_numeric import round_pbd_half
from .pac_cloth_guides import (
    decode_pac_cloth_guides, inspect_guide_constraint_geometry,
    inspect_guide_particle_initialization,
)
from .pac_jiggle_skinning import prepare_jiggle_bone_skinning
from .pac_cloth_preparation import prepare_guide_cloth_attachments


def _spline_chains(guides):
    """Admit complete, disjoint authored chains with a fixed first particle.

    This is a controlled preview prerequisite, not recovered game admission.
    A cloth's arbitrary groups must never be guessed into a spline topology.
    """
    chains = [list(group) for group in guides.groups_a if group]
    pairs = {frozenset((a, b)) for a, b, c, d, tag in guides.constraint_records
             if c == d == 0 and tag & 255 == 0}
    seen = set()
    for chain in chains:
        if (len(chain) < 2 or any(index >= len(guides.vertices) for index in chain)
                or len(set(chain)) != len(chain) or seen.intersection(chain)
                or guides.channel_b[chain[0]] != 255):
            return []
        seen.update(chain)
        if any(math.dist(guides.vertices[a], guides.vertices[b]) <= 1e-8
               or frozenset((a, b)) not in pairs for a, b in zip(chain, chain[1:])):
            return []
    return chains if len(seen) == len(guides.vertices) else []


def rigid_attachment_preview_rig(data: bytes, current_parts=(), *, spline_profile=False) -> dict:
    """Explicit model-root motion for proven single-slot rigid spline sources.

    Every stored render LOD and guide must use the same weighted palette slot.
    Identity here is the user-controlled model frame, never a substitute PAB.
    Unweighted source lanes still need a bounded palette for native decoding.
    """
    from .pac_cloth import pac_cloth_lods

    guides = decode_pac_cloth_guides(data)
    if guides is None or not _spline_chains(guides):
        raise ValueError("Standalone spline preview needs complete ordered guides with fixed roots.")
    if not guides.metadata_flags & 0x8000 and not spline_profile:
        raise ValueError("Standalone preview requires a spline source or an explicit spline profile.")
    weighted_slots, maximum_slot = set(), 0

    def inspect(slots, weights):
        nonlocal maximum_slot
        if sum(weights) != 255:
            raise ValueError("Standalone spline preview needs complete rigid skeletal weights.")
        maximum_slot = max(maximum_slot, *slots)
        weighted_slots.update(slot for slot, weight in zip(slots, weights) if weight)

    for slots, weights in zip(guides.bone_indices, guides.bone_weight_bytes, strict=True):
        inspect(slots, weights)
    for level in pac_cloth_lods(data):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                count = 6 if data[offset + 39] & 63 == 63 else 4
                groups = struct.unpack_from("<2I", data, offset + 20)
                slots = [(groups[i // 3] >> (10 * (i % 3))) & 1023 for i in range(count)]
                inspect(slots, data[offset + 28:offset + 28 + count])
    if len(weighted_slots) != 1:
        raise ValueError("Standalone spline preview requires one rigid skeletal attachment across every LOD.")
    slot = next(iter(weighted_slots))
    for part in current_parts:
        for slots, weights in zip(part.bone_indices, part.bone_weights, strict=True):
            if (len(slots) != len(weights) or not slots or not any(weights)
                    or any(not math.isfinite(weight) or weight < 0 for weight in weights)
                    or any(type(index) is not int or not 0 <= index <= maximum_slot
                           or (weight > 0 and index != slot) for index, weight in zip(slots, weights))):
                raise ValueError("Standalone spline preview cannot use edited skeletal attachments.")
    identity = [[float(i == j) for j in range(4)] for i in range(4)]
    return {"bone_palette": [0] * (maximum_slot + 1), "parents": [-1],
            "inverse_bind_matrices": [identity], "neutral_global_matrices": [identity],
            "neutral_local_matrices": [identity]}


def select_cloth_body_volumes(data: bytes, skeleton, *, body=None, head=None):
    """Use explicit preview inputs over decoded model volumes or rig defaults.

    The mapped producer (0x142D3F550/0x142D3EE80) looks raw model keys up in
    the skeleton's hash table via 0x140466840. Mark this materialized set as
    hash-keyed; never apply the PAB loader's index conversion to PAC records.
    Explicit body inputs replace the primary set; head inputs merge into it.
    Standalone inputs must have hash keys: there is no matching
    source-rig provenance for converting their legacy indices here.
    """
    from .pabv_parser import (
        PabvVolumes, decode_pab_embedded_volumes, decode_pac_embedded_volumes,
        merge_pabv_body_head_volumes,
    )

    model = decode_pac_embedded_volumes(data)
    for value in (body, head):
        if value is not None and not value.uses_bone_hashes:
            raise ValueError("Collision preview inputs need bone hashes; legacy indices need a matching source rig.")
    primary = body if body is not None else (PabvVolumes(3, model.volumes) if model.volumes
                                            else decode_pab_embedded_volumes(skeleton).primary)
    if body is not None or head is not None:
        return merge_pabv_body_head_volumes(primary, head).volumes, "appearance"
    return primary, "pac_model" if model.volumes else "pab_primary"


def build_cloth_body_collider_snapshot(skeleton, rig: dict, *, volumes=None) -> list[dict]:
    """Place selected primary primitives in the preview's neutral pose.

    Uses the mapped collider producer with an explicit active preview group,
    unit scene radius multiplier and the initial bone-flag profile. Live game
    activation is not selected. Spheres retain their
    authored center/radial scale without the animated kernel's zero-axis query.
    Existing callers without a supplied volume set retain PAB rig defaults.
    """
    from .pabv_parser import (
        decode_pab_embedded_volumes, default_pabv_cloth_flag_bone_sets,
        prepare_pabv_cloth_colliders,
    )
    from .pac_cloth_collisions import update_guide_cloth_collider_result

    if volumes is None:
        volumes = decode_pab_embedded_volumes(skeleton).primary
    if not volumes.volumes or len(volumes.volumes) > 128:
        raise ValueError("Body collision preview needs between 1 and 128 primary volumes.")
    prepared = prepare_pabv_cloth_colliders(
        volumes, skeleton, flag_bone_sets=default_pabv_cloth_flag_bone_sets())
    poses = rig["neutral_global_matrices"]
    if len(poses) != len(skeleton.bones):
        raise ValueError("Body colliders need the matching neutral rig pose.")
    identity = tuple(float(i == j) for i in range(4) for j in range(4))
    character = struct.pack('<16f', *identity) + bytes(208)
    group, scene = bytearray(56), bytearray(108)
    struct.pack_into('<I', group, 0, (1 << 16) | 1)
    struct.pack_into('<e', scene, 84, 1.)
    colliders = []
    for definition, bone, source in zip(prepared.definitions, prepared.bone_indices,
                                         prepared.source_ordinals, strict=True):
        kind = struct.unpack_from('<I', definition)[0] >> 16
        pose = poses[bone]
        if len(pose) != 4 or any(len(row) != 4 for row in pose):
            raise ValueError("Body colliders need complete neutral bone matrices.")
        if kind == 1:
            local = struct.unpack_from('<16f', definition, 12)
            center = [sum(local[12 + i] * pose[i][j] for i in range(4)) for j in range(3)]
            radial = [sum(local[8 + i] * pose[i][j] for i in range(4)) for j in range(3)]
            radius = struct.unpack_from('<f', definition, 4)[0] * math.hypot(*radial)
            a = b = center
        else:
            result = update_guide_cloth_collider_result(
                definition, bytes(56), group, scene, bytes(1216), character,
                use_bone_transform=True, animation_matrix=struct.pack('<16f', *(v for row in pose for v in row)),
                character_space_scale=(1., 1., 1.))
            radius = struct.unpack_from('<f', result, 4)[0]
            a, b = (struct.unpack_from('<3f', result, offset) for offset in (20, 44))
        if (not all(math.isfinite(v) and abs(v) <= 1e9 for v in (*a, *b))
                or not math.isfinite(radius) or not 0 < radius <= 1e6
                or (kind == 3 and math.dist(a, b) <= 1e-6)):
            raise ValueError("Body collision preview needs finite, nondegenerate primitives.")
        colliders.append({"kind": kind, "center1": list(a), "center2": list(b), "radius": radius,
                          "bone_index": bone, "source_ordinal": source})
    return colliders


def build_cloth_preview_snapshot(data: bytes, rig: dict) -> dict:
    """Retain decoded anchors/constraints in the resolved neutral rig's space.

    The host supplies a matching PAB/PAC snapshot or a verified, explicitly
    controlled rigid-attachment frame. Guide
    animation uses byte weights /255; CPU rest geometry uses normalized weights
    and its distinct full-16-bit positions. The native preview chooses its own
    clock, forces and iteration schedule; no active game material is inferred.
    """
    guides = decode_pac_cloth_guides(data)
    if guides is None or not guides.vertices:
        raise ValueError("This PAC has no decoded cloth guide mesh.")
    inverse, poses, palette = (rig[key] for key in ("inverse_bind_matrices", "neutral_global_matrices", "bone_palette"))
    if len(inverse) != len(poses) or not poses:
        raise ValueError("Cloth preview needs matching inverse-bind and neutral bone matrices.")
    matrices = [prepare_jiggle_bone_skinning(inverse_bind_matrix=a, animation_matrix=b,
                                           jiggle_matrix=None, character_space_scale=(1., 1., 1.))["skeletal_matrix"]
                for a, b in zip(inverse, poses, strict=True)]
    frames, cpu_positions = [], []
    for source, cpu, slots, weights in zip(guides.vertices, guides.cpu_unskinned_vertices,
                                         guides.bone_indices, guides.bone_weight_bytes, strict=True):
        if (any(slot >= len(palette) for slot in slots)
                or any(type(palette[slot]) is not int or not 0 <= palette[slot] < len(matrices) for slot in slots)):
            raise ValueError("Cloth guide skinning refers outside the resolved PAC bone palette.")
        total = sum(weights)
        if not total:
            raise ValueError("Cloth preview cannot bind a guide with zero skeletal weight.")
        weighted = [[sum(matrices[palette[slot]][i][j]*weight for slot, weight in zip(slots, weights))
                     for j in range(3)] for i in range(4)]
        shader_position = [sum((*source, 1.)[i]*weighted[i][j] for i in range(4))/255. for j in range(3)]
        cpu_positions.append([sum((*cpu, 1.)[i]*weighted[i][j] for i in range(4))/total for j in range(3)])
        frames.append([[value/255. for value in row] + [1. if i == 0 else 0.]
                       for i, row in enumerate(weighted[:3])] + [shader_position + [1.]])
    if any(not math.isfinite(x) for frame in frames for row in frame for x in row):
        raise ValueError("Cloth guide skinning produced a non-finite frame.")
    geometry = inspect_guide_constraint_geometry(guides, particle_positions=cpu_positions)
    constraints = []
    for row in geometry["constraints"]:
        kind = row["kind"]
        field = {"pair": "rest_length", "hinge": "rest_angle_radians", "triangle": "rest_area"}.get(kind)
        if field is None:
            raise ValueError("This PAC contains an undecoded cloth constraint record.")
        constraints.append({"kind": kind, "indices": list(row["vertices"]), "rest": round_pbd_half(row[field])})
    initial = inspect_guide_particle_initialization(guides)
    # Explicit preview preparation: component-local anchors, authored alpha and
    # no automatic weighting. This does not identify the active game material.
    prepared = prepare_guide_cloth_attachments(
        guides, separate_components=True, use_vertex_alpha_position_blending=True,
        auto_weighting_enabled=False, particle_positions=cpu_positions)
    chains = _spline_chains(guides)
    posed_edges = {frozenset(row["indices"]) for row in constraints if row["kind"] == "pair" and row["rest"] > 0}
    if any(frozenset((a, b)) not in posed_edges for chain in chains for a, b in zip(chain, chain[1:])):
        chains = []  # Unsupported spline preparation must not reject ordinary cloth.
    return {
        "version": 1, "source_positions": [list(v) for v in guides.vertices],
        "animation_frames": frames, "fixed": [b == 255 for b in guides.channel_b],
        "alpha_blends": initial["position_blend_with_vertex_alpha"],
        "orientation_neighbors": prepared["orientation_neighbor_indices"],
        "constraints": constraints,
        "spline_chains": chains,
    }
