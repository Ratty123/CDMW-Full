"""Material-plan UI state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DdsDetailThumbnailState:
    has_item: bool
    show_pixmap: bool
    text: str
    tooltip: str


@dataclass(frozen=True, slots=True)
class DdsDetailClearState:
    panel_visible: bool
    detail_text: str
    thumbnail: DdsDetailThumbnailState


@dataclass(frozen=True, slots=True)
class DdsDetailRefreshRouteState:
    should_resolve: bool
    preview_source: object | None
    slot_kind: str
    thumbnail: DdsDetailThumbnailState


@dataclass(frozen=True, slots=True)
class SelectedSourceMaterialTextureActionState:
    texture_set: object | None
    source_indices: set[int]
    planned_rows: tuple[tuple[dict[str, object], str, str], ...]
    material_name: str
    message_key: str
    enable_base_controls: bool
    saw_base: bool


@dataclass(frozen=True, slots=True)
class TextureRowsActionState:
    rows: tuple[tuple[dict[str, object], str, str], ...] | tuple[dict[str, object], ...]
    message_key: str
    should_refresh: bool = False
    should_check_rebuild_sidecar: bool = False
    texture_path: str = ""


@dataclass(frozen=True, slots=True)
class MaterialPlanProfileStatsState:
    material_count: int
    shader_count: int
    emissive_count: int


@dataclass(frozen=True, slots=True)
class MaterialPlanRouteStatsState:
    conflict_messages: tuple[str, ...]
    routing_blockers: tuple[object, ...]
    base_route_count: int
    normal_route_count: int
    pbr_count: int


@dataclass(frozen=True, slots=True)
class MaterialPlanDisplayState:
    summary_kwargs: dict[str, object]
    contract_kwargs: dict[str, int]
    routing_visible: bool
    plan_visible: bool
    apply_texture_plan_enabled: bool
    apply_selected_source_enabled: bool


@dataclass(frozen=True, slots=True)
class SourceMaterialRouteRowState:
    route: object
    status_label: str
    source_part_names: tuple[str, ...]
    source_material_name: str
    target_material_name: str


@dataclass(frozen=True, slots=True)
class ReplacementTexturePlanRowState:
    plan_row: object
    status_label: str
    material_name: str
    preview_status: str
    status_foreground: str


@dataclass(frozen=True, slots=True)
class FinalPreviewPlanState:
    binding_rows: tuple[object, ...]
    material_statuses: tuple[object, ...]
    warnings: tuple[str, ...]
    detected_sets: int
    detected_slots: int


@dataclass(frozen=True, slots=True)
class FinalPreviewMaterialStatusRowState:
    material_status: object
    material_name: str
    status_label: str
    detail: str
    maps: str


@dataclass(frozen=True, slots=True)
class FinalPreviewBindingRowState:
    binding_row: object
    material_name: str
    part_name: str
    status_label: str


def texture_material_plan_loaded_initial_state() -> dict[str, bool]:
    return {"loaded": False, "loading": False}


def selected_texture_plan_source_initial_state() -> dict[str, object]:
    return {"material_name": "", "source_indices": ()}


def material_plan_control_text() -> dict[str, object]:
    texture_file_filter = "Texture files (*.png *.dds *.jpg *.jpeg *.tga *.bmp *.tif *.tiff);;All files (*.*)"
    return {
        "group_title": "Materials",
        "contract_tooltip": "Stock/shared shader layers and helper wrappers are preserved by default.",
        "final_contract_tooltip": "Final texture contract resolved from packaged sidecar/DDS payloads.",
        "apply_suggested": "Apply Suggested",
        "apply_suggested_tooltip": (
            "Apply compatible suggestions to original-DDS override rows when the source texture plan can identify them."
        ),
        "use_selected": "Use Selected",
        "use_selected_tooltip": "Apply the selected material row to compatible target slots.",
        "use_route_source": "Use route source",
        "use_route_source_tooltip": "Use the selected material row's detected route source for compatible original DDS slots.",
        "keep_original": "Keep original",
        "keep_original_tooltip": "Keep original DDS bindings for the selected material route.",
        "choose_file": "Choose file",
        "choose_file_tooltip": "Choose a manual texture file for compatible selected material route slots.",
        "neutralize": "Neutralize",
        "neutralize_tooltip": "Clear selected route overrides so sidecar pruning/neutral output rules can apply.",
        "do_not_emit": "Do not emit",
        "do_not_emit_tooltip": "Do not emit replacement DDS overrides for the selected material route.",
        "help": (
            "Rows highlight the affected target and replacement part. Use Selected applies that row's maps to compatible slots."
        ),
        "advanced_routes": "Advanced Routes",
        "material_routing_headers": ["Target", "Source", "Parts", "Maps", "State", "Action"],
        "material_plan_headers": ["Part", "Role", "Source", "DDS", "Preview", "Param"],
        "dds_detail_no_preview": "No preview",
        "dds_detail_select_row": "Select a row.",
        "dds_detail_not_previewable": "Not previewable",
        "dds_detail_preview_read_failed": "Preview image could not be read: {preview_path}",
        "apply_suggested_reason": "Apply compatible sources; ambiguous rows stay unchanged.",
        "use_selected_missing_title": "Use Selected",
        "use_selected_missing_message": "Select a material row first.",
        "use_selected_base_enabled": "Base/color binding enabled.",
        "use_selected_no_rows": "No compatible rows matched.",
        "use_selected_reason": "Apply detected textures from {material_name}.",
        "texture_route_title": "Texture Route",
        "texture_route_select_first": "Select a material route first.",
        "choose_route_texture_title": "Choose Texture For Selected Route",
        "texture_file_filter": texture_file_filter,
        "add_replacement_textures_title": "Add Replacement Textures",
        "add_replacement_folder_title": "Add Replacement Texture Folder",
    }


def material_plan_column_fit_specs() -> dict[str, dict[str, object]]:
    return {
        "routing": {
            "minimum_widths": (90, 90, 110, 60, 58, 120),
            "maximum_widths": (240, 240, 320, 120, 92, 420),
            "expand_columns": (5, 2, 0, 1),
        },
        "plan": {
            "minimum_widths": (72, 58, 150, 230, 58, 90),
            "maximum_widths": (140, 120, 360, 520, 92, 240),
            "expand_columns": (3, 2, 5),
        },
    }


def material_plan_column_refit_requests() -> tuple[tuple[int, str], ...]:
    return (
        (0, "routing"),
        (0, "plan"),
        (150, "routing"),
        (150, "plan"),
    )


def reset_selected_texture_plan_source_state(selected_texture_plan_source: dict[str, object]) -> None:
    selected_texture_plan_source["material_name"] = ""
    selected_texture_plan_source["source_indices"] = ()


def material_plan_profile_stats(source_texture_evidence: Sequence[object]) -> MaterialPlanProfileStatsState:
    profile_labels = {
        str(evidence.get("material_profile_label") or "").strip()
        for evidence in tuple(source_texture_evidence or ())
        if isinstance(evidence, Mapping) and str(evidence.get("material_profile_label") or "").strip()
    }
    profile_shaders = {
        str(evidence.get("material_profile_shader") or "").strip()
        for evidence in tuple(source_texture_evidence or ())
        if isinstance(evidence, Mapping) and str(evidence.get("material_profile_shader") or "").strip()
    }
    profile_emissive_count = sum(
        1
        for evidence in tuple(source_texture_evidence or ())
        if isinstance(evidence, Mapping) and bool(evidence.get("material_profile_emissive"))
    )
    return MaterialPlanProfileStatsState(
        material_count=len(profile_labels),
        shader_count=len(profile_shaders),
        emissive_count=profile_emissive_count,
    )


def deferred_material_plan_display_state(texture_sets: Mapping[str, object]) -> MaterialPlanDisplayState:
    detected_preview_sets = len(texture_sets)
    detected_preview_slots = sum(
        len(getattr(texture_set, "slots", {}) or {})
        for texture_set in tuple(texture_sets.values())
    )
    return MaterialPlanDisplayState(
        summary_kwargs={
            "detected_sets": detected_preview_sets,
            "detected_slots": detected_preview_slots,
            "conflicts": ("Deferred until opened.",),
            "empty": not bool(texture_sets),
        },
        contract_kwargs={"route_count": 0, "blocker_count": 0, "base_count": 0, "normal_count": 0, "pbr_count": 0},
        routing_visible=False,
        plan_visible=False,
        apply_texture_plan_enabled=False,
        apply_selected_source_enabled=False,
    )


def empty_material_plan_display_state() -> MaterialPlanDisplayState:
    return MaterialPlanDisplayState(
        summary_kwargs={"detected_sets": 0, "detected_slots": 0, "conflicts": (), "empty": True},
        contract_kwargs={"route_count": 0, "blocker_count": 0, "base_count": 0, "normal_count": 0, "pbr_count": 0},
        routing_visible=False,
        plan_visible=False,
        apply_texture_plan_enabled=False,
        apply_selected_source_enabled=False,
    )


def source_material_plan_display_state(
    texture_sets: Mapping[str, object],
    *,
    detected_slot_count: int,
    route_count: int,
    route_stats: MaterialPlanRouteStatsState,
    profile_stats: MaterialPlanProfileStatsState,
    has_sidecar_bindings: bool,
) -> MaterialPlanDisplayState:
    return MaterialPlanDisplayState(
        summary_kwargs={
            "detected_sets": len(texture_sets),
            "detected_slots": int(detected_slot_count),
            "conflicts": route_stats.conflict_messages,
            "profile_material_count": profile_stats.material_count,
            "profile_shader_count": profile_stats.shader_count,
            "profile_emissive_count": profile_stats.emissive_count,
        },
        contract_kwargs={
            "route_count": int(route_count),
            "blocker_count": len(route_stats.routing_blockers),
            "base_count": route_stats.base_route_count,
            "normal_count": route_stats.normal_route_count,
            "pbr_count": route_stats.pbr_count,
        },
        routing_visible=True,
        plan_visible=True,
        apply_texture_plan_enabled=bool(has_sidecar_bindings),
        apply_selected_source_enabled=True,
    )


def material_plan_route_stats(
    texture_sets: Mapping[str, object],
    routing_rows: Sequence[object],
    conflict_messages: Sequence[object],
) -> MaterialPlanRouteStatsState:
    routing_blockers = tuple(route for route in tuple(routing_rows or ()) if bool(getattr(route, "blocker", False)))
    route_conflicts = tuple(
        str(getattr(route, "reason", "") or "").strip()
        for route in routing_blockers
        if str(getattr(route, "reason", "") or "").strip()
    )
    base_route_count = sum(1 for route in tuple(routing_rows or ()) if "base" in tuple(getattr(route, "detected_roles", ()) or ()))
    normal_route_count = sum(
        1 for route in tuple(routing_rows or ()) if "normal" in tuple(getattr(route, "detected_roles", ()) or ())
    )
    pbr_count = sum(
        1
        for texture_set in tuple(texture_sets.values())
        for role in tuple(getattr(texture_set, "slots", {}) or ())
        if str(role or "").strip().lower() in {"metallic", "roughness", "ao"}
    )
    return MaterialPlanRouteStatsState(
        conflict_messages=tuple(str(message) for message in tuple(conflict_messages or ())) + route_conflicts,
        routing_blockers=routing_blockers,
        base_route_count=base_route_count,
        normal_route_count=normal_route_count,
        pbr_count=pbr_count,
    )


def source_material_route_row_states(routing_rows: Sequence[object]) -> tuple[SourceMaterialRouteRowState, ...]:
    return tuple(
        SourceMaterialRouteRowState(
            route=route,
            status_label=str(getattr(route, "status", "") or "Unknown"),
            source_part_names=tuple(str(part_name) for part_name in tuple(getattr(route, "source_part_names", ()) or ())),
            source_material_name=str(getattr(route, "source_material_name", "") or ""),
            target_material_name=str(getattr(route, "target_material_name", "") or ""),
        )
        for route in tuple(routing_rows or ())
    )


def replacement_texture_plan_row_states(
    plan_rows: Sequence[object],
    *,
    ready_statuses: Sequence[str],
    support_only_statuses: Sequence[str] = (),
) -> tuple[ReplacementTexturePlanRowState, ...]:
    ready = {str(status) for status in tuple(ready_statuses or ())}
    support_only = {str(status) for status in tuple(support_only_statuses or ())}
    states: list[ReplacementTexturePlanRowState] = []
    for plan_row in tuple(plan_rows or ()):
        status_label = str(getattr(getattr(plan_row, "status", None), "label", "") or "")
        material_name = str(getattr(plan_row, "full_part_material", "") or getattr(plan_row, "part_material", "") or "")
        if " / " in material_name:
            material_name = material_name.rsplit(" / ", 1)[-1]
        states.append(
            ReplacementTexturePlanRowState(
                plan_row=plan_row,
                status_label=status_label,
                material_name=material_name,
                preview_status=(
                    "thumbnail if decoded; final path via Test Build" if status_label in ready else "not previewable"
                ),
                status_foreground="#0d1117" if status_label in (ready | support_only) else "#ffffff",
            )
        )
    return tuple(states)


def replacement_texture_plan_target_name(
    source_indices: Sequence[object],
    mappings: Sequence[object],
) -> str:
    normalized_sources: set[int] = set()
    for raw_source_index in tuple(source_indices or ()):
        try:
            normalized_sources.add(int(raw_source_index))
        except (TypeError, ValueError):
            continue
    if not normalized_sources:
        return ""
    for mapping in tuple(mappings or ()):
        mapping_sources = set()
        for raw_source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
            try:
                mapping_sources.add(int(raw_source_index))
            except (TypeError, ValueError):
                continue
        if normalized_sources & mapping_sources:
            return str(getattr(mapping, "target_submesh_name", "") or "")
    return ""


def final_preview_plan_state(final_preview: object) -> FinalPreviewPlanState:
    binding_rows = tuple(getattr(final_preview, "binding_rows", ()) or ())
    material_statuses = tuple(getattr(final_preview, "material_statuses", ()) or ())
    warnings = tuple(str(message) for message in tuple(getattr(final_preview, "warnings", ()) or ()))
    material_names = {
        str(getattr(row, "material_name", "") or "")
        for row in binding_rows
        if str(getattr(row, "material_name", "") or "")
    }
    return FinalPreviewPlanState(
        binding_rows=binding_rows,
        material_statuses=material_statuses,
        warnings=warnings,
        detected_sets=len(material_names),
        detected_slots=len(binding_rows),
    )


def final_preview_material_status_row_states(
    material_statuses: Sequence[object],
    binding_rows: Sequence[object],
) -> tuple[FinalPreviewMaterialStatusRowState, ...]:
    states: list[FinalPreviewMaterialStatusRowState] = []
    bindings = tuple(binding_rows or ())
    for material_status in tuple(material_statuses or ()):
        material_name = str(getattr(material_status, "material_name", "") or "")
        material_rows = [
            row
            for row in bindings
            if str(getattr(row, "material_name", "") or "") == material_name
        ]
        maps = ", ".join(
            dict.fromkeys(str(getattr(row, "role", "") or "") for row in material_rows if str(getattr(row, "role", "") or ""))
        ) or "-"
        states.append(
            FinalPreviewMaterialStatusRowState(
                material_status=material_status,
                material_name=material_name,
                status_label=str(getattr(material_status, "status", "") or "unknown"),
                detail=str(getattr(material_status, "detail", "") or ""),
                maps=maps,
            )
        )
    return tuple(states)


def final_preview_binding_row_states(binding_rows: Sequence[object]) -> tuple[FinalPreviewBindingRowState, ...]:
    states: list[FinalPreviewBindingRowState] = []
    for row in tuple(binding_rows or ()):
        material_name = str(getattr(row, "material_name", "") or "")
        part_name = str(getattr(row, "part_name", "") or "").strip() or material_name
        states.append(
            FinalPreviewBindingRowState(
                binding_row=row,
                material_name=material_name,
                part_name=part_name,
                status_label=str(getattr(row, "status", "") or "unknown"),
            )
        )
    return tuple(states)


def final_preview_binding_target_index(
    part_name: str,
    material_name: str,
    *,
    target_index_for_name: Callable[[str], int],
) -> int:
    target_index = int(target_index_for_name(str(part_name or "")))
    if target_index < 0:
        target_index = int(target_index_for_name(str(material_name or "")))
    return target_index


def suggested_texture_plan_rows(
    texture_override_rows: list[dict[str, object]],
    *,
    can_apply: Callable[[dict[str, object], object], bool],
) -> tuple[tuple[dict[str, object], str, str], ...]:
    planned_rows: list[tuple[dict[str, object], str, str]] = []
    for row_state in texture_override_rows:
        suggested_source = str(row_state.get("suggested_source", "") or "").strip()
        guidance = row_state.get("guidance")
        if suggested_source and can_apply(row_state, guidance):
            planned_rows.append((row_state, suggested_source, "Apply"))
    return tuple(planned_rows)


def all_suggested_texture_plan_rows(
    texture_override_rows: list[dict[str, object]],
) -> tuple[tuple[dict[str, object], str, str], ...]:
    planned_rows: list[tuple[dict[str, object], str, str]] = []
    for row_state in texture_override_rows:
        suggested_source = str(row_state.get("suggested_source", "") or "").strip()
        if suggested_source:
            planned_rows.append((row_state, suggested_source, "Apply"))
    return tuple(planned_rows)


def suggested_texture_plan_action_state(
    texture_override_rows: list[dict[str, object]],
    *,
    can_apply: Callable[[dict[str, object], object], bool],
) -> TextureRowsActionState:
    return TextureRowsActionState(
        rows=suggested_texture_plan_rows(texture_override_rows, can_apply=can_apply),
        message_key="",
        should_refresh=True,
    )


def all_suggested_override_sources_action_state(
    texture_override_rows: list[dict[str, object]],
) -> TextureRowsActionState:
    planned_rows = all_suggested_texture_plan_rows(texture_override_rows)
    return TextureRowsActionState(
        rows=planned_rows,
        message_key="" if planned_rows else "no_suggestions",
        should_refresh=bool(planned_rows),
    )


def selected_material_override_rows(
    texture_override_rows: list[dict[str, object]],
    selected_texture_plan_source: Mapping[str, object],
    *,
    texture_row_current_source_indices: Callable[[Mapping[str, object]], tuple[int, ...]],
) -> tuple[dict[str, object], ...]:
    selected_sources = {
        int(raw_source_index)
        for raw_source_index in tuple(selected_texture_plan_source.get("source_indices", ()) or ())
        if isinstance(raw_source_index, int) or str(raw_source_index).strip().lstrip("-").isdigit()
    }
    selected_material = str(selected_texture_plan_source.get("material_name", "") or "").strip().lower()
    rows: list[dict[str, object]] = []
    for row_state in texture_override_rows:
        row_sources = set(texture_row_current_source_indices(row_state))
        row_material = str(row_state.get("target_name", "") or "").strip().lower()
        if selected_sources and row_sources and selected_sources & row_sources:
            rows.append(row_state)
        elif selected_material and row_material == selected_material:
            rows.append(row_state)
    return tuple(rows)


def selected_material_texture_clear_action_state(
    selected_rows: Sequence[dict[str, object]],
) -> TextureRowsActionState:
    rows = tuple(selected_rows or ())
    return TextureRowsActionState(
        rows=rows,
        message_key="" if rows else "select_route",
        should_refresh=bool(rows),
    )


def selected_material_texture_file_action_state(
    selected_rows: Sequence[dict[str, object]],
    selected_file: object,
    *,
    is_file: Callable[[Path], bool],
) -> TextureRowsActionState:
    rows = tuple(selected_rows or ())
    if not rows:
        return TextureRowsActionState(rows=(), message_key="select_route")
    file_text = str(selected_file or "").strip()
    if not file_text:
        return TextureRowsActionState(rows=rows, message_key="cancelled")
    texture_path = Path(file_text).expanduser()
    if not is_file(texture_path):
        return TextureRowsActionState(rows=rows, message_key="missing_file")
    return TextureRowsActionState(
        rows=rows,
        message_key="",
        should_refresh=True,
        texture_path=str(texture_path),
    )


def registered_texture_sources_action_state(
    added: object,
    *,
    has_texture_sets: bool,
    rebuild_sidecar_checked: bool,
) -> TextureRowsActionState:
    added_count = len(tuple(added or ())) if not isinstance(added, int) else int(added)
    return TextureRowsActionState(
        rows=(),
        message_key="" if added_count > 0 else "none_added",
        should_refresh=added_count > 0,
        should_check_rebuild_sidecar=bool(added_count > 0 and has_texture_sets and not rebuild_sidecar_checked),
    )


def texture_set_for_selected_source_material(
    selected_texture_plan_source: Mapping[str, object],
    texture_sets: Mapping[str, object],
    *,
    texture_set_for_source_index: Callable[[int, Mapping[str, object]], object | None],
) -> object | None:
    material_name = str(selected_texture_plan_source.get("material_name", "") or "").strip()
    if material_name:
        material_key = material_name.lower()
        texture_set = texture_sets.get(material_key)
        if texture_set is not None:
            return texture_set
        for candidate in texture_sets.values():
            if str(getattr(candidate, "material_name", "") or "").strip().lower() == material_key:
                return candidate
    for raw_source_index in tuple(selected_texture_plan_source.get("source_indices", ()) or ()):
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        texture_set = texture_set_for_source_index(source_index, texture_sets)
        if texture_set is not None:
            return texture_set
    return None


def selected_source_material_indices(
    selected_texture_plan_source: Mapping[str, object],
    texture_set: object,
    *,
    source_indices_for_material_name: Callable[[str], tuple[int, ...]],
) -> set[int]:
    source_indices = {
        int(raw_source_index)
        for raw_source_index in tuple(selected_texture_plan_source.get("source_indices", ()) or ())
        if isinstance(raw_source_index, int) or str(raw_source_index).strip().lstrip("-").isdigit()
    }
    if not source_indices:
        source_indices.update(source_indices_for_material_name(str(getattr(texture_set, "material_name", "") or "")))
    return source_indices


def selected_source_material_texture_plan_rows(
    texture_override_rows: list[dict[str, object]],
    texture_set: object,
    source_indices: set[int],
    *,
    texture_row_current_source_indices: Callable[[Mapping[str, object]], tuple[int, ...]],
    source_slot_for_texture_row: Callable[[object, Mapping[str, object]], object | None],
) -> tuple[tuple[dict[str, object], str, str], ...]:
    planned_rows: list[tuple[dict[str, object], str, str]] = []
    for row_state in texture_override_rows:
        row_source_indices = set(texture_row_current_source_indices(row_state))
        if source_indices and row_source_indices and not (source_indices & row_source_indices):
            continue
        source_slot = source_slot_for_texture_row(texture_set, row_state)
        source_path = getattr(source_slot, "source_path", None) if source_slot is not None else None
        if not isinstance(source_path, Path):
            continue
        planned_rows.append((row_state, str(source_path), "Apply"))
    return tuple(planned_rows)


def selected_source_material_texture_action_state(
    selected_texture_plan_source: Mapping[str, object],
    texture_sets: Mapping[str, object],
    texture_override_rows: list[dict[str, object]],
    *,
    texture_set_for_source_index: Callable[[int, Mapping[str, object]], object | None],
    source_indices_for_material_name: Callable[[str], tuple[int, ...]],
    texture_row_current_source_indices: Callable[[Mapping[str, object]], tuple[int, ...]],
    source_slot_for_texture_row: Callable[[object, Mapping[str, object]], object | None],
) -> SelectedSourceMaterialTextureActionState:
    texture_set = texture_set_for_selected_source_material(
        selected_texture_plan_source,
        texture_sets,
        texture_set_for_source_index=texture_set_for_source_index,
    )
    if texture_set is None:
        return SelectedSourceMaterialTextureActionState(
            texture_set=None,
            source_indices=set(),
            planned_rows=(),
            material_name="",
            message_key="missing_selection",
            enable_base_controls=False,
            saw_base=False,
        )
    source_indices = selected_source_material_indices(
        selected_texture_plan_source,
        texture_set,
        source_indices_for_material_name=source_indices_for_material_name,
    )
    planned_rows = selected_source_material_texture_plan_rows(
        texture_override_rows,
        texture_set,
        source_indices,
        texture_row_current_source_indices=texture_row_current_source_indices,
        source_slot_for_texture_row=source_slot_for_texture_row,
    )
    material_name = str(getattr(texture_set, "material_name", "") or "selected source material")
    if not planned_rows:
        base_slot = (getattr(texture_set, "slots", {}) or {}).get("base")
        enable_base_controls = bool(base_slot is not None and isinstance(getattr(base_slot, "source_path", None), Path))
        return SelectedSourceMaterialTextureActionState(
            texture_set=texture_set,
            source_indices=source_indices,
            planned_rows=(),
            material_name=material_name,
            message_key="base_enabled" if enable_base_controls else "no_rows",
            enable_base_controls=enable_base_controls,
            saw_base=False,
        )
    return SelectedSourceMaterialTextureActionState(
        texture_set=texture_set,
        source_indices=source_indices,
        planned_rows=planned_rows,
        material_name=material_name,
        message_key="",
        enable_base_controls=any(str(row_state.get("slot_kind", "") or "").strip().lower() == "base" for row_state, _, _ in planned_rows),
        saw_base=any(str(row_state.get("slot_kind", "") or "").strip().lower() == "base" for row_state, _, _ in planned_rows),
    )


def dds_detail_item_state(
    *,
    has_item: bool,
    preview_source: object,
    slot_kind: object,
) -> dict[str, object]:
    return {
        "has_item": bool(has_item),
        "preview_source": preview_source if bool(has_item) else None,
        "slot_kind": str(slot_kind or "base") if bool(has_item) else "base",
    }


def dds_detail_clear_state(control_text: Mapping[str, object]) -> DdsDetailClearState:
    return DdsDetailClearState(
        panel_visible=False,
        detail_text=str(control_text["dds_detail_select_row"]),
        thumbnail=dds_detail_thumbnail_state(
            has_item=False,
            preview_path=None,
            status_text="",
            pixmap_readable=False,
            control_text=control_text,
        ),
    )


def dds_detail_refresh_route_state(
    *,
    has_item: bool,
    preview_source: object,
    slot_kind: object,
    control_text: Mapping[str, object],
) -> DdsDetailRefreshRouteState:
    item_state = dds_detail_item_state(
        has_item=has_item,
        preview_source=preview_source,
        slot_kind=slot_kind,
    )
    if not bool(item_state["has_item"]):
        return DdsDetailRefreshRouteState(
            should_resolve=False,
            preview_source=None,
            slot_kind="base",
            thumbnail=dds_detail_thumbnail_state(
                has_item=False,
                preview_path=None,
                status_text="",
                pixmap_readable=False,
                control_text=control_text,
            ),
        )
    return DdsDetailRefreshRouteState(
        should_resolve=True,
        preview_source=item_state["preview_source"],
        slot_kind=str(item_state["slot_kind"]),
        thumbnail=dds_detail_thumbnail_state(
            has_item=False,
            preview_path=None,
            status_text="",
            pixmap_readable=False,
            control_text=control_text,
        ),
    )


def dds_detail_thumbnail_state(
    *,
    has_item: bool,
    preview_path: Path | None,
    status_text: str,
    pixmap_readable: bool,
    control_text: Mapping[str, object],
) -> DdsDetailThumbnailState:
    if not bool(has_item):
        return DdsDetailThumbnailState(
            has_item=False,
            show_pixmap=False,
            text=str(control_text["dds_detail_no_preview"]),
            tooltip="",
        )
    if preview_path is None:
        return DdsDetailThumbnailState(
            has_item=True,
            show_pixmap=False,
            text=str(control_text["dds_detail_not_previewable"]),
            tooltip=str(status_text or ""),
        )
    if not bool(pixmap_readable):
        return DdsDetailThumbnailState(
            has_item=True,
            show_pixmap=False,
            text=str(control_text["dds_detail_not_previewable"]),
            tooltip=str(control_text["dds_detail_preview_read_failed"]).format(preview_path=preview_path),
        )
    return DdsDetailThumbnailState(
        has_item=True,
        show_pixmap=True,
        text="",
        tooltip=f"{status_text}\n{preview_path}",
    )


def dds_detail_resolved_thumbnail_state(
    *,
    preview_path: Path | None,
    status_text: str,
    pixmap_readable: bool,
    control_text: Mapping[str, object],
) -> DdsDetailThumbnailState:
    return dds_detail_thumbnail_state(
        has_item=True,
        preview_path=preview_path,
        status_text=status_text,
        pixmap_readable=pixmap_readable,
        control_text=control_text,
    )


__all__ = [
    "DdsDetailClearState",
    "DdsDetailRefreshRouteState",
    "DdsDetailThumbnailState",
    "FinalPreviewBindingRowState",
    "FinalPreviewMaterialStatusRowState",
    "FinalPreviewPlanState",
    "MaterialPlanDisplayState",
    "MaterialPlanProfileStatsState",
    "MaterialPlanRouteStatsState",
    "ReplacementTexturePlanRowState",
    "SelectedSourceMaterialTextureActionState",
    "SourceMaterialRouteRowState",
    "TextureRowsActionState",
    "all_suggested_texture_plan_rows",
    "all_suggested_override_sources_action_state",
    "dds_detail_clear_state",
    "dds_detail_item_state",
    "dds_detail_refresh_route_state",
    "dds_detail_resolved_thumbnail_state",
    "dds_detail_thumbnail_state",
    "deferred_material_plan_display_state",
    "empty_material_plan_display_state",
    "final_preview_binding_target_index",
    "final_preview_binding_row_states",
    "final_preview_material_status_row_states",
    "final_preview_plan_state",
    "material_plan_column_fit_specs",
    "material_plan_column_refit_requests",
    "material_plan_control_text",
    "material_plan_profile_stats",
    "material_plan_route_stats",
    "registered_texture_sources_action_state",
    "replacement_texture_plan_row_states",
    "replacement_texture_plan_target_name",
    "reset_selected_texture_plan_source_state",
    "selected_material_override_rows",
    "selected_material_texture_clear_action_state",
    "selected_material_texture_file_action_state",
    "selected_source_material_indices",
    "selected_source_material_texture_plan_rows",
    "selected_source_material_texture_action_state",
    "selected_texture_plan_source_initial_state",
    "source_material_route_row_states",
    "source_material_plan_display_state",
    "suggested_texture_plan_action_state",
    "suggested_texture_plan_rows",
    "texture_material_plan_loaded_initial_state",
    "texture_set_for_selected_source_material",
]
