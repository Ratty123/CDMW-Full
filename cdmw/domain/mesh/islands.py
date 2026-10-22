"""Deterministic disconnected mesh surfaces, including quantized material seams."""
from __future__ import annotations

import math

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
