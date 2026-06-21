"""Static replacement preview batch state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping

_REQUEST_KEYS = ("texture", "texture_uv", "rebuild", "refresh")


def static_preview_batch_initial_state() -> dict[str, object]:
    return {"depth": 0, **{key: False for key in _REQUEST_KEYS}}


def static_preview_batch_queue_request(state: MutableMapping[str, object], request: str) -> bool:
    if int(state.get("depth", 0) or 0) <= 0:
        return False
    key = str(request or "").strip()
    if key in _REQUEST_KEYS:
        state[key] = True
    return True


def static_preview_batch_begin(state: MutableMapping[str, object]) -> None:
    state["depth"] = int(state.get("depth", 0) or 0) + 1


def static_preview_batch_end(state: MutableMapping[str, object]) -> dict[str, bool] | None:
    state["depth"] = max(0, int(state.get("depth", 0) or 0) - 1)
    if int(state.get("depth", 0) or 0) > 0:
        return None
    payload = {key: bool(state.get(key)) for key in _REQUEST_KEYS}
    for key in _REQUEST_KEYS:
        state[key] = False
    return payload


__all__ = [
    "static_preview_batch_begin",
    "static_preview_batch_end",
    "static_preview_batch_initial_state",
    "static_preview_batch_queue_request",
]
