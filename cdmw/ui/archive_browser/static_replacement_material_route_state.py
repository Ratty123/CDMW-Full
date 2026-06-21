"""Material route state helpers for static replacement UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MaterialRouteControlState:
    apply_selected_source_textures_enabled: bool
    use_route_source_enabled: bool
    keep_original_enabled: bool
    choose_file_enabled: bool
    neutralize_enabled: bool
    do_not_emit_enabled: bool


@dataclass(frozen=True, slots=True)
class MaterialPlanDetailState:
    visible: bool
    detail_html: str
    transform_visible: bool


def material_route_control_state(
    *,
    has_item: bool,
    material_name: str,
    has_texture_sets: bool,
    has_sidecar_bindings: bool,
) -> MaterialRouteControlState:
    has_material_route = bool(has_item and str(material_name or "").strip())
    source_texture_actions_enabled = bool(has_material_route and has_texture_sets and has_sidecar_bindings)
    sidecar_actions_enabled = bool(has_material_route and has_sidecar_bindings)
    return MaterialRouteControlState(
        source_texture_actions_enabled,
        source_texture_actions_enabled,
        sidecar_actions_enabled,
        sidecar_actions_enabled,
        sidecar_actions_enabled,
        sidecar_actions_enabled,
    )


def material_plan_detail_state(
    *,
    has_item: bool,
    detail_html: str,
    material_name: str,
    empty_text: str,
) -> MaterialPlanDetailState:
    return MaterialPlanDetailState(
        bool(has_item),
        str(detail_html or empty_text or ""),
        bool(str(material_name or "").strip()),
    )


__all__ = [
    "MaterialPlanDetailState",
    "MaterialRouteControlState",
    "material_plan_detail_state",
    "material_route_control_state",
]
