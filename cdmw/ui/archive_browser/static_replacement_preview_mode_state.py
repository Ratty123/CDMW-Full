"""Static replacement preview-mode state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass

_DEFAULT_MODE = "side_by_side"


@dataclass(frozen=True, slots=True)
class AlignmentPreviewRendererRoute:
    action: str
    should_report_unavailable: bool
    should_show_d3d11_preview: bool
    should_reset_d3d11_state: bool
    should_stop_d3d11_worker: bool
    should_invalidate_d3d11_cache: bool
    should_stop_d3d11_process: bool
    should_queue_selection_preview_refresh: bool
    should_sync_highlights: bool
    should_apply_static_preview_mode: bool


@dataclass(frozen=True, slots=True)
class AlignmentPreviewModeRoute:
    mode: str
    d3d11_active: bool
    should_set_live_d3d11_mode: bool
    should_mark_d3d11_rebuild: bool
    should_show_d3d11_preview: bool
    static_stack_index: int
    should_restore_view_state: bool
    should_replay_fast_transform: bool
    should_queue_static_preview_refresh: bool


def alignment_preview_mode_initial_state(mode: object) -> dict[str, str]:
    return {"current": str(mode or _DEFAULT_MODE)}


def alignment_preview_mode_record(
    state: MutableMapping[str, object],
    mode: object,
) -> tuple[str, str]:
    previous = str(state.get("current", _DEFAULT_MODE) or _DEFAULT_MODE)
    current = str(mode or _DEFAULT_MODE)
    state["current"] = current
    return previous, current


def alignment_preview_renderer_route(
    renderer_value: object,
    *,
    d3d11_available: bool,
    d3d11_active: bool,
) -> AlignmentPreviewRendererRoute:
    wants_d3d11 = str(renderer_value or "").strip().lower() == "d3d11"
    if wants_d3d11 and not bool(d3d11_available):
        return AlignmentPreviewRendererRoute(
            action="unavailable",
            should_report_unavailable=True,
            should_show_d3d11_preview=False,
            should_reset_d3d11_state=True,
            should_stop_d3d11_worker=True,
            should_invalidate_d3d11_cache=True,
            should_stop_d3d11_process=True,
            should_queue_selection_preview_refresh=False,
            should_sync_highlights=False,
            should_apply_static_preview_mode=True,
        )
    if bool(d3d11_active):
        return AlignmentPreviewRendererRoute(
            action="d3d11",
            should_report_unavailable=False,
            should_show_d3d11_preview=True,
            should_reset_d3d11_state=False,
            should_stop_d3d11_worker=False,
            should_invalidate_d3d11_cache=False,
            should_stop_d3d11_process=False,
            should_queue_selection_preview_refresh=True,
            should_sync_highlights=True,
            should_apply_static_preview_mode=False,
        )
    return AlignmentPreviewRendererRoute(
        action="static",
        should_report_unavailable=False,
        should_show_d3d11_preview=False,
        should_reset_d3d11_state=True,
        should_stop_d3d11_worker=True,
        should_invalidate_d3d11_cache=True,
        should_stop_d3d11_process=True,
        should_queue_selection_preview_refresh=False,
        should_sync_highlights=False,
        should_apply_static_preview_mode=True,
    )


def alignment_preview_mode_route(
    mode: object,
    *,
    d3d11_active: bool,
    needs_static_refresh: bool,
) -> AlignmentPreviewModeRoute:
    normalized = str(mode or _DEFAULT_MODE)
    if bool(d3d11_active):
        return AlignmentPreviewModeRoute(
            mode=normalized,
            d3d11_active=True,
            should_set_live_d3d11_mode=not bool(needs_static_refresh),
            should_mark_d3d11_rebuild=bool(needs_static_refresh),
            should_show_d3d11_preview=True,
            static_stack_index=0,
            should_restore_view_state=True,
            should_replay_fast_transform=True,
            should_queue_static_preview_refresh=bool(needs_static_refresh),
        )
    return AlignmentPreviewModeRoute(
        mode=normalized,
        d3d11_active=False,
        should_set_live_d3d11_mode=False,
        should_mark_d3d11_rebuild=False,
        should_show_d3d11_preview=False,
        static_stack_index={"side_by_side": 0, "overlay": 1, "replacement_only": 2}.get(normalized, 0),
        should_restore_view_state=True,
        should_replay_fast_transform=False,
        should_queue_static_preview_refresh=bool(needs_static_refresh),
    )


__all__ = [
    "AlignmentPreviewModeRoute",
    "AlignmentPreviewRendererRoute",
    "alignment_preview_mode_initial_state",
    "alignment_preview_mode_record",
    "alignment_preview_mode_route",
    "alignment_preview_renderer_route",
]
