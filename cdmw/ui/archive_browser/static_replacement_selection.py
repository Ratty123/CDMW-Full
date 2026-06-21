"""Pure source selection helpers for static replacement."""

from __future__ import annotations

from collections.abc import Sequence


def part_source_indices_for_commit(
    raw_source_indices: Sequence[int],
    replacement_mesh: object | None,
    *,
    geometry_tab_active: bool,
) -> tuple[int, ...]:
    if not geometry_tab_active or replacement_mesh is None:
        return ()
    source_count = len(getattr(replacement_mesh, "submeshes", ()) or ())
    indices: list[int] = []
    for raw_index in sorted(int(index) for index in tuple(raw_source_indices or ())):
        if 0 <= raw_index < source_count:
            indices.append(raw_index)
    return tuple(indices)


def single_part_source_index_for_preview(source_indices: Sequence[int]) -> int:
    return int(source_indices[0]) if len(source_indices) == 1 else -1


__all__ = [
    "part_source_indices_for_commit",
    "single_part_source_index_for_preview",
]
