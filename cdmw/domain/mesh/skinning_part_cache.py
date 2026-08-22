"""Content-keyed cache for per-part skinning summaries.

Split from ``skeleton`` to keep that module inside the owned-file line cap.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .skeleton import MeshSkinningPartSummary

# Walking every bone row of a part is the whole cost of a skinning summary, and
# one mesh open asks for the same summary several times over: once for the
# asset status, then once per OBJ export of the same geometry (the editable
# mesh and the scene copy are separate clones that share their rows). The
# summary is a pure function of the rows and the skeleton bone count, so it is
# keyed on their content and kept for the last few parts seen.
PART_SUMMARY_CACHE_LIMIT = 64
PART_SUMMARY_CACHE: "OrderedDict[tuple[object, ...], MeshSkinningPartSummary]" = OrderedDict()


def part_summary_cache_key(
    row_tuple,
    index: int,
    submesh: object,
    vertices: tuple[object, ...],
    bone_indices: tuple[object, ...],
    bone_weights: tuple[object, ...],
    *,
    selected: bool,
    skeleton_bone_count: int | None,
) -> tuple[object, ...] | None:
    try:
        return (
            index,
            str(getattr(submesh, "name", "") or ""),
            len(vertices),
            len(bone_indices),
            len(bone_weights),
            bool(selected),
            skeleton_bone_count,
            row_tuple(bone_indices[0]) if bone_indices else (),
            row_tuple(bone_indices[-1]) if bone_indices else (),
            hash(tuple(row_tuple(row) for row in bone_indices)),
            hash(tuple(row_tuple(row) for row in bone_weights)),
        )
    except TypeError:
        return None




def cached_part_summary(key: tuple[object, ...] | None) -> "MeshSkinningPartSummary | None":
    if key is None:
        return None
    cached = PART_SUMMARY_CACHE.get(key)
    if cached is not None:
        PART_SUMMARY_CACHE.move_to_end(key)
    return cached


def remember_part_summary(key: tuple[object, ...] | None, summary: "MeshSkinningPartSummary") -> None:
    if key is None:
        return
    PART_SUMMARY_CACHE[key] = summary
    while len(PART_SUMMARY_CACHE) > PART_SUMMARY_CACHE_LIMIT:
        PART_SUMMARY_CACHE.popitem(last=False)
