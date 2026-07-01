"""Mapping table build state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from html import escape

from cdmw.ui.archive_browser.static_replacement_source_display import (
    source_assignment_state_tooltip as _source_assignment_state_tooltip_owner,
    source_assignment_targets_tooltip as _source_assignment_targets_tooltip_owner,
)


@dataclass(frozen=True, slots=True)
class MappingTableTargetRowState:
    target_index: int
    row_number: int
    target_label_text: str
    target_role_source_text: str
    initial_mapping_text: str
    initial_source_indices: tuple[int, ...]
    removed: bool
    mapping_text_empty: bool


@dataclass(frozen=True, slots=True)
class MappingTableChunkPresentationState:
    current_rows: int
    total_rows: int
    filters_active: bool
    fit_height: bool
    complete: bool


@dataclass(frozen=True, slots=True)
class MappingTableAdvancedVisibilityState:
    advanced_visible: bool
    visible_widgets: bool
    hidden_columns: tuple[tuple[int, bool], ...]
    expand_part_tools: bool


@dataclass(frozen=True, slots=True)
class MappingRouteButtonSpec:
    key: str
    label: str
    object_name: str
    tooltip: str
    color: str


@dataclass(frozen=True, slots=True)
class MappingRouteSelectionButtonSpec:
    key: str
    label: str
    tooltip: str


def mapping_table_build_initial_state() -> dict[str, object]:
    return {"next_index": 0, "complete": False}


def mapping_table_build_next_index(state: Mapping[str, object]) -> int:
    return int(state.get("next_index", 0) or 0)


def mapping_table_build_set_next_index(
    state: MutableMapping[str, object],
    next_index: int,
) -> None:
    state["next_index"] = int(next_index)


def mapping_table_build_mark_complete(state: MutableMapping[str, object]) -> None:
    state["complete"] = True


def mapping_table_build_complete(state: Mapping[str, object]) -> bool:
    return bool(state.get("complete"))


def mapping_table_build_can_start(
    requested_state: Mapping[str, object],
    build_state: Mapping[str, object],
) -> bool:
    return not mapping_table_build_requested_started(requested_state) and not mapping_table_build_complete(build_state)


def mapping_table_build_requested_initial_state() -> dict[str, object]:
    return {"started": False}


def suggested_mappings_by_target(suggested_mappings: Sequence[object]) -> dict[int, object]:
    return {
        int(getattr(mapping, "target_submesh_index")): mapping
        for mapping in tuple(suggested_mappings or ())
    }


def mapping_table_target_row_state(
    *,
    target_index: object,
    target: object,
    mapping: object | None,
) -> MappingTableTargetRowState:
    try:
        normalized_target_index = int(target_index)
    except (TypeError, ValueError):
        normalized_target_index = -1
    row_number = normalized_target_index + 1
    target_label_text = str(
        getattr(target, "material", "")
        or getattr(target, "name", "")
        or f"target {normalized_target_index}"
    )
    target_role_source_text = f"{getattr(target, 'name', '')} {getattr(target, 'material', '')}"
    raw_source_indices = tuple(getattr(mapping, "source_submesh_indices", ()) or ()) if mapping is not None else ()
    source_indices: list[int] = []
    for raw_index in raw_source_indices:
        try:
            source_indices.append(int(raw_index))
        except (TypeError, ValueError):
            continue
    initial_source_indices = tuple(source_indices)
    initial_mapping_text = ", ".join(str(index) for index in initial_source_indices)
    removed = bool(mapping is not None and not initial_source_indices)
    return MappingTableTargetRowState(
        target_index=normalized_target_index,
        row_number=row_number,
        target_label_text=target_label_text,
        target_role_source_text=target_role_source_text,
        initial_mapping_text=initial_mapping_text,
        initial_source_indices=initial_source_indices,
        removed=removed,
        mapping_text_empty=not bool(initial_mapping_text.strip()),
    )


def mapping_table_action_control_text() -> dict[str, str]:
    return {
        "headers": ["Target", "Role", "Index", "Source", "State", "DDS", "Physics"],
        "routing_hint_html": (
            "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid #d2a8ff; background:#20252d;'>"
            "<span style='color:#d2a8ff; font-weight:700;'>Routing</span>"
            "<span style='color:#c9d1d9;'> | target -> source -> DDS</span>"
            "</div>"
        ),
        "routing_hint_tooltip": (
            "Each target row is an original game draw/material slot. Assign one source to replace it, add several sources to merge, "
            "or leave it empty to remove the original slot and prune its DDS sidecar references when material sidecar patching is enabled."
        ),
        "target_slots_html": (
            "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid #79c0ff; background:#10233a;'>"
            "<span style='color:#79c0ff; font-weight:700;'>Targets</span>"
            "<span style='color:#c9d1d9;'> | source | state | DDS | physics</span>"
            "</div>"
        ),
        "target_slots_tooltip": (
            "Select a target and source, then replace/add/remove. Empty targets export as removed original parts."
        ),
        "low_confidence_filter": "Show low confidence only",
        "empty_targets_filter": "Show removed targets only",
        "clear_all_guesses": "Clear all guesses",
        "apply_best_guesses": "Apply best guesses",
        "group_materials": "Group by Source Material",
        "preview_target": "Preview selected target",
        "clear_all_guesses_tooltip": "Empty every target slot so you can rebuild the mapping manually.",
        "apply_best_guesses_tooltip": "Restore the app's original best-guess target-slot mapping.",
        "group_materials_tooltip": (
            "Route imported parts so each original draw slot receives one source material set where possible. "
            "Use this when the replacement model has more pieces/materials than the original."
        ),
        "preview_target_tooltip": "Highlight the currently selected target slot in the preview.",
        "advanced_mapping": "Advanced Mapping",
        "advanced_mapping_tooltip": (
            "Show raw target routing, original/source reference lists, and source-index editor. "
            "Normal routing should use Parts Outliner."
        ),
        "mapping_status_initial": "No target/source selected.",
        "geometry_hint_html": "<span style='color:#8b949e;'>Preview + Transform place parts.</span>",
        "geometry_hint_tooltip": (
            "Use preview + Transform for placement. Advanced routing controls original PAC draw-slot assignment."
        ),
        "advanced_part_transform": "Advanced Part Transform",
    }


def mapping_route_control_text() -> dict[str, str]:
    return {
        "replace": "Replace Target",
        "add": "Add To Target",
        "remove_source": "Remove From Target",
        "remove_target": "Remove Original Part",
        "clear_replacement": "Clear Replacement",
        "clear_all": "Clear All",
        "replace_object": "MeshRoutingReplaceButton",
        "add_object": "MeshRoutingAddButton",
        "remove_source_object": "MeshRoutingRemoveSourceButton",
        "remove_target_object": "MeshRoutingRemoveTargetButton",
        "replace_tooltip": "Set the selected original target to exactly the selected replacement source.",
        "add_tooltip": "Append the selected replacement source to the selected original target.",
        "remove_source_tooltip": "Remove the selected replacement source from the selected original target.",
        "remove_target_tooltip": (
            "Remove the selected original target part from output and mark its DDS sidecar references for pruning "
            "when possible."
        ),
        "clear_replacement_tooltip": (
            "Clear only the replacement source selection and preview highlight without changing mappings."
        ),
        "clear_all_tooltip": (
            "Clear original, replacement, and target row selections/highlighting without changing mappings."
        ),
    }


def mapping_route_button_enabled_state(*, source_index: int, target_index: int) -> dict[str, bool]:
    has_source = int(source_index) >= 0
    has_target = int(target_index) >= 0
    source_and_target = has_source and has_target
    return {
        "assign_source": source_and_target,
        "merge_source": source_and_target,
        "remove_source": source_and_target,
        "clear_target": has_target,
    }


def mapping_route_primary_button_specs(control_text: Mapping[str, object]) -> tuple[MappingRouteButtonSpec, ...]:
    return (
        MappingRouteButtonSpec(
            key="assign_source",
            label=str(control_text["replace"]),
            object_name=str(control_text["replace_object"]),
            tooltip=str(control_text["replace_tooltip"]),
            color="#238636",
        ),
        MappingRouteButtonSpec(
            key="merge_source",
            label=str(control_text["add"]),
            object_name=str(control_text["add_object"]),
            tooltip=str(control_text["add_tooltip"]),
            color="#1f6feb",
        ),
        MappingRouteButtonSpec(
            key="remove_source",
            label=str(control_text["remove_source"]),
            object_name=str(control_text["remove_source_object"]),
            tooltip=str(control_text["remove_source_tooltip"]),
            color="#8b949e",
        ),
        MappingRouteButtonSpec(
            key="clear_target",
            label=str(control_text["remove_target"]),
            object_name=str(control_text["remove_target_object"]),
            tooltip=str(control_text["remove_target_tooltip"]),
            color="#d29922",
        ),
    )


def mapping_route_selection_button_specs(control_text: Mapping[str, object]) -> tuple[MappingRouteSelectionButtonSpec, ...]:
    return (
        MappingRouteSelectionButtonSpec(
            key="clear_replacement",
            label=str(control_text["clear_replacement"]),
            tooltip=str(control_text["clear_replacement_tooltip"]),
        ),
        MappingRouteSelectionButtonSpec(
            key="clear_all",
            label=str(control_text["clear_all"]),
            tooltip=str(control_text["clear_all_tooltip"]),
        ),
    )


def mapping_route_button_style(object_name: object, color: object) -> str:
    return f"QPushButton#{object_name} {{ border: 1px solid {color}; padding: 3px 8px; }}"


def mapping_edit_draft_tooltip() -> str:
    return "Draft source indices. Press Enter or leave the field to apply."


def mapping_edit_placeholder_text() -> str:
    return "empty, 0, or 0, 1"


def mapping_edit_refresh_interval_ms() -> int:
    return 260


def mapping_edit_source_cell_state(
    raw_text: object,
    committed_text: object,
    *,
    has_source_indices: bool,
) -> dict[str, object]:
    return {
        "is_empty": not bool(has_source_indices),
        "foreground": "#f2cc60"
        if str(raw_text or "").strip() != str(committed_text or "").strip()
        else "#cbd5e1",
    }


def mapping_committed_source_cell_state(
    *,
    selection_ok: bool,
    has_source_indices: bool,
) -> dict[str, object]:
    return {
        "is_empty": not bool(has_source_indices),
        "foreground": "#cbd5e1" if bool(selection_ok) else "#fca5a5",
    }


def mapping_target_dds_cell_state(*, state_text: object, has_source_indices: bool) -> dict[str, object]:
    return {
        "uses_removed_target_text": str(state_text) == "Removed",
        "foreground": "#cbd5e1" if bool(has_source_indices) else "#fb923c",
    }


def mapping_target_confidence_state(mapping: object | None) -> dict[str, str]:
    if mapping is None:
        return {"text": "Manual", "color": "#94a3b8"}
    if not tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
        return {"text": "Remove Original Part", "color": "#fb923c"}
    confidence = str(getattr(mapping, "confidence_label", "") or "low").lower()
    confidence_score = float(getattr(mapping, "confidence_score", 0.0) or 0.0)
    color_by_confidence = {"high": "#86efac", "medium": "#facc15"}
    return {
        "text": f"Mapped: {confidence.title()} ({confidence_score:.1f})",
        "color": color_by_confidence.get(confidence, "#fb923c"),
    }


def mapping_target_details_text(
    target_index: int,
    target_label_text: object,
    target_role_hint: object,
    target: object,
) -> str:
    return (
        f"{int(target_index)}: {target_label_text}\n"
        f"Role: {target_role_hint}\n"
        f"{len(getattr(target, 'vertices', ()) or ()):,.0f} vertices, "
        f"{len(getattr(target, 'faces', ()) or ()):,.0f} faces"
    )


def mapping_table_chunk_row_limit() -> int:
    return 8


def mapping_table_chunk_time_budget_seconds() -> float:
    return 0.012


def mapping_table_build_start_delay_ms() -> int:
    return 25


def mapping_table_column_min_widths() -> tuple[int, ...]:
    return (150, 60, 118, 160, 68, 78, 64)


def mapping_table_column_max_widths() -> tuple[int, ...]:
    return (280, 120, 180, 320, 120, 140, 110)


def mapping_table_expand_columns() -> tuple[int, ...]:
    return (0, 3)


def mapping_table_height_fit_kwargs() -> dict[str, int]:
    return {"minimum": 96, "screen_margin": 500, "maximum": 300}


def mapping_table_filters_active(*, show_low_only: object, show_empty_only: object) -> bool:
    return bool(show_low_only or show_empty_only)


def mapping_table_confidence_matches_low_filter(confidence_text: object) -> bool:
    normalized = str(confidence_text or "").casefold()
    return "low" in normalized or "empty" in normalized or "manual" in normalized


def mapping_table_row_hidden_by_filters(
    *,
    confidence_text: object,
    is_empty: object,
    show_low_only: object,
    show_empty_only: object,
) -> bool:
    low_filter_excludes = bool(show_low_only) and not mapping_table_confidence_matches_low_filter(confidence_text)
    empty_filter_excludes = bool(show_empty_only) and not bool(is_empty)
    return bool(low_filter_excludes or empty_filter_excludes)


def mapping_table_chunk_presentation_state(
    *,
    current_rows: object,
    total_rows: object,
    show_low_only: object,
    show_empty_only: object,
) -> MappingTableChunkPresentationState:
    try:
        current = int(current_rows)
    except (TypeError, ValueError):
        current = 0
    try:
        total = int(total_rows)
    except (TypeError, ValueError):
        total = 0
    complete = current >= total
    filters_active = mapping_table_filters_active(
        show_low_only=show_low_only,
        show_empty_only=show_empty_only,
    )
    return MappingTableChunkPresentationState(
        current_rows=current,
        total_rows=total,
        filters_active=filters_active,
        fit_height=complete,
        complete=complete,
    )


def mapping_table_advanced_visibility_state(checked: object) -> MappingTableAdvancedVisibilityState:
    advanced_visible = bool(checked)
    return MappingTableAdvancedVisibilityState(
        advanced_visible=advanced_visible,
        visible_widgets=advanced_visible,
        hidden_columns=(
            (2, not advanced_visible),
            (4, advanced_visible),
            (5, advanced_visible),
            (6, advanced_visible),
        ),
        expand_part_tools=advanced_visible,
    )


def removed_target_dds_tooltip() -> str:
    return "Removed target: patched sidecar output prunes this target's DDS parameters when material sidecar patching is enabled."


def source_assignment_targets_tooltip(assigned_targets: str) -> str:
    return _source_assignment_targets_tooltip_owner(assigned_targets)


def source_assignment_state_tooltip(source_state: str) -> str:
    return _source_assignment_state_tooltip_owner(source_state)


def mapping_status_summary_html(badges: Sequence[str]) -> str:
    return (
        "<div style='font-size:0.8em; line-height:1.2; padding:4px 5px; border:1px solid #30363d; border-radius:4px; background:#0d1117;'>"
        + "".join(str(badge) for badge in tuple(badges or ()))
        + "</div>"
    )


def mapping_status_summary_badge(label: object, value: object, color: object) -> str:
    return (
        "<span style='display:inline-block; margin:1px 3px 1px 0; padding:2px 6px; "
        f"border:1px solid {color}; border-radius:3px; background:#161b22;'>"
        f"<span style='color:{color}; font-weight:700;'>{escape(str(label))}</span>"
        f"<span style='color:#f0f6fc;'> {escape(str(value or '-'))}</span>"
        "</span>"
    )


def mapping_status_summary_badges(
    *,
    source_text: object,
    target_text: object,
    action_text: object,
    action_color: object,
    dds_text: object,
    physics_text: object,
    physics_color: object,
) -> tuple[str, ...]:
    return (
        mapping_status_summary_badge("Source", source_text, "#79c0ff"),
        mapping_status_summary_badge("Target", target_text, "#d2a8ff"),
        mapping_status_summary_badge("Action", action_text, action_color),
        mapping_status_summary_badge("DDS", dds_text, mapping_status_dds_color(dds_text)),
        mapping_status_summary_badge("Physics", physics_text, physics_color),
    )


def mapping_status_selection_lines(source_text: object, target_text: object) -> tuple[str, str]:
    return (f"Selected source: {source_text}", f"Selected target: {target_text}")


def mapping_status_current_target_line(summary: object, *, selection_ok: bool) -> str:
    summary_text = str(summary)
    return (
        f"Current target: {summary_text.replace('Selected: ', '')}"
        if bool(selection_ok)
        else f"Current target error: {summary_text}"
    )


def mapping_status_action_state(
    *,
    has_target_edit: bool,
    source_index: int,
    source_indices_for_target: Sequence[int],
    preview_only_source_indices: Sequence[int],
) -> dict[str, str]:
    if bool(has_target_edit):
        source_indices = tuple(source_indices_for_target or ())
        if not source_indices:
            return {"text": "Remove target", "color": "#d29922"}
        if len(source_indices) == 1:
            return {"text": "Replace target", "color": "#3fb950"}
        return {"text": "Merge sources", "color": "#d29922"}
    if int(source_index) >= 0:
        is_preview_only = int(source_index) in tuple(preview_only_source_indices or ())
        return {
            "text": "Preview-only" if is_preview_only else "Source selected",
            "color": "#d29922" if is_preview_only else "#79c0ff",
        }
    return {"text": "Select", "color": "#8b949e"}


def mapping_status_dds_color(dds_text: object) -> str:
    return "#d29922" if str(dds_text) in {"Will prune", "Review"} else "#79c0ff"


def mapping_status_physics_color(physics_text: object) -> str:
    text = str(physics_text)
    if text == "Review":
        return "#f2cc60"
    if text == "Preserved":
        return "#7ee787"
    return "#8b949e"


def mapping_status_physics_state(
    *,
    target_index: int,
    source_indices_for_target: Sequence[int],
    target_physics_text: object,
    source_physics_text: object,
) -> dict[str, str]:
    physics_text = str(target_physics_text)
    if str(source_physics_text) != "-":
        physics_text = str(source_physics_text)
    if physics_text == "-":
        physics_text = "Preserved" if int(target_index) >= 0 and tuple(source_indices_for_target or ()) else "-"
    return {"text": physics_text, "color": mapping_status_physics_color(physics_text)}


def mapping_table_queued_progress_text(total_rows: int) -> str:
    return f"Target routing table queued: 0 / {int(total_rows):,} row(s). Preview can render while rows load."


def mapping_table_loading_progress_text(current_rows: int, total_rows: int) -> str:
    return (
        f"Target routing table loading: {int(current_rows):,} / {int(total_rows):,} row(s). "
        "Preview remains usable while this fills in."
    )


def mapping_table_ready_progress_text(total_rows: int) -> str:
    return f"Target routing table ready: {int(total_rows):,} row(s)."


def invalid_submesh_mapping_title() -> str:
    return "Invalid Submesh Mapping"


def invalid_submesh_mapping_non_numeric_message(target_index: int, part: object) -> str:
    return f"Target {int(target_index)} contains a non-numeric source index: {part}"


def invalid_submesh_mapping_missing_source_message(target_index: int, source_index: int) -> str:
    return (
        f"Target {int(target_index)} references source index {int(source_index)}, "
        "but that source does not exist or is an anchor marker."
    )


def vertex_limit_issue_display_text(issues: Sequence[object], *, max_visible: int = 8) -> str:
    issue_text = [str(issue) for issue in tuple(issues or ())]
    visible_count = max(0, int(max_visible))
    displayed = "\n".join(issue_text[:visible_count])
    remaining = len(issue_text) - visible_count
    if remaining > 0:
        displayed += f"\n... {remaining} more target(s)"
    return displayed


def mesh_replacement_too_large_title() -> str:
    return "Mesh Replacement Too Large"


def mesh_replacement_too_large_message(displayed_issues: object) -> str:
    return (
        "One or more target draw slots exceed the current 16-bit export limit.\n\n"
        f"{displayed_issues}\n\n"
        "Use the Parts tab to disable, split, or map fewer replacement sources into each target, "
        "or decimate the source mesh before importing."
    )


def geometry_mapping_summary_html(
    replacement_part_count: int,
    active_target_count: int,
    empty_target_count: int,
    *,
    session_edit_count: int = 0,
) -> str:
    appended_text = (
        "<span style='color:#8b949e;'> | </span>"
        "<span style='color:#d2a8ff; font-weight:700;'>Session edits</span>"
        f"<span style='color:#f0f6fc;'> {int(session_edit_count):,}</span>"
        if int(session_edit_count)
        else ""
    )
    return (
        "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid #2f81f7; background:#10233a;'>"
        "<span style='color:#79c0ff; font-weight:700;'>Replacement parts</span>"
        f"<span style='color:#f0f6fc;'> {int(replacement_part_count):,}</span>"
        "<span style='color:#8b949e;'> | </span>"
        "<span style='color:#7ee787; font-weight:700;'>Active targets</span>"
        f"<span style='color:#f0f6fc;'> {int(active_target_count):,}</span>"
        "<span style='color:#8b949e;'> | </span>"
        "<span style='color:#f2cc60; font-weight:700;'>Empty targets</span>"
        f"<span style='color:#f0f6fc;'> {int(empty_target_count):,}</span>"
        f"{appended_text}"
        "</div>"
    )


def output_impact_review_presentation(
    removed_targets: Sequence[str],
    used_source_count: int,
    disabled_mapped_source_count: int,
    preview_only_source_count: int,
    generated_dds_count: int,
    *,
    sidecar_enabled: bool = False,
    prune_unmapped_enabled: bool = False,
) -> dict[str, str]:
    removed_target_names = tuple(str(target) for target in removed_targets)
    removed_target_count = len(removed_target_names)
    sidecar_status = (
        "visible only"
        if sidecar_enabled and prune_unmapped_enabled
        else "prune removed"
        if removed_target_count and sidecar_enabled
        else "keep"
        if removed_target_count
        else "-"
    )
    tooltip = (
        "Removed targets: "
        + (", ".join(removed_target_names) if removed_target_names else "none")
        + f"\nReplacement sources used: {int(used_source_count):,}"
        + f"\nDisabled mapped sources ignored by final geometry: {int(disabled_mapped_source_count):,}"
        + f"\nPreview-only parts excluded: {int(preview_only_source_count):,}"
        + f"\nDDS override rows ready: {int(generated_dds_count):,}"
        + (
            "\nUnmapped original DDS parameters will be pruned unless shown as kept in the visible contract."
            if sidecar_enabled and prune_unmapped_enabled
            else ""
        )
        + (
            "\nRemoved target DDS parameters will be pruned from patched sidecars."
            if removed_target_count and sidecar_enabled
            else "\nRemoved target DDS parameters are retained unless material sidecar patching is enabled."
            if removed_target_count
            else "\nNo original targets are removed."
        )
    )
    html = (
        "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid #f2cc60; background:#211b12;'>"
        "<span style='color:#f2cc60; font-weight:700;'>Output</span>"
        f"<span style='color:#c9d1d9;'> | remove {removed_target_count:,}"
        f" | source {int(used_source_count):,}"
        f" | disabled {int(disabled_mapped_source_count):,}"
        f" | preview-only {int(preview_only_source_count):,}"
        f" | DDS {int(generated_dds_count):,}"
        f" | sidecar {escape(sidecar_status)}</span>"
        "</div>"
    )
    return {"html": html, "tooltip": tooltip}


def mapping_table_build_requested_started(state: Mapping[str, object]) -> bool:
    return bool(state.get("started"))


def mapping_table_build_mark_requested_started(state: MutableMapping[str, object]) -> None:
    state["started"] = True


__all__ = [
    "MappingRouteButtonSpec",
    "MappingRouteSelectionButtonSpec",
    "MappingTableAdvancedVisibilityState",
    "MappingTableChunkPresentationState",
    "MappingTableTargetRowState",
    "geometry_mapping_summary_html",
    "invalid_submesh_mapping_missing_source_message",
    "invalid_submesh_mapping_non_numeric_message",
    "invalid_submesh_mapping_title",
    "mapping_route_control_text",
    "mapping_route_button_style",
    "mapping_route_primary_button_specs",
    "mapping_route_selection_button_specs",
    "mapping_committed_source_cell_state",
    "mapping_edit_draft_tooltip",
    "mapping_edit_placeholder_text",
    "mapping_edit_refresh_interval_ms",
    "mapping_edit_source_cell_state",
    "mapping_status_action_state",
    "mapping_status_dds_color",
    "mapping_status_physics_color",
    "mapping_status_physics_state",
    "mapping_status_summary_badge",
    "mapping_status_summary_badges",
    "mapping_status_current_target_line",
    "mapping_status_selection_lines",
    "mapping_status_summary_html",
    "mapping_route_button_enabled_state",
    "mapping_target_dds_cell_state",
    "mapping_target_confidence_state",
    "mapping_target_details_text",
    "mapping_table_action_control_text",
    "mapping_table_build_complete",
    "mapping_table_build_can_start",
    "mapping_table_build_initial_state",
    "mapping_table_build_mark_complete",
    "mapping_table_build_mark_requested_started",
    "mapping_table_build_next_index",
    "mapping_table_build_requested_initial_state",
    "mapping_table_build_requested_started",
    "mapping_table_build_start_delay_ms",
    "mapping_table_chunk_row_limit",
    "mapping_table_chunk_time_budget_seconds",
    "mapping_table_chunk_presentation_state",
    "mapping_table_column_max_widths",
    "mapping_table_column_min_widths",
    "mapping_table_confidence_matches_low_filter",
    "mapping_table_expand_columns",
    "mapping_table_filters_active",
    "mapping_table_build_set_next_index",
    "mapping_table_height_fit_kwargs",
    "mapping_table_row_hidden_by_filters",
    "mapping_table_loading_progress_text",
    "mapping_table_queued_progress_text",
    "mapping_table_ready_progress_text",
    "mapping_table_target_row_state",
    "mesh_replacement_too_large_message",
    "mesh_replacement_too_large_title",
    "output_impact_review_presentation",
    "removed_target_dds_tooltip",
    "source_assignment_state_tooltip",
    "source_assignment_targets_tooltip",
    "suggested_mappings_by_target",
    "vertex_limit_issue_display_text",
]
