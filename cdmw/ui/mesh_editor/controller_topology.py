"""Small topology packet rules shared by the Mesh Editor controller."""

from __future__ import annotations

from collections.abc import Sequence

from cdmw.domain.mesh import MeshEditResult


def final_submesh_count(controller: object, result: MeshEditResult) -> int | None:
    if result.submesh_counts:
        return len(result.submesh_counts)
    try:
        return max(0, int(controller.session_view().submesh_count))
    except (AttributeError, RuntimeError, TypeError, ValueError, OverflowError):
        return None


def shrink_source_indices(
    result: MeshEditResult,
    requested: Sequence[int],
    final_count: int,
) -> tuple[int, ...]:
    previous_count = max(final_count, final_count - int(result.submesh_count_delta))
    first_affected = min((*requested, final_count))
    last_affected = max(previous_count, max(requested, default=-1) + 1)
    return tuple(range(first_affected, last_affected))


__all__ = ["final_submesh_count", "shrink_source_indices"]
