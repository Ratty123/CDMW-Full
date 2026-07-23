"""Static replacement raw mesh-preview state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeshEditRawPreviewTransitionRoute:
    changed: bool
    should_clear_static_preview_caches: bool
    should_invalidate_package_cache: bool
    should_queue_static_preview_refresh: bool
    should_stop_raw_package: bool
    should_queue_texture_preview_refresh: bool


def mesh_edit_raw_preview_initial_state() -> dict[str, bool]:
    return {"active": False}


def mesh_edit_raw_preview_record_state(
    state: MutableMapping[str, object],
    active: bool,
) -> tuple[bool, bool]:
    previous = bool(state.get("active"))
    current = bool(active)
    state["active"] = current
    return previous, current


def mesh_edit_raw_preview_transition_route(
    previous_raw: bool,
    current_raw: bool,
    *,
    raw_package_active_or_pending: bool,
) -> MeshEditRawPreviewTransitionRoute:
    del raw_package_active_or_pending
    previous = bool(previous_raw)
    current = bool(current_raw)
    changed = previous != current
    return MeshEditRawPreviewTransitionRoute(
        changed=changed,
        should_clear_static_preview_caches=False,
        should_invalidate_package_cache=False,
        should_queue_static_preview_refresh=False,
        should_stop_raw_package=False,
        should_queue_texture_preview_refresh=False,
    )


__all__ = [
    "MeshEditRawPreviewTransitionRoute",
    "mesh_edit_raw_preview_initial_state",
    "mesh_edit_raw_preview_record_state",
    "mesh_edit_raw_preview_transition_route",
]
