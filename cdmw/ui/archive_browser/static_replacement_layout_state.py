"""Static replacement dialog layout mode state helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AlignmentDialogResponsiveLayout:
    mode: str
    main_orientation: str
    preview_orientation: str
    main_handle_width: int
    controls_policy: str
    content_policy: str
    controls_min_width: int
    content_min_width: int
    controls_max_width: int
    content_max_width: int
    preview_min_width: int
    main_stretch: tuple[int, int]
    main_sizes: tuple[int, int] | None
    preview_sizes: tuple[int, int] | None


@dataclass(frozen=True)
class AlignmentDialogFitSize:
    width: int
    height: int


@dataclass(frozen=True)
class AlignmentDialogFrameOrigin:
    left: int
    top: int


def alignment_dialog_layout_initial_state() -> dict[str, str]:
    return {"mode": ""}


def alignment_dialog_layout_embedded_resize_needed(
    state: MutableMapping[str, object],
    *,
    force_sizes: bool,
) -> bool:
    return bool(force_sizes or str(state.get("mode") or "") != "embedded")


def alignment_dialog_layout_set_mode(
    state: MutableMapping[str, object],
    mode: str,
) -> bool:
    normalized = str(mode or "")
    changed = str(state.get("mode") or "") != normalized
    state["mode"] = normalized
    return changed


def alignment_dialog_responsive_layout(
    state: MutableMapping[str, object],
    *,
    width: int,
    height: int,
    embedded: bool,
    force_sizes: bool,
    mesh_edit_tools_active: bool,
    alignment_control_min_width: int,
    alignment_control_content_min_width: int,
    alignment_preview_min_width: int,
    mesh_edit_control_min_width: int,
    mesh_edit_control_content_min_width: int,
    mesh_edit_control_max_width: int,
) -> AlignmentDialogResponsiveLayout:
    normalized_width = max(1, int(width))
    normalized_height = max(1, int(height))
    if bool(embedded):
        resize_needed = alignment_dialog_layout_embedded_resize_needed(
            state,
            force_sizes=force_sizes,
        )
        control_width = max(380, min(620, int(normalized_width * 0.40)))
        main_sizes = (
            control_width,
            max(220, normalized_width - control_width),
        ) if resize_needed else None
        preview_width = max(1, normalized_width - control_width)
        preview_sizes = (
            max(220, int(preview_width * 0.52)),
            max(220, int(preview_width * 0.44)),
        ) if resize_needed else None
        alignment_dialog_layout_set_mode(state, "embedded")
        return AlignmentDialogResponsiveLayout(
            mode="embedded",
            main_orientation="horizontal",
            preview_orientation="horizontal",
            main_handle_width=8,
            controls_policy="preferred",
            content_policy="preferred",
            controls_min_width=260,
            content_min_width=0,
            controls_max_width=16777215,
            content_max_width=16777215,
            preview_min_width=220,
            main_stretch=(0, 1),
            main_sizes=main_sizes,
            preview_sizes=preview_sizes,
        )
    compact = normalized_width < 1680
    mode = "compact" if compact else "wide"
    mode_changed = alignment_dialog_layout_set_mode(state, mode)
    should_resize = bool(force_sizes or mode_changed)
    if compact:
        return AlignmentDialogResponsiveLayout(
            mode="compact",
            main_orientation="vertical",
            preview_orientation="horizontal",
            main_handle_width=8,
            controls_policy="minimum_expanding",
            content_policy="minimum_expanding",
            controls_min_width=0,
            content_min_width=0,
            controls_max_width=16777215,
            content_max_width=16777215,
            preview_min_width=0,
            main_stretch=(1, 1),
            main_sizes=(
                max(360, int(normalized_height * 0.56)),
                max(280, int(normalized_height * 0.36)),
            ) if should_resize else None,
            preview_sizes=(
                max(260, int(normalized_width * 0.52)),
                max(260, int(normalized_width * 0.42)),
            ) if should_resize else None,
        )
    active_control_min_width = (
        int(mesh_edit_control_min_width)
        if bool(mesh_edit_tools_active)
        else int(alignment_control_min_width)
    )
    active_content_min_width = (
        int(mesh_edit_control_content_min_width)
        if bool(mesh_edit_tools_active)
        else int(alignment_control_content_min_width)
    )
    if bool(mesh_edit_tools_active):
        control_width = max(
            int(mesh_edit_control_min_width),
            min(int(mesh_edit_control_max_width), int(normalized_width * 0.24)),
        )
    else:
        control_width = max(760, min(1120, int(normalized_width * 0.48)))
    preview_width = max(1, normalized_width - control_width)
    return AlignmentDialogResponsiveLayout(
        mode="wide",
        main_orientation="horizontal",
        preview_orientation="horizontal",
        main_handle_width=10,
        controls_policy="fixed" if bool(mesh_edit_tools_active) else "minimum_expanding",
        content_policy="fixed" if bool(mesh_edit_tools_active) else "minimum_expanding",
        controls_min_width=active_control_min_width,
        content_min_width=active_content_min_width,
        controls_max_width=int(mesh_edit_control_max_width) if bool(mesh_edit_tools_active) else 16777215,
        content_max_width=16777215,
        preview_min_width=int(alignment_preview_min_width),
        main_stretch=(1, 1),
        main_sizes=(control_width, max(760, normalized_width - control_width)) if should_resize else None,
        preview_sizes=(
            max(360, int(preview_width * 0.52)),
            max(360, int(preview_width * 0.44)),
        ) if should_resize else None,
    )


def alignment_dialog_fit_size(
    *,
    available_width: int,
    available_height: int,
) -> AlignmentDialogFitSize:
    normalized_width = max(1, int(available_width))
    normalized_height = max(1, int(available_height))
    inner_width = max(640, normalized_width - 24)
    inner_height = max(420, normalized_height - 24)
    return AlignmentDialogFitSize(
        width=min(1720, max(760, int(float(normalized_width) * 0.92)), inner_width),
        height=min(900, max(560, int(float(normalized_height) * 0.88)), inner_height),
    )


def alignment_dialog_frame_origin(
    *,
    available_left: int,
    available_top: int,
    available_right: int,
    available_bottom: int,
    frame_left: int,
    frame_top: int,
    frame_width: int,
    frame_height: int,
) -> AlignmentDialogFrameOrigin:
    return AlignmentDialogFrameOrigin(
        left=max(int(available_left), min(int(frame_left), int(available_right) - int(frame_width) + 1)),
        top=max(int(available_top), min(int(frame_top), int(available_bottom) - int(frame_height) + 1)),
    )


__all__ = [
    "AlignmentDialogFitSize",
    "AlignmentDialogFrameOrigin",
    "AlignmentDialogResponsiveLayout",
    "alignment_dialog_fit_size",
    "alignment_dialog_frame_origin",
    "alignment_dialog_layout_embedded_resize_needed",
    "alignment_dialog_layout_initial_state",
    "alignment_dialog_layout_set_mode",
    "alignment_dialog_responsive_layout",
]
