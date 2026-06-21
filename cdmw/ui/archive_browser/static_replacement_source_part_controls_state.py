"""Selected source-part control state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cdmw.ui.archive_browser.static_replacement_source_part_selection_state import (
    selected_source_part_name_text,
    selected_source_part_target_text,
)


@dataclass(frozen=True, slots=True)
class SourcePartControlState:
    has_source: bool
    source_combo_enabled: bool
    target_choice_available: bool
    mapped_target_available: bool
    fit_part_enabled: bool


@dataclass(frozen=True, slots=True)
class SourcePartCopiedTextureControlsState:
    visible: bool
    use_copied_enabled: bool
    use_route_enabled: bool
    remove_enabled: bool


@dataclass(frozen=True, slots=True)
class SourcePartCopiedTextureActionState:
    available: bool
    source_index: int
    undo_label: str
    disable_copied_texture: bool
    remove_intent: bool
    mark_dirty: bool
    queue_preview: bool


@dataclass(frozen=True, slots=True)
class SourcePartCheckToggleState:
    available: bool
    source_index: int
    enabled: bool
    undo_action: str
    refresh_selected_controls: bool
    apply_pending: bool


@dataclass(frozen=True, slots=True)
class SourcePartTargetButtonState:
    replace_enabled: bool
    add_enabled: bool
    remove_enabled: bool


@dataclass(frozen=True, slots=True)
class SourcePartSourceComboSelectionState:
    source_index: int
    select_existing_source: bool
    clear_selection: bool


@dataclass(frozen=True, slots=True)
class SourcePartTargetComboSelectionState:
    target_index: int
    button_state: SourcePartTargetButtonState


@dataclass(frozen=True, slots=True)
class SourcePartOutputActionState:
    available: bool
    target_indices: tuple[int, ...]
    source_checked: bool
    part_enabled_checked: bool
    undo_action: str
    apply_pending: bool


@dataclass(frozen=True, slots=True)
class SourcePartControlLoadState:
    has_source: bool
    control_state: SourcePartControlState
    name_text: str
    target_text: str
    source_combo_value: int
    enabled_checked: bool
    role_value: str
    target_choice: int
    transform_values: tuple[float, float, float, float, float, float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class SourcePartGlowColorControlsState:
    enabled: bool
    color_text: str
    style_sheet: str


def source_part_control_state(
    *,
    source_index: int,
    has_replacement_sources: bool,
    target_choice: object,
    mapped_target_indices: Sequence[int] = (),
    selected_target_index: int = -1,
) -> SourcePartControlState:
    has_source = int(source_index) >= 0
    try:
        has_target_choice = int(target_choice) >= 0
    except (TypeError, ValueError):
        has_target_choice = False
    try:
        selected_target = int(selected_target_index)
    except (TypeError, ValueError):
        selected_target = -1
    return SourcePartControlState(
        has_source=has_source,
        source_combo_enabled=bool(has_replacement_sources),
        target_choice_available=bool(has_source and has_target_choice),
        mapped_target_available=bool(has_source and tuple(mapped_target_indices or ())),
        fit_part_enabled=bool(has_source and selected_target >= 0),
    )


def source_part_target_choice(selected_target_index: int, mapped_target_indices: Sequence[int]) -> int:
    try:
        selected_target = int(selected_target_index)
    except (TypeError, ValueError):
        selected_target = -1
    normalized_targets: list[int] = []
    for raw_index in tuple(mapped_target_indices or ()):
        try:
            normalized_targets.append(int(raw_index))
        except (TypeError, ValueError):
            continue
    mapped_targets = tuple(normalized_targets)
    if selected_target in mapped_targets:
        return selected_target
    if mapped_targets:
        return int(mapped_targets[0])
    return selected_target


def source_part_selected_target_index(raw_target_index: object) -> int:
    try:
        return int(raw_target_index)
    except (TypeError, ValueError):
        return -1


def source_part_source_combo_selection_state(
    raw_source_index: object,
    *,
    available_source_indices: Sequence[int],
) -> SourcePartSourceComboSelectionState:
    try:
        source_index = int(raw_source_index)
    except (TypeError, ValueError):
        source_index = -1
    available_indices: set[int] = set()
    for raw_index in tuple(available_source_indices or ()):
        try:
            available_indices.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    select_existing = source_index in available_indices
    return SourcePartSourceComboSelectionState(
        source_index=source_index,
        select_existing_source=select_existing,
        clear_selection=not select_existing,
    )


def source_part_target_combo_selection_state(
    raw_target_index: object,
    *,
    source_index: object,
    mapped_target_indices: Sequence[int] = (),
) -> SourcePartTargetComboSelectionState:
    target_index = source_part_selected_target_index(raw_target_index)
    return SourcePartTargetComboSelectionState(
        target_index=target_index,
        button_state=source_part_target_button_state(
            source_index=source_index,
            target_index=target_index,
            mapped_target_indices=mapped_target_indices,
        ),
    )


def _float_at(values: object, index: int, default: float) -> float:
    try:
        sequence = tuple(values or ())
        return float(sequence[index])
    except (TypeError, ValueError, IndexError):
        return float(default)


def _float_value(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int_value(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def source_part_control_load_state(
    *,
    source_index: int,
    source_count: int,
    has_replacement_sources: bool,
    current_target_choice: object,
    mapped_target_indices: Sequence[int],
    selected_target_index: int,
    name_placeholder: str,
    target_placeholder: str,
    source_label: str = "",
    target_summary: str = "",
    role_value: str = "",
    multi_selected_count: int = 1,
    adjustment: object | None = None,
) -> SourcePartControlLoadState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    normalized_source_count = _int_value(source_count, 0)
    normalized_multi_count = max(1, _int_value(multi_selected_count, 1))
    has_source = 0 <= normalized_source_index < normalized_source_count
    control_state = source_part_control_state(
        source_index=normalized_source_index if has_source else -1,
        has_replacement_sources=has_replacement_sources,
        target_choice=current_target_choice,
        mapped_target_indices=mapped_target_indices,
        selected_target_index=selected_target_index,
    )
    if not has_source or adjustment is None:
        return SourcePartControlLoadState(
            has_source=False,
            control_state=control_state,
            name_text=str(name_placeholder),
            target_text=str(target_placeholder),
            source_combo_value=-1,
            enabled_checked=True,
            role_value="",
            target_choice=-1,
            transform_values=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0),
        )
    transform_values = (
        _float_at(getattr(adjustment, "offset_xyz", ()), 0, 0.0),
        _float_at(getattr(adjustment, "offset_xyz", ()), 1, 0.0),
        _float_at(getattr(adjustment, "offset_xyz", ()), 2, 0.0),
        _float_at(getattr(adjustment, "rotate_xyz_degrees", ()), 0, 0.0),
        _float_at(getattr(adjustment, "rotate_xyz_degrees", ()), 1, 0.0),
        _float_at(getattr(adjustment, "rotate_xyz_degrees", ()), 2, 0.0),
        _float_at(getattr(adjustment, "scale_xyz", ()), 0, 1.0),
        _float_at(getattr(adjustment, "scale_xyz", ()), 1, 1.0),
        _float_at(getattr(adjustment, "scale_xyz", ()), 2, 1.0),
        _float_value(getattr(adjustment, "uniform_scale", 1.0) or 1.0, 1.0),
    )
    return SourcePartControlLoadState(
        has_source=True,
        control_state=control_state,
        name_text=selected_source_part_name_text(
            normalized_source_index,
            source_label,
            multi_selected_count=normalized_multi_count,
        ),
        target_text=selected_source_part_target_text(target_summary, multi_selected_count=normalized_multi_count),
        source_combo_value=normalized_source_index,
        enabled_checked=bool(getattr(adjustment, "enabled", True)),
        role_value=str(role_value or ""),
        target_choice=source_part_target_choice(selected_target_index, mapped_target_indices),
        transform_values=transform_values,
    )


def source_part_output_action_state(
    *,
    action: str,
    source_index: int,
    selected_source_indices: Sequence[int],
) -> SourcePartOutputActionState:
    normalized_action = str(action or "").strip().lower()
    target_indices = source_part_normalized_target_indices(source_index, selected_source_indices)
    available = bool(target_indices)
    if normalized_action == "remove":
        return SourcePartOutputActionState(
            available=available,
            target_indices=target_indices,
            source_checked=False,
            part_enabled_checked=False,
            undo_action="remove",
            apply_pending=available,
        )
    return SourcePartOutputActionState(
        available=available,
        target_indices=target_indices,
        source_checked=True,
        part_enabled_checked=True,
        undo_action="reset",
        apply_pending=False,
    )


def source_part_check_toggle_state(
    *,
    source_index: object,
    column: object,
    guard_active: bool,
    checked: bool,
    selected_source_index: object,
) -> SourcePartCheckToggleState:
    try:
        normalized_column = int(column)
    except (TypeError, ValueError):
        normalized_column = -1
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    try:
        normalized_selected_index = int(selected_source_index)
    except (TypeError, ValueError):
        normalized_selected_index = -1
    available = bool(not guard_active and normalized_column == 0 and normalized_source_index >= 0)
    return SourcePartCheckToggleState(
        available=available,
        source_index=normalized_source_index if available else -1,
        enabled=bool(checked),
        undo_action="toggle",
        refresh_selected_controls=bool(available and normalized_source_index == normalized_selected_index),
        apply_pending=available,
    )


def source_part_copied_texture_action_state(
    *,
    action: str,
    source_index: object,
    copied_source_indices: Sequence[int],
) -> SourcePartCopiedTextureActionState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    copied_indices: set[int] = set()
    for raw_index in tuple(copied_source_indices or ()):
        try:
            copied_indices.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    normalized_action = str(action or "").strip().lower()
    available = normalized_source_index >= 0 and normalized_source_index in copied_indices
    undo_labels = {
        "use_copied": "Use copied original texture",
        "use_route": "Use route source texture",
        "remove": "Remove copied source texture",
    }
    return SourcePartCopiedTextureActionState(
        available=available,
        source_index=normalized_source_index if available else -1,
        undo_label=undo_labels.get(normalized_action, ""),
        disable_copied_texture=normalized_action == "use_route",
        remove_intent=normalized_action == "remove",
        mark_dirty=available and normalized_action in undo_labels,
        queue_preview=available and normalized_action in undo_labels,
    )


def source_part_copied_texture_controls_state(
    *,
    has_rows: bool,
    disabled: bool,
) -> SourcePartCopiedTextureControlsState:
    return SourcePartCopiedTextureControlsState(
        visible=bool(has_rows),
        use_copied_enabled=bool(has_rows and disabled),
        use_route_enabled=bool(has_rows and not disabled),
        remove_enabled=bool(has_rows),
    )


def source_part_copied_texture_status_text(
    *,
    has_rows: bool,
    disabled: bool = False,
    copied_badge: str = "",
) -> str:
    if not has_rows:
        return "Texture: -"
    if disabled:
        return "Texture: Route source"
    return f"Texture: {str(copied_badge or '').strip()}"


def source_part_glow_color_button_text(color: object, *, enabled: bool) -> str:
    return str(color) if enabled else "Pick"


def source_part_glow_rgb(values: Sequence[object]) -> tuple[int, int, int]:
    normalized: list[int] = []
    for raw_value in tuple(values or ())[:3]:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 0
        normalized.append(max(0, min(255, value)))
    while len(normalized) < 3:
        normalized.append(0)
    return normalized[0], normalized[1], normalized[2]


def source_part_glow_color_controls_state(
    *,
    rgb: Sequence[object],
    complete_external_swap_enabled: bool,
    checked: bool,
    checkbox_enabled: bool,
) -> SourcePartGlowColorControlsState:
    normalized_rgb = source_part_glow_rgb(rgb)
    color = f"#{normalized_rgb[0]:02X}{normalized_rgb[1]:02X}{normalized_rgb[2]:02X}"
    enabled = bool(complete_external_swap_enabled and checked and checkbox_enabled)
    return SourcePartGlowColorControlsState(
        enabled=enabled,
        color_text=source_part_glow_color_button_text(color, enabled=enabled),
        style_sheet=f"QPushButton {{ background-color: {color}; color: #0d1117; }}" if enabled else "",
    )


def source_part_normalized_target_indices(
    source_index: int,
    selected_source_indices: Sequence[int],
) -> tuple[int, ...]:
    try:
        selected_source_index = int(source_index)
    except (TypeError, ValueError):
        selected_source_index = -1
    normalized: list[int] = []
    if selected_source_index >= 0:
        normalized.append(selected_source_index)
    for raw_target_index in tuple(selected_source_indices or ()):
        try:
            target_source_index = int(raw_target_index)
        except (TypeError, ValueError):
            continue
        if target_source_index >= 0 and target_source_index not in normalized:
            normalized.append(target_source_index)
    return tuple(normalized)


def source_part_target_button_state(
    *,
    source_index: int,
    target_index: int,
    mapped_target_indices: Sequence[int] = (),
) -> SourcePartTargetButtonState:
    try:
        source_available = int(source_index) >= 0
    except (TypeError, ValueError):
        source_available = False
    try:
        target_available = int(target_index) >= 0
    except (TypeError, ValueError):
        target_available = False
    return SourcePartTargetButtonState(
        replace_enabled=bool(source_available and target_available),
        add_enabled=bool(source_available and target_available),
        remove_enabled=bool(source_available and tuple(mapped_target_indices or ())),
    )


__all__ = [
    "SourcePartControlState",
    "SourcePartCheckToggleState",
    "SourcePartCopiedTextureControlsState",
    "SourcePartCopiedTextureActionState",
    "SourcePartControlLoadState",
    "SourcePartGlowColorControlsState",
    "SourcePartOutputActionState",
    "SourcePartSourceComboSelectionState",
    "SourcePartTargetButtonState",
    "SourcePartTargetComboSelectionState",
    "source_part_control_state",
    "source_part_check_toggle_state",
    "source_part_control_load_state",
    "source_part_copied_texture_action_state",
    "source_part_copied_texture_controls_state",
    "source_part_copied_texture_status_text",
    "source_part_glow_color_controls_state",
    "source_part_glow_color_button_text",
    "source_part_glow_rgb",
    "source_part_normalized_target_indices",
    "source_part_output_action_state",
    "source_part_selected_target_index",
    "source_part_source_combo_selection_state",
    "source_part_target_button_state",
    "source_part_target_choice",
    "source_part_target_combo_selection_state",
]
