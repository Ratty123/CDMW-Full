"""Original-reference texture preview state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True)
class OriginalReferenceTexturePreviewPerformance:
    summary: str
    details: str = ""


@dataclass(frozen=True)
class OriginalTexturePreviewToggleState:
    enabled: bool
    should_clear_failure: bool
    should_load: bool
    should_refresh: bool = True


@dataclass(frozen=True)
class OriginalReferenceTexturePreviewReadyState:
    ready: bool
    should_start_load: bool
    message: str
    progress_message: str
    performance: OriginalReferenceTexturePreviewPerformance


@dataclass(frozen=True)
class OriginalReferenceTexturePreviewLoadStartState:
    should_start: bool
    progress_message: str
    detail: str
    performance: OriginalReferenceTexturePreviewPerformance


@dataclass(frozen=True)
class OriginalReferenceTexturePreviewReadyResultState:
    handled: bool
    should_apply_model: bool
    should_apply_manifest_performance: bool
    should_update_d3d11_progress: bool
    manifest_performance: OriginalReferenceTexturePreviewPerformance
    loaded_performance: OriginalReferenceTexturePreviewPerformance
    progress_message: str
    progress_detail: str


@dataclass(frozen=True)
class OriginalReferenceTexturePreviewErrorState:
    handled: bool
    message: str
    performance: OriginalReferenceTexturePreviewPerformance


@dataclass(frozen=True)
class OriginalReferenceTexturePreviewExceptionState:
    message: str
    performance: OriginalReferenceTexturePreviewPerformance


def original_texture_preview_initial_state(enabled: bool = False) -> dict[str, bool]:
    return {"enabled": bool(enabled)}


def original_texture_preview_enabled(state: MutableMapping[str, object]) -> bool:
    return bool(state.get("enabled"))


def original_texture_preview_set_enabled(
    state: MutableMapping[str, object],
    checked: bool,
    *,
    modify_original_clone_mode: bool,
) -> bool:
    enabled = bool(checked and modify_original_clone_mode)
    state["enabled"] = enabled
    return enabled


def original_texture_preview_toggle_state(
    preview_state: MutableMapping[str, object],
    reference_state: MutableMapping[str, object],
    checked: bool,
    *,
    modify_original_clone_mode: bool,
) -> OriginalTexturePreviewToggleState:
    enabled = original_texture_preview_set_enabled(
        preview_state,
        checked,
        modify_original_clone_mode=modify_original_clone_mode,
    )
    if enabled:
        original_reference_texture_preview_clear_failure(reference_state)
    return OriginalTexturePreviewToggleState(
        enabled=enabled,
        should_clear_failure=enabled,
        should_load=enabled,
    )


def original_texture_preview_material_preview_enabled(
    modify_original_clone_mode: bool,
    state: MutableMapping[str, object],
) -> bool:
    return bool(modify_original_clone_mode and original_texture_preview_enabled(state))


def original_texture_preview_control_text() -> dict[str, str]:
    return {
        "group_title": "Original Texture Preview",
        "checkbox_label": "Preview with original DDS/materials",
    }


def original_texture_preview_checkbox_tooltip() -> str:
    return (
        "For Modify Original clones, reuse the selected archive model's resolved texture bindings in the live replacement preview. "
        "This can trigger DDS preview preparation, but keeps placement work visually aligned with Archive Preview."
    )


def original_texture_preview_help_text() -> str:
    return (
        "Preview-only: original game DDS files are reused for display and are not copied into the loose mod unless you add replacement textures."
    )


def original_texture_preview_note_text(
    *,
    modify_original_clone_mode: bool,
    defer_original_texture_preview: bool,
) -> str:
    if not modify_original_clone_mode:
        return "Exact Modify Original clones only."
    if defer_original_texture_preview:
        return "On by default for Modify Original so the workspace reuses archive DDS/materials; disable only for faster rough geometry checks."
    return "Preview-only; exported only when replaced."


def original_texture_preview_note_tooltip(
    *,
    modify_original_clone_mode: bool,
    defer_original_texture_preview: bool,
) -> str:
    if not modify_original_clone_mode:
        return "Available when the imported OBJ is an exact Modify Original clone of the selected archive model."
    if defer_original_texture_preview:
        return "Original game DDS files are reused only for display. Disabling this gives a faster untextured geometry check."
    return original_texture_preview_help_text()


def original_reference_texture_preview_initial_state() -> dict[str, object]:
    return {
        "loaded": False,
        "loading": False,
        "failed": False,
        "error": "",
        "native_package_path": "",
    }


def original_reference_texture_preview_required(
    active_preview_mode: str,
    *,
    has_original_reference_model: bool,
) -> bool:
    return bool(str(active_preview_mode or "") in {"side_by_side", "overlay"} and has_original_reference_model)


def original_reference_texture_preview_readiness(
    state: Mapping[str, object],
    *,
    active_preview_mode: str,
    has_original_reference_model: bool,
) -> str:
    if not original_reference_texture_preview_required(
        active_preview_mode,
        has_original_reference_model=has_original_reference_model,
    ):
        return "ready"
    if bool(state.get("loaded")) or bool(state.get("failed")):
        return "ready"
    if bool(state.get("loading")):
        return "loading"
    return "start"


def original_reference_texture_preview_ready_state(
    state: Mapping[str, object],
    *,
    active_preview_mode: str,
    has_original_reference_model: bool,
    reason: str,
) -> OriginalReferenceTexturePreviewReadyState:
    readiness = original_reference_texture_preview_readiness(
        state,
        active_preview_mode=active_preview_mode,
        has_original_reference_model=has_original_reference_model,
    )
    message = original_reference_texture_preview_loading_message()
    return OriginalReferenceTexturePreviewReadyState(
        ready=readiness == "ready",
        should_start_load=readiness == "start",
        message=message,
        progress_message=original_reference_texture_preview_resolving_progress_message(),
        performance=original_reference_texture_preview_loading_performance(reason),
    )


def original_reference_texture_preview_archive_parity_state(
    state: Mapping[str, object],
    *,
    active_preview_mode: str,
    has_original_reference_model: bool,
) -> tuple[bool, bool]:
    readiness = original_reference_texture_preview_readiness(
        state,
        active_preview_mode=active_preview_mode,
        has_original_reference_model=has_original_reference_model,
    )
    return readiness == "ready", readiness == "start"


def original_reference_texture_preview_can_start_load(
    state: Mapping[str, object],
    *,
    has_original_reference_model: bool,
) -> bool:
    return bool(
        has_original_reference_model
        and not bool(state.get("loaded"))
        and not bool(state.get("loading"))
    )


def original_reference_texture_preview_set_native_package_path(
    state: MutableMapping[str, object],
    package_path: object,
) -> None:
    state["native_package_path"] = str(package_path or "")


def original_reference_texture_preview_clear_native_package_path(state: MutableMapping[str, object]) -> None:
    state["native_package_path"] = ""


def original_reference_texture_preview_mark_loaded(state: MutableMapping[str, object]) -> None:
    state["loaded"] = True
    state["loading"] = False
    state["failed"] = False
    state["error"] = ""


def original_reference_texture_preview_mark_failed(
    state: MutableMapping[str, object],
    message: object,
    *,
    clear_loading: bool = True,
    clear_native_package: bool = True,
) -> None:
    state["loaded"] = False
    if clear_loading:
        state["loading"] = False
    state["failed"] = True
    state["error"] = str(message)
    if clear_native_package:
        state["native_package_path"] = ""


def original_reference_texture_preview_mark_loading(state: MutableMapping[str, object]) -> None:
    state["loading"] = True
    state["failed"] = False
    state["error"] = ""
    state["native_package_path"] = ""


def original_reference_texture_preview_load_start_state(
    state: MutableMapping[str, object],
    *,
    has_original_reference_model: bool,
) -> OriginalReferenceTexturePreviewLoadStartState:
    if not original_reference_texture_preview_can_start_load(
        state,
        has_original_reference_model=has_original_reference_model,
    ):
        return OriginalReferenceTexturePreviewLoadStartState(
            should_start=False,
            progress_message="",
            detail="",
            performance=OriginalReferenceTexturePreviewPerformance(summary=""),
        )
    original_reference_texture_preview_mark_loading(state)
    return OriginalReferenceTexturePreviewLoadStartState(
        should_start=True,
        progress_message=original_reference_texture_preview_resolving_progress_message(),
        detail=original_reference_texture_preview_loading_message(),
        performance=original_reference_texture_preview_loading_performance(),
    )


def original_reference_texture_preview_clear_loading(state: MutableMapping[str, object]) -> None:
    state["loading"] = False


def original_reference_texture_preview_clear_failure(state: MutableMapping[str, object]) -> None:
    state["failed"] = False
    state["error"] = ""


def original_reference_texture_preview_loading_message() -> str:
    return "Loading original textures: base/sidecar/support maps..."


def original_reference_texture_preview_resolving_progress_message() -> str:
    return "Preparing preview - resolving original textures."


def original_reference_texture_preview_loaded_progress_message() -> str:
    return "Preparing preview - original textures loaded."


def original_reference_texture_preview_loaded_detail() -> str:
    return "Original textures loaded; applying resident materials."


def original_reference_texture_preview_loading_performance(reason: str = "") -> OriginalReferenceTexturePreviewPerformance:
    details = f"reason={str(reason or '')}" if str(reason or "") else ""
    return OriginalReferenceTexturePreviewPerformance(
        summary=original_reference_texture_preview_loading_message(),
        details=details,
    )


def original_reference_texture_preview_manifest_performance(
    native_material_batches: int,
) -> OriginalReferenceTexturePreviewPerformance:
    return OriginalReferenceTexturePreviewPerformance(
        summary=f"Original native material manifest applied: {int(native_material_batches):,} batch(es).",
    )


def original_reference_texture_preview_loaded_performance(
    elapsed_ms: float,
) -> OriginalReferenceTexturePreviewPerformance:
    return OriginalReferenceTexturePreviewPerformance(
        summary=original_reference_texture_preview_loaded_detail(),
        details=f"worker_elapsed_ms={float(elapsed_ms):.1f}",
    )


def original_reference_texture_preview_ready_result_state(
    state: MutableMapping[str, object],
    *,
    request_current: bool,
    widgets_live: bool,
    native_material_batches: int,
    elapsed_ms: float,
    d3d11_preview_active: bool,
) -> OriginalReferenceTexturePreviewReadyResultState:
    if not request_current or not widgets_live:
        return OriginalReferenceTexturePreviewReadyResultState(
            handled=False,
            should_apply_model=False,
            should_apply_manifest_performance=False,
            should_update_d3d11_progress=False,
            manifest_performance=OriginalReferenceTexturePreviewPerformance(summary=""),
            loaded_performance=OriginalReferenceTexturePreviewPerformance(summary=""),
            progress_message="",
            progress_detail="",
        )
    original_reference_texture_preview_mark_loaded(state)
    return OriginalReferenceTexturePreviewReadyResultState(
        handled=True,
        should_apply_model=not bool(d3d11_preview_active),
        should_apply_manifest_performance=bool(native_material_batches),
        should_update_d3d11_progress=bool(d3d11_preview_active),
        manifest_performance=original_reference_texture_preview_manifest_performance(native_material_batches),
        loaded_performance=original_reference_texture_preview_loaded_performance(elapsed_ms),
        progress_message=original_reference_texture_preview_loaded_progress_message(),
        progress_detail=original_reference_texture_preview_loaded_detail(),
    )


def original_reference_texture_preview_failed_message(message: object) -> str:
    return f"Original texture preview failed; continuing untextured: {message}"


def original_reference_texture_preview_resolve_failed_performance(
    message: object,
) -> OriginalReferenceTexturePreviewPerformance:
    return OriginalReferenceTexturePreviewPerformance(
        summary="Original texture resolve failed.",
        details=str(message),
    )


def original_reference_texture_preview_error_state(
    state: MutableMapping[str, object],
    *,
    request_current: bool,
    message: object,
) -> OriginalReferenceTexturePreviewErrorState:
    if not request_current:
        return OriginalReferenceTexturePreviewErrorState(
            handled=False,
            message="",
            performance=OriginalReferenceTexturePreviewPerformance(summary=""),
        )
    original_reference_texture_preview_mark_failed(state, message)
    return OriginalReferenceTexturePreviewErrorState(
        handled=True,
        message=original_reference_texture_preview_failed_message(message),
        performance=original_reference_texture_preview_resolve_failed_performance(message),
    )


def original_reference_texture_preview_exception_state(
    state: MutableMapping[str, object],
    message: object,
) -> OriginalReferenceTexturePreviewExceptionState:
    original_reference_texture_preview_mark_failed(
        state,
        message,
        clear_loading=False,
        clear_native_package=False,
    )
    return OriginalReferenceTexturePreviewExceptionState(
        message=original_reference_texture_preview_failed_message(message),
        performance=original_reference_texture_preview_resolve_failed_performance(message),
    )


__all__ = [
    "OriginalReferenceTexturePreviewPerformance",
    "OriginalReferenceTexturePreviewErrorState",
    "OriginalReferenceTexturePreviewExceptionState",
    "OriginalReferenceTexturePreviewLoadStartState",
    "OriginalReferenceTexturePreviewReadyResultState",
    "OriginalReferenceTexturePreviewReadyState",
    "OriginalTexturePreviewToggleState",
    "original_texture_preview_enabled",
    "original_texture_preview_checkbox_tooltip",
    "original_texture_preview_control_text",
    "original_texture_preview_help_text",
    "original_texture_preview_initial_state",
    "original_texture_preview_material_preview_enabled",
    "original_texture_preview_note_text",
    "original_texture_preview_note_tooltip",
    "original_texture_preview_set_enabled",
    "original_texture_preview_toggle_state",
    "original_reference_texture_preview_archive_parity_state",
    "original_reference_texture_preview_clear_failure",
    "original_reference_texture_preview_clear_loading",
    "original_reference_texture_preview_clear_native_package_path",
    "original_reference_texture_preview_can_start_load",
    "original_reference_texture_preview_error_state",
    "original_reference_texture_preview_exception_state",
    "original_reference_texture_preview_failed_message",
    "original_reference_texture_preview_initial_state",
    "original_reference_texture_preview_loaded_detail",
    "original_reference_texture_preview_loaded_performance",
    "original_reference_texture_preview_loaded_progress_message",
    "original_reference_texture_preview_load_start_state",
    "original_reference_texture_preview_loading_message",
    "original_reference_texture_preview_loading_performance",
    "original_reference_texture_preview_mark_failed",
    "original_reference_texture_preview_mark_loaded",
    "original_reference_texture_preview_mark_loading",
    "original_reference_texture_preview_manifest_performance",
    "original_reference_texture_preview_ready_result_state",
    "original_reference_texture_preview_ready_state",
    "original_reference_texture_preview_readiness",
    "original_reference_texture_preview_required",
    "original_reference_texture_preview_resolve_failed_performance",
    "original_reference_texture_preview_resolving_progress_message",
    "original_reference_texture_preview_set_native_package_path",
]
