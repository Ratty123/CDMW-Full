"""D3D11 request queue and metadata state helpers for static replacement previews."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AlignmentD3D11ProcessRequestMetadata:
    display_mode: str
    package_quality: str
    rebuild_reason: str
    cache_key: str


def _request_id(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def alignment_d3d11_request_package_quality(
    state: Mapping[str, object],
    request_id: int,
    *,
    fallback: str = "",
) -> str:
    request_package_qualities = state.get("request_package_qualities")
    quality = str(fallback or "")
    if isinstance(request_package_qualities, Mapping):
        quality = str(request_package_qualities.get(_request_id(request_id), quality) or quality)
    return quality.strip().lower()


def alignment_d3d11_remember_request_package_quality(
    state: MutableMapping[str, object],
    request_id: int,
    package_quality: str,
) -> None:
    request_package_qualities = state.get("request_package_qualities")
    if not isinstance(request_package_qualities, dict):
        request_package_qualities = {}
        state["request_package_qualities"] = request_package_qualities
    request_package_qualities[_request_id(request_id)] = str(package_quality or "normal").strip().lower()


def alignment_d3d11_begin_package_request(
    state: MutableMapping[str, object],
    *,
    drag_generation: int,
    transform_generation: int,
    display_mode: str,
    reason: str,
    package_quality: str,
) -> int:
    state["request_id"] = _request_id(state.get("request_id")) + 1
    request_id = _request_id(state["request_id"])
    request_drag_generation = int(drag_generation or 0)
    request_transform_generation = int(transform_generation or 0)
    state["request_drag_generation"] = request_drag_generation
    request_generations = state.get("request_drag_generations")
    if not isinstance(request_generations, dict):
        request_generations = {}
        state["request_drag_generations"] = request_generations
    request_generations[request_id] = request_drag_generation
    state["request_transform_generation"] = request_transform_generation
    request_transform_generations = state.get("request_transform_generations")
    if not isinstance(request_transform_generations, dict):
        request_transform_generations = {}
        state["request_transform_generations"] = request_transform_generations
    request_transform_generations[request_id] = request_transform_generation
    request_display_modes = state.get("request_display_modes")
    if not isinstance(request_display_modes, dict):
        request_display_modes = {}
        state["request_display_modes"] = request_display_modes
    request_display_modes[request_id] = str(display_mode or "")
    request_reasons = state.get("request_reasons")
    if not isinstance(request_reasons, dict):
        request_reasons = {}
        state["request_reasons"] = request_reasons
    request_reasons[request_id] = str(reason or "")
    alignment_d3d11_remember_request_package_quality(state, request_id, package_quality)
    return request_id


def alignment_d3d11_queue_pending_request(
    state: MutableMapping[str, object],
    *,
    model: object,
    label: str,
    display_mode: str,
    reason: str,
    transform_generation: int,
    package_quality: str,
) -> int:
    state["request_id"] = _request_id(state.get("request_id")) + 1
    state["pending_model"] = model
    state["pending_label"] = str(label or "")
    state["pending_display_mode"] = str(display_mode or "")
    state["pending_reason"] = str(reason or "")
    state["pending_transform_generation"] = int(transform_generation or 0)
    state["pending_package_quality"] = str(package_quality or "")
    return _request_id(state["request_id"])


def alignment_d3d11_queue_preview_request(
    state: MutableMapping[str, object],
    *,
    model: object,
    label: str,
    display_mode: str,
    reason: str,
    transform_generation: int,
    package_quality: str,
) -> None:
    state["next_rebuild_reason"] = ""
    state["queued_model"] = model
    state["queued_label"] = str(label or "Live alignment preview")
    state["queued_display_mode"] = str(display_mode or "")
    state["queued_reason"] = str(reason or "")
    state["queued_transform_generation"] = int(transform_generation or 0)
    state["queued_package_quality"] = str(package_quality or "")


def alignment_d3d11_mark_rebuild_reason(state: MutableMapping[str, object], reason: str) -> str:
    normalized = str(reason or "geometry").strip().lower()
    if normalized not in {"geometry", "texture_uv", "material", "mode_missing_original"}:
        normalized = "geometry"
    if not str(state.get("next_rebuild_reason", "") or ""):
        state["next_rebuild_reason"] = normalized
    return normalized


def alignment_d3d11_clear_queued_preview_request(state: MutableMapping[str, object]) -> None:
    state["queued_model"] = None
    state["queued_label"] = ""
    state["queued_display_mode"] = ""
    state["queued_reason"] = ""
    state["queued_transform_generation"] = 0
    state["queued_package_quality"] = ""


def alignment_d3d11_take_pending_request(
    state: MutableMapping[str, object],
    *,
    label_fallback: str,
    display_mode_fallback: str,
) -> dict[str, object]:
    pending_request = {
        "model": state.get("pending_model"),
        "label": str(state.get("pending_label", "") or label_fallback),
        "display_mode": str(state.get("pending_display_mode", "") or display_mode_fallback),
        "reason": str(state.get("pending_reason", "") or "geometry"),
        "transform_generation": int(state.get("pending_transform_generation", 0) or 0),
        "package_quality": str(state.get("pending_package_quality", "") or ""),
    }
    state["pending_model"] = None
    state["pending_label"] = ""
    state["pending_display_mode"] = ""
    state["pending_reason"] = ""
    state["pending_transform_generation"] = 0
    state["pending_package_quality"] = ""
    return pending_request


def alignment_d3d11_record_package_worker_refs(
    state: MutableMapping[str, object],
    *,
    worker: object,
    thread: object,
) -> None:
    state["worker"] = worker
    state["thread"] = thread


def alignment_d3d11_clear_package_worker_refs(state: MutableMapping[str, object]) -> None:
    state["thread"] = None
    state["worker"] = None


def alignment_d3d11_next_original_texture_worker_request_id(state: MutableMapping[str, object]) -> int:
    request_id = _request_id(state.get("original_texture_worker_request_id")) + 1
    state["original_texture_worker_request_id"] = request_id
    return request_id


def alignment_d3d11_original_texture_worker_request_current(
    state: Mapping[str, object],
    request_id: int,
) -> bool:
    return _request_id(request_id) == _request_id(state.get("original_texture_worker_request_id"))


def alignment_d3d11_record_original_texture_worker_refs(
    state: MutableMapping[str, object],
    *,
    worker: object,
    thread: object,
) -> None:
    state["original_texture_worker"] = worker
    state["original_texture_thread"] = thread


def alignment_d3d11_clear_original_texture_worker_refs(state: MutableMapping[str, object]) -> None:
    state["original_texture_worker"] = None
    state["original_texture_thread"] = None


def alignment_d3d11_record_stale_reload_restart(state: MutableMapping[str, object]) -> int:
    restart_count = int(state.get("stale_reload_restart_count", 0) or 0) + 1
    state["stale_reload_restart_count"] = restart_count
    return restart_count


def alignment_d3d11_reset_request_state(
    state: MutableMapping[str, object],
    *,
    increment_request: bool = True,
    clear_loading: bool = False,
    clear_active_request_id: bool = True,
    clear_active_metadata: bool = False,
    clear_mapping_ids: bool = False,
) -> None:
    if increment_request:
        state["request_id"] = _request_id(state.get("request_id")) + 1
    for key, value in (
        ("queued_model", None),
        ("queued_label", ""),
        ("queued_display_mode", ""),
        ("queued_reason", ""),
        ("queued_transform_generation", 0),
        ("queued_package_quality", ""),
        ("pending_model", None),
        ("pending_label", ""),
        ("pending_display_mode", ""),
        ("pending_reason", ""),
        ("pending_transform_generation", 0),
        ("pending_package_quality", ""),
        ("request_display_modes", {}),
        ("request_package_qualities", {}),
        ("request_reasons", {}),
        ("request_cache_keys", {}),
    ):
        state[key] = value
    if clear_active_request_id:
        state["active_package_request_id"] = 0
    if clear_active_metadata:
        state["active_package_display_mode"] = ""
        state["active_package_quality"] = ""
        state["active_package_cache_key"] = ""
    if clear_mapping_ids:
        state["source_to_d3d11_ids"] = {}
        state["d3d11_id_to_source_indices"] = {}
    if clear_loading:
        state["preview_loaded"] = False
        state["loading_percent"] = 0
        state["loading_stage"] = ""
        state["loading_message"] = ""


def alignment_d3d11_request_reason(
    state: Mapping[str, object],
    *,
    request_id: int = 0,
    fallback: str = "geometry",
) -> str:
    normalized = str(fallback or "geometry").strip().lower() or "geometry"
    request_reasons = state.get("request_reasons")
    request_id = _request_id(request_id)
    if isinstance(request_reasons, Mapping) and request_id > 0:
        normalized = str(request_reasons.get(request_id, normalized) or normalized).strip().lower()
    return normalized if normalized in {"geometry", "texture_uv", "material", "mode_missing_original"} else "geometry"


def alignment_d3d11_request_display_mode(
    state: Mapping[str, object],
    request_id: int,
    *,
    fallback: str,
) -> str:
    request_display_modes = state.get("request_display_modes")
    normalized = str(fallback or "side_by_side")
    if isinstance(request_display_modes, Mapping):
        normalized = str(request_display_modes.get(_request_id(request_id), normalized) or normalized)
    return normalized


def alignment_d3d11_request_cache_key(state: Mapping[str, object], request_id: int) -> str:
    request_cache_keys = state.get("request_cache_keys")
    if isinstance(request_cache_keys, Mapping):
        return str(request_cache_keys.get(_request_id(request_id), "") or "")
    return ""


def alignment_d3d11_process_request_metadata(
    state: Mapping[str, object],
    request_id: int,
    *,
    display_mode_fallback: object,
    package_quality_fallback: object,
    rebuild_reason_fallback: object,
) -> AlignmentD3D11ProcessRequestMetadata:
    return AlignmentD3D11ProcessRequestMetadata(
        display_mode=alignment_d3d11_request_display_mode(state, request_id, fallback=str(display_mode_fallback or "")),
        package_quality=alignment_d3d11_request_package_quality(
            state,
            request_id,
            fallback=str(package_quality_fallback or "normal"),
        )
        or "normal",
        rebuild_reason=alignment_d3d11_request_reason(
            state,
            request_id=request_id,
            fallback=str(rebuild_reason_fallback or "geometry"),
        ),
        cache_key=alignment_d3d11_request_cache_key(state, request_id),
    )


def alignment_d3d11_cache_key_with_native_reference(
    cache_key: str,
    *,
    native_reference_signature_hash: object = "",
) -> str:
    key = str(cache_key or "")
    signature_hash = str(native_reference_signature_hash or "").strip()
    if signature_hash:
        key = f"{key}|native_ref={signature_hash}"
    return f"{key}|original_reference_native_splice=role_aware_v3"


def alignment_d3d11_remember_request_cache_key(
    state: MutableMapping[str, object],
    request_id: int,
    cache_key: str,
) -> None:
    request_cache_keys = state.get("request_cache_keys")
    if not isinstance(request_cache_keys, dict):
        request_cache_keys = {}
        state["request_cache_keys"] = request_cache_keys
    request_cache_keys[_request_id(request_id)] = str(cache_key or "")


__all__ = [
    "AlignmentD3D11ProcessRequestMetadata",
    "alignment_d3d11_begin_package_request",
    "alignment_d3d11_cache_key_with_native_reference",
    "alignment_d3d11_clear_original_texture_worker_refs",
    "alignment_d3d11_clear_package_worker_refs",
    "alignment_d3d11_clear_queued_preview_request",
    "alignment_d3d11_mark_rebuild_reason",
    "alignment_d3d11_next_original_texture_worker_request_id",
    "alignment_d3d11_original_texture_worker_request_current",
    "alignment_d3d11_process_request_metadata",
    "alignment_d3d11_queue_pending_request",
    "alignment_d3d11_queue_preview_request",
    "alignment_d3d11_record_original_texture_worker_refs",
    "alignment_d3d11_record_package_worker_refs",
    "alignment_d3d11_record_stale_reload_restart",
    "alignment_d3d11_remember_request_cache_key",
    "alignment_d3d11_remember_request_package_quality",
    "alignment_d3d11_reset_request_state",
    "alignment_d3d11_request_cache_key",
    "alignment_d3d11_request_display_mode",
    "alignment_d3d11_request_package_quality",
    "alignment_d3d11_request_reason",
    "alignment_d3d11_take_pending_request",
]
