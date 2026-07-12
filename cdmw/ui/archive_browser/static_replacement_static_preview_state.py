"""Static preview refresh route and prepared-cache state helpers."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass

from cdmw.ui.archive_browser.static_replacement_preview_cache import store_static_preview_cache_entry


@dataclass(frozen=True, slots=True)
class StaticPreviewRefreshRouteState:
    mesh_edit_direct_source_preview: bool
    replacement_only_direct_source_preview: bool
    source_owned_direct_source_preview: bool
    require_original_reference: bool
    can_build_source_geometry: bool

    def waits_for_original_reference(self, *, ready: bool) -> bool:
        return bool(self.require_original_reference and not ready and not self.can_build_source_geometry)


@dataclass(frozen=True, slots=True)
class StaticPreviewWidgetModelAction:
    preserve_mesh_edit_cache: bool
    use_prepared_cache: bool
    prepared_key: str
    cache_lookup_allowed: bool


@dataclass(frozen=True, slots=True)
class StaticPreviewWidgetModeState:
    update_side_by_side: bool
    update_replacement_only: bool
    update_overlay: bool


@dataclass(frozen=True, slots=True)
class StaticPreviewPreparedCacheResult:
    prepared_model: object
    prepared_preview: object
    prepare_elapsed_ms: float
    cache_hit: bool


def static_preview_refresh_route_state(
    *,
    active_preview_mode: str,
    mesh_edit_enabled: bool,
    mesh_edit_tab_active: bool,
    replacement_mesh_available: bool,
    interactive_preview: bool,
    complete_external_swap_enabled: bool,
    needs_original_material_preview: bool,
    preview_controls_ready: bool,
    original_mesh_available: bool,
) -> StaticPreviewRefreshRouteState:
    mesh_edit_direct_source_preview = False
    replacement_available = bool(replacement_mesh_available)
    replacement_only_direct_source_preview = False
    source_owned_direct_source_preview = bool(
        replacement_available
        and not needs_original_material_preview
    )
    require_original_reference = bool(not mesh_edit_direct_source_preview or needs_original_material_preview)
    can_build_source_geometry = bool(
        preview_controls_ready and original_mesh_available and replacement_available
    )
    return StaticPreviewRefreshRouteState(
        mesh_edit_direct_source_preview=mesh_edit_direct_source_preview,
        replacement_only_direct_source_preview=replacement_only_direct_source_preview,
        source_owned_direct_source_preview=source_owned_direct_source_preview,
        require_original_reference=require_original_reference,
        can_build_source_geometry=can_build_source_geometry,
    )


def static_preview_widget_mode_state(active_preview_mode: object) -> StaticPreviewWidgetModeState:
    mode = str(active_preview_mode or "side_by_side")
    return StaticPreviewWidgetModeState(
        update_side_by_side=mode == "side_by_side",
        update_replacement_only=mode == "replacement_only",
        update_overlay=mode == "overlay",
    )


def static_preview_widget_model_action(
    *,
    live_mesh_edit: bool,
    prepared_key: str,
) -> StaticPreviewWidgetModelAction:
    key = str(prepared_key or "")
    return StaticPreviewWidgetModelAction(
        preserve_mesh_edit_cache=bool(live_mesh_edit),
        use_prepared_cache=bool(key) and not bool(live_mesh_edit),
        prepared_key=key,
        cache_lookup_allowed=bool(key) and not bool(live_mesh_edit),
    )


def static_preview_prepared_cache_result(
    cache: MutableMapping[str, object],
    model: object,
    *,
    prepared_key: str,
    prepare_model_preview: Callable[[object], tuple[object, object]],
    cache_limit: int = 8,
) -> StaticPreviewPreparedCacheResult:
    key = str(prepared_key or "")
    cached_prepared = cache.get(key) if key else None
    if cached_prepared is not None:
        prepared_model, prepared_preview = tuple(cached_prepared)[:2]
        return StaticPreviewPreparedCacheResult(
            prepared_model=prepared_model,
            prepared_preview=prepared_preview,
            prepare_elapsed_ms=0.0,
            cache_hit=True,
        )
    prepare_started = time.perf_counter()
    prepared_model, prepared_preview = prepare_model_preview(model)
    prepare_elapsed_ms = (time.perf_counter() - prepare_started) * 1000.0
    if key:
        store_static_preview_cache_entry(
            cache,
            key,
            (prepared_model, prepared_preview),
            cache_limit=cache_limit,
        )
    return StaticPreviewPreparedCacheResult(
        prepared_model=prepared_model,
        prepared_preview=prepared_preview,
        prepare_elapsed_ms=prepare_elapsed_ms,
        cache_hit=False,
    )


def static_preview_upload_elapsed_ms(widgets: Iterable[object]) -> float:
    values: list[float] = []
    for widget in tuple(widgets or ()):
        try:
            values.append(float(getattr(widget, "_last_gl_upload_ms", 0.0) or 0.0))
        except (TypeError, ValueError):
            values.append(0.0)
    return max(values, default=0.0)


__all__ = [
    "StaticPreviewPreparedCacheResult",
    "StaticPreviewRefreshRouteState",
    "StaticPreviewWidgetModeState",
    "StaticPreviewWidgetModelAction",
    "static_preview_prepared_cache_result",
    "static_preview_refresh_route_state",
    "static_preview_upload_elapsed_ms",
    "static_preview_widget_mode_state",
    "static_preview_widget_model_action",
]
