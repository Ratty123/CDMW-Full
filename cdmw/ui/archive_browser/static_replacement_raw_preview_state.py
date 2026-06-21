"""Static replacement raw mesh-preview state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping


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


__all__ = [
    "mesh_edit_raw_preview_initial_state",
    "mesh_edit_raw_preview_record_state",
]
