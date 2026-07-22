"""Selected source-part adjustment state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from cdmw.ui.archive_browser.static_replacement_source_part_controls_state import (
    source_part_normalized_target_indices,
)


@dataclass(frozen=True, slots=True)
class SourcePartAdjustmentApplyState:
    available: bool
    changed: bool
    enabled_changed: bool
    geometry_changed: bool
    target_indices: tuple[int, ...]
    enabled: bool
    offset_xyz: tuple[float, float, float]
    rotate_xyz_degrees: tuple[float, float, float]
    scale_xyz: tuple[float, float, float]
    uniform_scale: float


@dataclass(frozen=True, slots=True)
class SourcePartGlowColorActionState:
    undo_action: str
    refresh_plan: bool
    force_plan: bool
    refresh_preview: bool
    refresh_reason: str


@dataclass(frozen=True, slots=True)
class SourcePartGlowEmissiveUpdateState:
    source_index: int
    emissive_color_rgb: tuple[int, ...]
    emissive_strength: float | None


@dataclass(frozen=True, slots=True)
class SourcePartRoleActionState:
    available: bool
    source_index: int
    normalized_role: str
    undo_label: str
    refresh_plan: bool
    force_plan: bool
    refresh_preview: bool
    refresh_reason: str


@dataclass(frozen=True, slots=True)
class SourcePartRoleExportFlushState:
    source_index: int
    normalized_role: str
    material_role_changed: bool
    clear_emissive_color: bool

    @property
    def changed(self) -> bool:
        return self.material_role_changed or self.clear_emissive_color


@dataclass(frozen=True, slots=True)
class SourcePartRoleOverrideState:
    source_index: int
    normalized_role: str
    store_override: bool
    emissive_color_rgb: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourcePartMaterialAdjustmentState:
    available: bool
    changed: bool
    target_indices: tuple[int, ...]
    brightness: float
    contrast: float
    saturation: float
    gamma: float
    tint_rgb: tuple[int, int, int]


def _source_part_rgb(values: Sequence[object]) -> tuple[int, int, int]:
    normalized_values: list[int] = []
    for raw_value in tuple(values or ())[:3]:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 0
        normalized_values.append(max(0, min(255, value)))
    while len(normalized_values) < 3:
        normalized_values.append(0)
    return normalized_values[0], normalized_values[1], normalized_values[2]


def _float3(values: Sequence[object], default: float = 0.0) -> tuple[float, float, float]:
    normalized: list[float] = []
    for raw_value in tuple(values or ())[:3]:
        try:
            normalized.append(float(raw_value))
        except (TypeError, ValueError):
            normalized.append(float(default))
    while len(normalized) < 3:
        normalized.append(float(default))
    return normalized[0], normalized[1], normalized[2]


def _source_part_clamped_float(value: object, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = float(default)
    return max(float(minimum), min(float(maximum), number))


def source_part_adjustment_apply_state(
    source_part_adjustments: Mapping[int, object],
    *,
    source_index: object,
    selected_source_indices: Sequence[int],
    enabled: bool,
    offset_xyz: Sequence[object],
    rotate_xyz_degrees: Sequence[object],
    scale_xyz: Sequence[object],
    uniform_scale: object,
    default_adjustment: Callable[[int], object],
) -> SourcePartAdjustmentApplyState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    if normalized_source_index < 0:
        return SourcePartAdjustmentApplyState(
            available=False,
            changed=False,
            enabled_changed=False,
            geometry_changed=False,
            target_indices=(),
            enabled=bool(enabled),
            offset_xyz=_float3(offset_xyz),
            rotate_xyz_degrees=_float3(rotate_xyz_degrees),
            scale_xyz=_float3(scale_xyz, default=1.0),
            uniform_scale=1.0,
        )
    try:
        normalized_uniform = float(uniform_scale)
    except (TypeError, ValueError):
        normalized_uniform = 1.0
    target_indices = source_part_normalized_target_indices(normalized_source_index, selected_source_indices)
    normalized_offset = _float3(offset_xyz)
    normalized_rotation = _float3(rotate_xyz_degrees)
    normalized_scale = _float3(scale_xyz, default=1.0)
    changed = source_part_adjustment_values_changed(
        source_part_adjustments,
        target_indices,
        enabled=enabled,
        offset_xyz=normalized_offset,
        rotate_xyz_degrees=normalized_rotation,
        scale_xyz=normalized_scale,
        uniform_scale=normalized_uniform,
        default_adjustment=default_adjustment,
    )
    enabled_changed = False
    geometry_changed = False
    for target_source_index in target_indices:
        adjustment = source_part_adjustments.get(
            target_source_index,
            default_adjustment(target_source_index),
        )
        if bool(getattr(adjustment, "enabled", True)) != bool(enabled):
            enabled_changed = True
        if (
            tuple(float(value) for value in getattr(adjustment, "offset_xyz", ())) != normalized_offset
            or tuple(float(value) for value in getattr(adjustment, "rotate_xyz_degrees", ())) != normalized_rotation
            or tuple(float(value) for value in getattr(adjustment, "scale_xyz", ())) != normalized_scale
            or float(getattr(adjustment, "uniform_scale", 1.0)) != normalized_uniform
        ):
            geometry_changed = True
    return SourcePartAdjustmentApplyState(
        available=bool(target_indices),
        changed=changed,
        enabled_changed=enabled_changed,
        geometry_changed=geometry_changed,
        target_indices=target_indices,
        enabled=bool(enabled),
        offset_xyz=normalized_offset,
        rotate_xyz_degrees=normalized_rotation,
        scale_xyz=normalized_scale,
        uniform_scale=normalized_uniform,
    )


def source_part_adjustment_values_changed(
    source_part_adjustments: Mapping[int, object],
    target_indices: Sequence[int],
    *,
    enabled: bool,
    offset_xyz: Sequence[float],
    rotate_xyz_degrees: Sequence[float],
    scale_xyz: Sequence[float],
    uniform_scale: float,
    default_adjustment: Callable[[int], object],
) -> bool:
    expected_offset = tuple(float(value) for value in tuple(offset_xyz or ()))
    expected_rotation = tuple(float(value) for value in tuple(rotate_xyz_degrees or ()))
    expected_scale = tuple(float(value) for value in tuple(scale_xyz or ()))
    expected_uniform = float(uniform_scale)
    for target_source_index in tuple(target_indices or ()):
        try:
            normalized_index = int(target_source_index)
        except (TypeError, ValueError):
            continue
        adjustment = source_part_adjustments.get(
            normalized_index,
            default_adjustment(normalized_index),
        )
        if (
            bool(getattr(adjustment, "enabled", True)) != bool(enabled)
            or tuple(float(value) for value in getattr(adjustment, "offset_xyz", ())) != expected_offset
            or tuple(float(value) for value in getattr(adjustment, "rotate_xyz_degrees", ())) != expected_rotation
            or tuple(float(value) for value in getattr(adjustment, "scale_xyz", ())) != expected_scale
            or float(getattr(adjustment, "uniform_scale", 1.0)) != expected_uniform
        ):
            return True
    return False


def source_part_material_adjustment_state(
    source_part_adjustments: Mapping[int, object],
    *,
    source_index: object,
    selected_source_indices: Sequence[int],
    brightness: object,
    contrast: object,
    saturation: object,
    gamma: object,
    tint_rgb: Sequence[object],
    default_adjustment: Callable[[int], object],
) -> SourcePartMaterialAdjustmentState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    normalized_brightness = _source_part_clamped_float(brightness, default=0.0, minimum=-100.0, maximum=100.0)
    normalized_contrast = _source_part_clamped_float(contrast, default=0.0, minimum=-100.0, maximum=100.0)
    normalized_saturation = _source_part_clamped_float(saturation, default=0.0, minimum=-100.0, maximum=100.0)
    normalized_gamma = _source_part_clamped_float(gamma, default=1.0, minimum=0.25, maximum=4.0)
    normalized_tint = _source_part_rgb(tint_rgb)
    if normalized_source_index < 0:
        return SourcePartMaterialAdjustmentState(
            available=False,
            changed=False,
            target_indices=(),
            brightness=normalized_brightness,
            contrast=normalized_contrast,
            saturation=normalized_saturation,
            gamma=normalized_gamma,
            tint_rgb=normalized_tint,
        )
    target_indices = source_part_normalized_target_indices(normalized_source_index, selected_source_indices)
    changed = source_part_material_adjustment_values_changed(
        source_part_adjustments,
        target_indices,
        brightness=normalized_brightness,
        contrast=normalized_contrast,
        saturation=normalized_saturation,
        gamma=normalized_gamma,
        tint_rgb=normalized_tint,
        default_adjustment=default_adjustment,
    )
    return SourcePartMaterialAdjustmentState(
        available=bool(target_indices),
        changed=changed,
        target_indices=target_indices,
        brightness=normalized_brightness,
        contrast=normalized_contrast,
        saturation=normalized_saturation,
        gamma=normalized_gamma,
        tint_rgb=normalized_tint,
    )


def source_part_material_adjustment_values_changed(
    source_part_adjustments: Mapping[int, object],
    target_indices: Sequence[int],
    *,
    brightness: float,
    contrast: float,
    saturation: float,
    gamma: float,
    tint_rgb: Sequence[int],
    default_adjustment: Callable[[int], object],
) -> bool:
    expected_tint = _source_part_rgb(tint_rgb)
    for target_source_index in tuple(target_indices or ()):
        try:
            normalized_index = int(target_source_index)
        except (TypeError, ValueError):
            continue
        adjustment = source_part_adjustments.get(
            normalized_index,
            default_adjustment(normalized_index),
        )
        current_tint = tuple(getattr(adjustment, "material_tint_rgb", ()) or ())
        if not current_tint:
            current_tint = (255, 255, 255)
        if (
            abs(float(getattr(adjustment, "material_brightness", 0.0) or 0.0) - float(brightness)) > 1e-8
            or abs(float(getattr(adjustment, "material_contrast", 0.0) or 0.0) - float(contrast)) > 1e-8
            or abs(float(getattr(adjustment, "material_saturation", 0.0) or 0.0) - float(saturation)) > 1e-8
            or abs(float(getattr(adjustment, "material_gamma", 1.0) or 1.0) - float(gamma)) > 1e-8
            or _source_part_rgb(current_tint) != expected_tint
        ):
            return True
    return False


def source_part_glow_emissive_update_states(
    source_part_adjustments: Mapping[int, object],
    *,
    source_index: object,
    rgb: Sequence[object],
    use_color: bool,
    strength: object = 1.0,
    use_strength: bool = False,
) -> tuple[SourcePartGlowEmissiveUpdateState, ...]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError, OverflowError):
        return ()
    if normalized_source_index < 0:
        return ()
    adjustment = source_part_adjustments.get(normalized_source_index)
    if adjustment is None or str(getattr(adjustment, "material_role", "") or "").strip().lower() != "glow":
        return ()
    normalized_rgb = _source_part_rgb(rgb)
    next_rgb = normalized_rgb if use_color else ()
    try:
        normalized_strength = max(0.0, min(20.0, float(strength))) if use_strength else None
    except (TypeError, ValueError, OverflowError):
        normalized_strength = 1.0 if use_strength else None
    current_rgb = tuple(getattr(adjustment, "emissive_color_rgb", ()) or ())
    current_strength = getattr(adjustment, "emissive_strength", None)
    if current_rgb == next_rgb and current_strength == normalized_strength:
        return ()
    return (
        SourcePartGlowEmissiveUpdateState(
            source_index=normalized_source_index,
            emissive_color_rgb=next_rgb,
            emissive_strength=normalized_strength,
        ),
    )


def source_part_glow_color_action_state() -> SourcePartGlowColorActionState:
    return SourcePartGlowColorActionState(
        undo_action="glow",
        refresh_plan=False,
        force_plan=False,
        refresh_preview=True,
        refresh_reason="source glow color change",
    )


def source_part_role_action_state(
    *,
    source_index: object,
    role_value: object,
    undo_label: str,
    refresh_reason: str = "source role change",
) -> SourcePartRoleActionState:
    role_state = source_part_role_override_state(
        source_index=source_index,
        role_value=role_value,
        glow_color_checked=False,
        glow_rgb=(),
    )
    available = role_state.source_index >= 0
    return SourcePartRoleActionState(
        available=available,
        source_index=role_state.source_index,
        normalized_role=role_state.normalized_role,
        undo_label=str(undo_label or "Change source role"),
        refresh_plan=True,
        force_plan=True,
        refresh_preview=True,
        refresh_reason=str(refresh_reason or "source role change"),
    )


def source_part_role_export_flush_states(
    source_role_overrides: Mapping[int, object],
    source_part_adjustments: Mapping[int, object],
    *,
    default_adjustment: Callable[[int], object],
) -> tuple[SourcePartRoleExportFlushState, ...]:
    states: list[SourcePartRoleExportFlushState] = []
    for raw_source_index, raw_role in tuple(source_role_overrides.items()):
        role_state = source_part_role_override_state(
            source_index=raw_source_index,
            role_value=raw_role,
            glow_color_checked=False,
            glow_rgb=(),
        )
        if role_state.source_index < 0:
            continue
        adjustment = source_part_adjustments.get(
            role_state.source_index,
            default_adjustment(role_state.source_index),
        )
        material_role_changed = (
            str(getattr(adjustment, "material_role", "") or "").strip() != role_state.normalized_role
        )
        # Color/strength are dormant metadata outside the glow role. Keeping them
        # lets each part restore its independent override when glow is reselected.
        clear_emissive = False
        states.append(
            SourcePartRoleExportFlushState(
                source_index=role_state.source_index,
                normalized_role=role_state.normalized_role,
                material_role_changed=material_role_changed,
                clear_emissive_color=clear_emissive,
            )
        )
    return tuple(states)


def source_part_role_override_state(
    *,
    source_index: int,
    role_value: object,
    glow_color_checked: bool,
    glow_rgb: Sequence[object],
) -> SourcePartRoleOverrideState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    if normalized_source_index < 0:
        return SourcePartRoleOverrideState(
            source_index=-1,
            normalized_role="",
            store_override=False,
            emissive_color_rgb=(),
        )
    normalized_role = str(role_value or "").strip()
    return SourcePartRoleOverrideState(
        source_index=normalized_source_index,
        normalized_role=normalized_role,
        store_override=bool(normalized_role),
        emissive_color_rgb=_source_part_rgb(glow_rgb) if normalized_role == "glow" and glow_color_checked else (),
    )


__all__ = [
    "SourcePartAdjustmentApplyState",
    "SourcePartGlowColorActionState",
    "SourcePartGlowEmissiveUpdateState",
    "SourcePartMaterialAdjustmentState",
    "SourcePartRoleActionState",
    "SourcePartRoleExportFlushState",
    "SourcePartRoleOverrideState",
    "source_part_adjustment_apply_state",
    "source_part_adjustment_values_changed",
    "source_part_glow_color_action_state",
    "source_part_glow_emissive_update_states",
    "source_part_material_adjustment_state",
    "source_part_material_adjustment_values_changed",
    "source_part_role_action_state",
    "source_part_role_export_flush_states",
    "source_part_role_override_state",
]
