from __future__ import annotations

from collections import Counter
import json
import threading

_NATIVE_MESH_CORE_FALLBACK_EVENT_LIMIT = 64
_native_mesh_core_fallback_lock = threading.RLock()
_native_mesh_core_fallback_counts: Counter[str] = Counter()
_native_mesh_core_fallback_events: list[dict[str, object]] = []


def clear_native_mesh_core_fallback_counts() -> None:
    with _native_mesh_core_fallback_lock:
        _native_mesh_core_fallback_counts.clear()
        _native_mesh_core_fallback_events.clear()


def native_mesh_core_fallback_counts() -> dict[str, int]:
    with _native_mesh_core_fallback_lock:
        return dict(_native_mesh_core_fallback_counts)


def native_mesh_core_fallback_events() -> tuple[dict[str, object], ...]:
    with _native_mesh_core_fallback_lock:
        return tuple(dict(event) for event in _native_mesh_core_fallback_events)


def record_native_mesh_core_fallback(operation: object, reason: object = "", **details: object) -> None:
    operation_text = str(operation or "unknown").strip() or "unknown"
    event: dict[str, object] = {
        "operation": operation_text,
        "reason": str(reason or "unspecified").strip() or "unspecified",
    }
    for raw_key, raw_value in details.items():
        if raw_value is None:
            continue
        key = str(raw_key or "").strip()
        if key:
            event[key] = _native_mesh_core_fallback_detail(raw_value)
    with _native_mesh_core_fallback_lock:
        _native_mesh_core_fallback_counts[operation_text] += 1
        _native_mesh_core_fallback_events.append(event)
        if len(_native_mesh_core_fallback_events) > _NATIVE_MESH_CORE_FALLBACK_EVENT_LIMIT:
            del _native_mesh_core_fallback_events[:-_NATIVE_MESH_CORE_FALLBACK_EVENT_LIMIT]


def _native_mesh_core_fallback_detail(value: object) -> object:
    if isinstance(value, set):
        return sorted(_native_mesh_core_fallback_detail(item) for item in value)
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return str(value)
    return value
