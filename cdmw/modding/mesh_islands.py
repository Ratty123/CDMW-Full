"""Disconnected geometry and exact PAC island exclusion without vertex edits."""

from __future__ import annotations

import math
import struct

from cdmw.domain.cancellation import raise_if_cancelled


def position_key(position):
    """Quantize seam positions to 1e-5 model units without welding output."""
    return tuple(math.floor(float(v) * 100_000 + .5) if v >= 0
                 else math.ceil(float(v) * 100_000 - .5) for v in position)


def mesh_islands(part, *, join_seams=True, stop_event=None):
    """Return deterministic tuples of face indices, staying within one part."""
    parent = list(range(len(part.vertices)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    if join_seams:
        positions = {}
        for index, vertex in enumerate(part.vertices):
            if index % 4096 == 0:
                raise_if_cancelled(stop_event)
            key = position_key(vertex)
            if key in positions:
                union(index, positions[key])
            else:
                positions[key] = index
    for index, face in enumerate(part.faces):
        if index % 4096 == 0:
            raise_if_cancelled(stop_event)
        if len(face) != 3 or any(type(v) is not int or not 0 <= v < len(parent) for v in face):
            raise ValueError("Mesh island contains an invalid face.")
        union(face[0], face[1])
        union(face[0], face[2])
    groups = {}
    for index, face in enumerate(part.faces):
        if index % 4096 == 0:
            raise_if_cancelled(stop_event)
        groups.setdefault(find(face[0]), []).append(index)
    return tuple(tuple(group) for group in sorted(groups.values(), key=lambda values: values[0]))


def pac_island_face_masks(original_data, exclusions, *, stop_event=None):
    """Map retained LOD0 faces to every PAC LOD, rejecting unproven mappings.

    Coarser LODs must retain identifiable source positions. Guessing nearest
    geometry can remove an adjacent island; ambiguous or simplified positions
    therefore fail before any output is published.
    """
    from cdmw.modding.pac_cloth import pac_cloth_lods

    lods = pac_cloth_lods(original_data)
    masks = {}
    for part_index, values in exclusions.items():
        raise_if_cancelled(stop_event)
        if type(part_index) is not int or not 0 <= part_index < len(lods[0].submeshes):
            raise ValueError("Choose a valid part for island exclusion.")
        part = lods[0].submeshes[part_index]
        hidden = set(values)
        if any(type(v) is not int or not 0 <= v < len(part.faces) for v in hidden):
            raise ValueError("Island face mapping no longer matches the original part.")
        if not hidden:
            continue
        if len(hidden) == len(part.faces):
            raise ValueError("Keep one island included, or exclude the entire part with its Mod control.")
        owners = {}
        for face_index, face in enumerate(part.faces):
            if face_index % 4096 == 0:
                raise_if_cancelled(stop_event)
            included = face_index not in hidden
            for vertex in face:
                key = position_key(part.vertices[vertex])
                owners.setdefault(key, set()).add(included)
        if any(len(value) != 1 for value in owners.values()):
            raise ValueError("Island boundaries share source positions. Join seams before excluding this island.")
        for lod_index, lod in enumerate(lods):
            if part_index >= len(lod.submeshes):
                raise ValueError(f"Island part mapping is missing at LOD {lod_index}.")
            current = lod.submeshes[part_index]
            if current.source_index_count != len(current.faces) * 3:
                raise ValueError("Island exclusion requires a complete original triangle index mapping.")
            raw = tuple(struct.iter_unpack('<3H', original_data[current.source_index_offset:
                current.source_index_offset + current.source_index_count * 2])) if current.faces else ()
            if raw != tuple(current.faces):
                raise ValueError("Island exclusion cannot prove the stored triangle mapping.")
            selected = []
            for face_index, face in enumerate(current.faces):
                if face_index % 4096 == 0:
                    raise_if_cancelled(stop_event)
                labels = [owners.get(position_key(current.vertices[vertex])) for vertex in face]
                if any(label is None for label in labels) or len(set(tuple(label) for label in labels)) != 1:
                    raise ValueError(f"Island mapping is ambiguous at LOD {lod_index}. Its simplified geometry cannot be excluded safely.")
                if labels[0] == {False}:
                    selected.append(face_index)
            if lod_index == 0 and set(selected) != hidden:
                raise ValueError("Island selection is not a complete disconnected component.")
            masks[lod_index, part_index] = tuple(selected)
    return lods, masks


def apply_pac_island_exclusions(data, original_data, exclusions, *, stop_event=None):
    """Suppress mapped triangles; preserve every vertex and other index byte."""
    from cdmw.modding.pac_cloth import pac_cloth_lods

    reference, masks = pac_island_face_masks(original_data, exclusions, stop_event=stop_event)
    output = pac_cloth_lods(data)
    if len(output) != len(reference):
        raise ValueError("Island exclusion lost its original LOD mapping.")
    result = bytearray(data)
    for (lod_index, part_index), hidden in masks.items():
        raise_if_cancelled(stop_event)
        old = reference[lod_index].submeshes[part_index]
        if part_index >= len(output[lod_index].submeshes):
            raise ValueError("Island exclusion lost its original part mapping.")
        part = output[lod_index].submeshes[part_index]
        if len(part.vertices) != len(old.vertices) or part.faces != old.faces:
            raise ValueError("Island exclusion requires unchanged source topology. Restore islands before replacing or rebuilding this part.")
        for face_index in hidden:
            vertex = part.faces[face_index][0]
            struct.pack_into('<3H', result, part.source_index_offset + face_index * 6,
                             vertex, vertex, vertex)
    return bytes(result)
