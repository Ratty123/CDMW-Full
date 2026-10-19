"""Disconnected geometry and exact PAC island exclusion preserving part slots."""

from __future__ import annotations

import math
import struct

import numpy as np

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


def _separated_island_bounds(part, hidden, *, stop_event=None):
    """Bound simplification by both component size and clearance to its neighbours."""
    positions = np.asarray(part.vertices, dtype=np.float64)
    triangles = np.asarray(part.faces, dtype=np.intp)
    bounds, included = [], []
    for group in mesh_islands(part, stop_event=stop_event):
        raise_if_cancelled(stop_event)
        points = positions[triangles[list(group)].ravel()]
        bounds.append((points.min(axis=0), points.max(axis=0)))
        included.append(group[0] not in hidden)
    bounds = np.asarray(bounds)
    lower, upper = bounds[:, 0], bounds[:, 1]
    radii = np.zeros(len(bounds))
    for index in range(len(bounds)):
        raise_if_cancelled(stop_event)
        gaps = np.maximum(np.maximum(lower[index] - upper, lower - upper[index]), 0)
        distances = np.linalg.norm(gaps, axis=1)
        distances[index] = np.inf
        # Euclidean clearance keeps even diagonally neighbouring envelopes apart.
        # Overlapping/touching source bounds have zero clearance and cannot use
        # this envelope mapping. Large nearby voids
        # cannot justify a displacement larger than 10% of the component size.
        radii[index] = min(float(distances.min()) / 3,
                           float(np.linalg.norm(upper[index] - lower[index])) * .1)
    return lower, upper, radii, included


def _simplified_island_faces(part, owners, bounds, error, *, stop_event=None):
    """Map whole lower-LOD components, including splits and disappearing islands."""
    lower, upper, radii, included = bounds
    positions = np.asarray(part.vertices, dtype=np.float64)
    triangles = np.asarray(part.faces, dtype=np.intp)
    selected = []
    for group in mesh_islands(part, stop_event=stop_event):
        raise_if_cancelled(stop_event)
        points = positions[np.unique(triangles[list(group)])]
        labels = [owners.get(position_key(point)) for point in points]
        known = set().union(*(label for label in labels if label is not None))
        if len(known) > 1:
            raise ValueError(error)
        if len(known) == 1 and all(label is not None for label in labels):
            keep = next(iter(known))
        else:
            # Every point of the component's bounding box must fit in a single
            # separated source envelope. A centroid/nearest-vertex vote would
            # silently accept bridges and pieces straddling two source islands.
            excursions = np.maximum(np.maximum(lower - points.min(axis=0),
                                                points.max(axis=0) - upper), 0)
            candidates = np.flatnonzero((radii > 0) & (np.linalg.norm(excursions, axis=1) <= radii))
            if len(candidates) != 1:
                raise ValueError(error)
            keep = included[candidates[0]]
            if known and known != {keep}:
                raise ValueError(error)
        if not keep:
            selected.extend(group)
    return sorted(selected)


def _island_record_key(data, part, vertex, *, decoded_skin=False):
    # PAC's UV0 and skin/guide/mask lanes can survive simplification exactly,
    # unlike positions and packed normals. Never infer lineage from UVs alone.
    offset = part.source_vertex_offsets[vertex]
    uv = data[offset + 8:offset + 12]
    if decoded_skin:
        if (len(part.bone_indices) != len(part.vertices) or len(part.bone_weights) != len(part.vertices)
                or not part.bone_indices[vertex] or not any(part.bone_weights[vertex])):
            return None
        # Guide references and masks can change per LOD while resolved skeletal
        # bones and weights remain exact. Source ownership must still be unique.
        return uv, tuple(part.bone_indices[vertex]), tuple(part.bone_weights[vertex])
    return uv + data[offset + 20:offset + 40]


def _island_record_owners(data, part, hidden, *, decoded_skin=False, stop_event=None):
    owners = {}
    for face_index, face in enumerate(part.faces):
        if face_index % 4096 == 0:
            raise_if_cancelled(stop_event)
        for vertex in face:
            key = _island_record_key(data, part, vertex, decoded_skin=decoded_skin)
            if key is not None:
                owners.setdefault(key, set()).add(face_index not in hidden)
    return owners


def _retained_island_faces(data, previous, current, record_owners, position_owners, *, decoded_skin=False, stop_event=None):
    """Require exact retained records and bounded motion at every component vertex.

    A match spanning included and excluded source geometry is never authority.
    Movement must fit an incident edge of the matching preceding-LOD record;
    this follows progressive simplification without increasing spatial bounds.
    Return None when this independent correspondence cannot prove the output.
    """
    if not previous.vertices or not previous.faces:
        return None
    positions = np.asarray(previous.vertices, dtype=np.float64)
    triangles = np.asarray(previous.faces, dtype=np.intp)
    radius_squared = np.zeros(len(positions))
    for left, right in ((0, 1), (1, 2), (2, 0)):
        raise_if_cancelled(stop_event)
        delta = positions[triangles[:, left]] - positions[triangles[:, right]]
        length_squared = np.sum(delta * delta, axis=1)
        np.maximum.at(radius_squared, triangles[:, left], length_squared)
        np.maximum.at(radius_squared, triangles[:, right], length_squared)
    references = {}
    # A mixed or incomplete preceding component must not become a stepping stone
    # that launders an ambiguous merge into a later, apparently unique match.
    for group in mesh_islands(previous, stop_event=stop_event):
        raise_if_cancelled(stop_event)
        vertices = {v for f in group for v in previous.faces[f]}
        flags, keys = set(), {}
        for vertex in vertices:
            if vertex % 4096 == 0:
                raise_if_cancelled(stop_event)
            key = _island_record_key(data, previous, vertex, decoded_skin=decoded_skin)
            labels = record_owners.get(key)
            if labels is None or len(labels) != 1:
                break
            included = next(iter(labels))
            exact = position_owners.get(position_key(previous.vertices[vertex]))
            if exact is not None and exact != {included}:
                break
            flags.add(included)
            keys[vertex] = key
        else:
            if len(flags) == 1:
                for vertex, key in keys.items():
                    references.setdefault(key, []).append(vertex)
    selected, comparisons = [], 0
    for group in mesh_islands(current, stop_event=stop_event):
        raise_if_cancelled(stop_event)
        flags = set()
        for vertex in {v for f in group for v in current.faces[f]}:
            if vertex % 4096 == 0:
                raise_if_cancelled(stop_event)
            key = _island_record_key(data, current, vertex, decoded_skin=decoded_skin)
            labels = record_owners.get(key)
            if labels is None or len(labels) != 1:
                return None
            included = next(iter(labels))
            exact = position_owners.get(position_key(current.vertices[vertex]))
            if exact is not None and exact != {included}:
                return None
            matches = references.get(key, ())
            comparisons += len(matches)
            # Repeated uniform records must not turn this bounded fallback into
            # a quadratic search over a large untextured mesh.
            if not matches or comparisons > 2_000_000:
                return None
            delta = positions[matches] - current.vertices[vertex]
            if not np.any(np.sum(delta * delta, axis=1) <= radius_squared[matches]):
                return None
            flags.add(included)
        if len(flags) != 1:
            return None
        if flags == {False}:
            selected.extend(group)
    return sorted(selected)


def pac_island_face_masks(original_data, exclusions, *, stop_event=None):
    """Map retained LOD0 faces to every PAC LOD, rejecting unproven mappings.

    Prefer exact source positions. Simplified disconnected components can also
    map within bounded, separated source envelopes; overlapping or excessive
    simplification can also use exact retained UV/skin records with bounded
    preceding-LOD motion. Unproven mappings fail before output is published.
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
        bounds, record_owners = None, {}
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
                    error = f"Island mapping is ambiguous at LOD {lod_index}. Its simplified geometry cannot be excluded safely."
                    if lod_index == 0:
                        raise ValueError(error)
                    if bounds is None:
                        bounds = _separated_island_bounds(part, hidden, stop_event=stop_event)
                    try:
                        selected = _simplified_island_faces(current, owners, bounds, error, stop_event=stop_event)
                    except ValueError as exc:
                        if str(exc) != error:
                            raise
                        for decoded_skin in (False, True):
                            if decoded_skin not in record_owners:
                                record_owners[decoded_skin] = _island_record_owners(original_data, part, hidden,
                                    decoded_skin=decoded_skin, stop_event=stop_event)
                            selected = _retained_island_faces(original_data, lods[lod_index - 1].submeshes[part_index],
                                current, record_owners[decoded_skin], owners, decoded_skin=decoded_skin, stop_event=stop_event)
                            if selected is not None:
                                break
                        if selected is None:
                            raise
                    break
                if labels[0] == {False}:
                    selected.append(face_index)
            if lod_index == 0 and set(selected) != hidden:
                raise ValueError("Island selection is not a complete disconnected component.")
            masks[lod_index, part_index] = tuple(selected)
    return lods, masks


def _preserve_empty_island_part(result, part, lod_index):
    """Keep a valid tiny draw when all remaining islands disappear at this LOD."""
    axes = sorted((axis for axis in range(3) if math.isfinite(part.source_bbox_extent[axis])
                   and 0 < part.source_bbox_extent[axis] / 32767 < .002),
                  key=lambda axis: part.source_bbox_extent[axis])[:2]
    if len(axes) != 2:
        raise ValueError(f"Island exclusion cannot preserve an invisible part at LOD {lod_index}.")
    face = part.faces[0]
    offset = part.source_vertex_offsets[face[0]]
    donor = bytes(result[offset:offset + 40])
    origin = struct.unpack_from('<3H', donor)
    for index, vertex in enumerate(face):
        offset = part.source_vertex_offsets[vertex]
        # Matching skin/guide data prevents animation from stretching the tiny
        # triangle back out. Other unused source records remain byte-identical.
        result[offset:offset + 40] = donor
        position = list(origin)
        if index:
            axis = axes[index - 1]
            position[axis] += 1 if origin[axis] < 32767 else -1
        struct.pack_into('<3H', result, offset, *position)
    struct.pack_into('<3H', result, part.source_index_offset, *face)


def apply_pac_island_exclusions(data, original_data, exclusions, *, stop_event=None):
    """Suppress mapped triangles, retaining a tiny valid draw for an emptied LOD."""
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
        if hidden and len(hidden) == len(part.faces):
            _preserve_empty_island_part(result, part, lod_index)
    return bytes(result)
