"""Validate a PAC's embedded attachment skeleton before deforming its geometry."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import struct

import numpy as np


class BindingError(ValueError):
    pass


@dataclass(frozen=True)
class UnusedTrack:
    name_hash: int
    name: str
    source: str
    sha256: str


@dataclass(frozen=True)
class AttachmentBinding:
    skeleton: object
    palette: tuple[int, ...]
    mesh: object
    skeleton_offset: int
    palette_offset: int
    bind_error: float
    unused_tracks: tuple[UnusedTrack, ...] = ()

    def unmatched(self, clip):
        have = {b.name_hash for b in self.skeleton.bones} | {t.name_hash for t in self.unused_tracks}
        return tuple(t.name_hash for t in clip.tracks if t.name_hash not in have)

    def unused(self, clip):
        hashes = {t.name_hash for t in clip.tracks}
        return tuple(t for t in self.unused_tracks if t.name_hash in hashes)


def optional_leaf_tracks(binding, witness, hashes, source, payload):
    """Identify unused leaves from another mesh using the same animation set.

    No witness transform or weight is applied to the target. Every target bone
    must retain the same named ancestry; an unknown ancestor can never qualify.
    Different bow proportions do not change whether an absent leaf influences
    this mesh. The caller must establish the explicit shared animation mapping.
    """
    target = {b.name_hash: b for b in binding.skeleton.bones}
    other = {b.name_hash: b for b in witness.skeleton.bones}
    def parent(skeleton, bone):
        return skeleton.bones[bone.parent_index].name_hash if bone.parent_index >= 0 else None
    if not target.keys() <= other.keys():
        return ()
    for key, bone in target.items():
        if bone.name != other[key].name or parent(binding.skeleton, bone) != parent(witness.skeleton, other[key]):
            return ()
    parents = {parent(witness.skeleton, b) for b in other.values()}
    return tuple(UnusedTrack(h, other[h].name, source, hashlib.sha256(payload).hexdigest())
                 for h in sorted(hashes) if h in other and h not in target and h not in parents
                 and parent(witness.skeleton, other[h]) in target)


def complete_scene_binding(scene, read_asset, *, cancelled=lambda: False):
    """Resolve optional tracks using active installed meshes on the preparation worker."""
    from fnmatch import fnmatchcase
    binding, path, mappings = scene.equipment
    if binding is None or scene.relationships is None or read_asset is None:
        return
    sets = {s for pattern, s in scene.relationships.matches if fnmatchcase(path, pattern)}
    if len(sets) != 1:
        return
    mapped = {target for target, _ in mappings.values()}
    for target in tuple(mapped):
        space = scene.relationships.spaces.get(target)
        if space:
            mapped.update(space.clips)
    missing = {h for p in mapped if p in scene.clips for h in binding.unmatched(scene.clips[p])}
    evidence = list(binding.unused_tracks)
    if not missing:
        return
    for candidate in sorted(scene.relationships.entries):
        if cancelled():
            raise RuntimeError('Attachment inspection cancelled')
        if candidate == path or not candidate.endswith('.pac'):
            continue
        candidate_sets = {s for pattern,s in scene.relationships.matches if fnmatchcase(candidate,pattern)}
        if candidate_sets != sets:
            continue
        try:
            data = read_asset(candidate)
            witness = decode_binding(data, candidate)
        except (OSError, ValueError, KeyError, RuntimeError):
            if cancelled():
                raise RuntimeError('Attachment inspection cancelled')
            continue  # Missing evidence cannot turn an unresolved track into a pass.
        found = optional_leaf_tracks(binding, witness, missing, candidate, data)
        evidence.extend(found)
        missing.difference_update(t.name_hash for t in found)
        if not missing:
            break
    if cancelled():
        raise RuntimeError('Attachment inspection cancelled')
    scene.equipment = (replace(binding, unused_tracks=tuple(evidence)), path, mappings)


def embedded_skeleton(data, section_start, section_end):
    """Find one complete typed hierarchy with its adjacent hash palette.

    Candidates are accepted only with a parent-first tree, valid bind/inverse
    pairs, local-to-world reconstruction, unique names/hashes, and a palette
    resolving entirely into that tree. Ambiguity is an error, never a guess.
    """
    from cdmw.modding.skeleton_parser import Skeleton, _read_fixed_pab_bone
    from tools.paa_motion.pose import bind_transform, matrix_of, matrix_multiply
    found = []
    for offset in range(section_start, section_end - 310):
        count = struct.unpack_from('<I', data, offset)[0]
        if not 1 <= count <= 512 or offset + 4 + count * 306 > section_end:
            continue
        name_size = data[offset + 8]
        if not 1 <= name_size <= 100:
            continue
        name = data[offset + 9:offset + 9 + name_size]
        if not all(32 <= b < 127 for b in name):
            continue
        bones, cursor, error = [], offset + 4, 0.
        try:
            for index in range(count):
                bone, cursor = _read_fixed_pab_bone(data, cursor, index)
                if cursor > section_end or not bone.name or not bone.name.isascii() or not all(32 <= ord(c) < 127 for c in bone.name):
                    raise BindingError('Invalid embedded bone record')
                if (index == 0 and bone.parent_index != -1) or (index and not -1 <= bone.parent_index < index):
                    raise BindingError('Invalid embedded hierarchy')
                world = matrix_of(bind_transform(bone))
                if bone.parent_index >= 0:
                    world = matrix_multiply(world, bones[bone.parent_index].bind_matrix)
                bind = np.array(bone.bind_matrix).reshape(4, 4)
                inverse = np.array(bone.inv_bind_matrix).reshape(4, 4)
                values = (*bone.bind_matrix, *bone.inv_bind_matrix, *world)
                if not np.isfinite(values).all():
                    raise BindingError('Non-finite bind data')
                error = max(error, float(np.max(np.abs(bind @ inverse - np.eye(4)))),
                            float(np.max(np.abs(np.array(world).reshape(4, 4) - bind))))
                if error > 1e-4:
                    raise BindingError('Bind reconstruction failed')
                bones.append(bone)
            by_hash = {b.name_hash: b.index for b in bones}
            if len(by_hash) != count or len({b.name for b in bones}) != count:
                raise BindingError('Duplicate bone identity')
            # One enabled byte per embedded bone precedes a u16 hash palette.
            if data[cursor:cursor + count] != bytes([1]) * count:
                raise BindingError('Unsupported embedded bone flags')
            palette_offset = cursor + count
            size = struct.unpack_from('<H', data, palette_offset)[0]
            if not 1 <= size <= count or palette_offset + 2 + size * 4 > section_end:
                raise BindingError('Invalid embedded palette count')
            hashes = struct.unpack_from('<' + 'I' * size, data, palette_offset + 2)
            if len(set(hashes)) != size or any(h not in by_hash for h in hashes):
                raise BindingError('Unresolved embedded palette')
            skeleton = Skeleton(bones=bones, bone_count=count, tail_offset=cursor, parser_mode='pac_embedded')
            found.append((skeleton, tuple(by_hash[h] for h in hashes), offset, palette_offset, error))
        except (ValueError, struct.error, IndexError, OverflowError):
            continue
    if len(found) != 1:
        raise BindingError(f'Expected one validated embedded hierarchy; found {len(found)}')
    return found[0]


def exact_skin(parsed, skeleton, palette, path=''):
    from .skinning import SkinnedMesh, deform, skin_matrices
    rest, faces, indices, weights = [], [], [], []
    for submesh in parsed.submeshes:
        base = len(rest)
        if len(submesh.bone_indices) != len(submesh.vertices) or len(submesh.bone_weights) != len(submesh.vertices):
            raise BindingError('Incomplete vertex influence arrays')
        for point, slots, shares in zip(submesh.vertices, submesh.bone_indices, submesh.bone_weights):
            if len(slots) != len(shares) or not 1 <= len(slots) <= 8:
                raise BindingError('Invalid influence count')
            if any(not np.isfinite(w) or w < 0 for w in shares) or sum(shares) <= 0:
                raise BindingError('Invalid skin weights')
            unresolved = sorted({s for s, w in zip(slots, shares) if w > 0 and not 0 <= s < len(palette)})
            if unresolved:
                raise BindingError(f'Weighted slots {unresolved} exceed the validated {len(palette)}-bone palette')
            bones = [palette[s] if w > 0 else 0 for s, w in zip(slots, shares)]
            normal = [w / sum(shares) for w in shares]
            indices.append(bones + [0] * (8 - len(bones)))
            weights.append(normal + [0.] * (8 - len(normal)))
            rest.append((*point, 1.))
        faces.extend(tuple(i + base for i in face) for face in submesh.faces)
    if not rest or not faces or any(i < 0 or i >= len(rest) for f in faces for i in f):
        raise BindingError('Invalid attachment geometry')
    mesh = SkinnedMesh(path.rsplit('/', 1)[-1], np.asarray(rest), np.asarray(faces, dtype=np.int32),
                       np.asarray(indices, dtype=np.int32), np.asarray(weights), path, True, True)
    reconstructed = deform(mesh, skin_matrices(skeleton, [b.bind_matrix for b in skeleton.bones]))
    if not np.allclose(reconstructed, mesh.rest[:, :3], atol=1e-5, rtol=1e-5):
        raise BindingError('Mesh bind-pose reconstruction failed')
    return mesh


def decode_binding(data, path=''):
    from cdmw.modding.mesh_parser import _parse_par_sections, parse_pac
    sections = _parse_par_sections(data)
    section = next((s for s in sections if s['index'] == 0), None)
    if section is None or struct.unpack_from('<I', data, 0x10)[0] != 0:
        raise BindingError('Unsupported PAC section storage')
    skeleton, palette, offset, palette_offset, error = embedded_skeleton(
        data, section['offset'], section['offset'] + section['size'])
    mesh = exact_skin(parse_pac(data, path), skeleton, palette, path)
    return AttachmentBinding(skeleton, palette, mesh, offset, palette_offset, error)
