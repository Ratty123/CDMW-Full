"""Selected source-part assignment dialog text helpers for static replacement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentImportState:
    appended_indices: tuple[int, ...]
    total_vertices: int
    total_faces: int
    matched_texture_count: int
    has_texture_files: bool
    texture_warning: bool
    dense_warning: bool
    detail_lines: tuple[str, ...]
    message_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentApplyState:
    assignments_by_target: dict[int, tuple[int, ...]]
    preview_indices: tuple[int, ...]
    attached_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentSummaryState:
    title: str
    summary_lines: tuple[str, ...]
    show_texture_warning: bool
    show_dense_warning: bool


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentTargetOption:
    label: str
    target_index: int


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentRowSpec:
    source_index: int
    geometry_text: str
    tooltip: str
    default_target: int
    target_options: tuple[SourcePartAssignmentTargetOption, ...]


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentButtonState:
    add_all_text: str
    add_all_enabled: bool
    add_all_tooltip: str
    assign_order_enabled: bool
    textures_visible: bool


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentHighlightState:
    source_index: int
    target_index: int
    target_source_indices: tuple[int, ...]
    target_original_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourcePartAssignmentRouteState:
    route: str
    assignments_by_target: dict[int, tuple[int, ...]]
    preview_indices: tuple[int, ...]
    attached_indices: tuple[int, ...]
    open_textures: bool
    cancel_import: bool


def source_part_assignment_dialog_text() -> dict[str, str]:
    return {
        "window_title": "Assign Added Mesh Parts",
        "high_density_title": "High-density mesh import",
        "added_parts_title": "Added mesh parts",
        "default_target_summary": "Default: attach to the selected target when one is selected.",
        "preview_only_summary": "Rows left as Preview only are not final-exportable in this pass.",
        "texture_warning": (
            "No texture files were discovered. Route textures in Materials & Textures before final output."
        ),
        "dense_warning": (
            "Dense source: final static output supports about 65,535 vertices per draw section. "
            "PAC builds can split under-limit parts into cloned draw sections; reduce any single part above the limit."
        ),
        "preview_only_combo": "Preview only",
        "attach_to_target_prefix": "Attach to ",
        "apply_button": "Apply Attachments",
        "attach_all_current": "Attach All To Current",
        "attach_all_current_fallback": "Attach all to current target",
        "attach_all_current_tooltip_prefix": "Attach every imported source row to ",
        "assign_by_order": "Assign By Order",
        "open_textures": "Open Textures",
        "preview_only_button": "Preview Only",
        "cancel_import": "Cancel Import",
        "cancel_import_tooltip": "Remove the newly imported parts and return to the previous Geometry state.",
    }


def source_part_assignment_tree_headers() -> tuple[str, str, str]:
    return ("Added source", "Geometry", "Assign to target")


def source_part_assignment_primary_target(
    *,
    selected_target_index: object,
    selected_original_index: object,
    target_count: int,
) -> int:
    try:
        target_index = int(selected_target_index)
    except (TypeError, ValueError):
        target_index = -1
    if target_index < 0:
        try:
            target_index = int(selected_original_index)
        except (TypeError, ValueError):
            target_index = -1
    try:
        normalized_target_count = max(0, int(target_count))
    except (TypeError, ValueError):
        normalized_target_count = 0
    return target_index if 0 <= target_index < normalized_target_count else -1


def source_part_assignment_summary_state(
    *,
    import_state: SourcePartAssignmentImportState,
    source_name: object,
    placement_note: str = "",
    discovered_texture_count: int = 0,
    text: dict[str, str] | None = None,
) -> SourcePartAssignmentSummaryState:
    copy = text or source_part_assignment_dialog_text()
    summary_lines = [
        f"{len(import_state.appended_indices):,} part(s) from {source_name}",
        copy["default_target_summary"],
    ]
    if placement_note:
        summary_lines.append(f"Placement: {placement_note}.")
    try:
        texture_count = max(0, int(discovered_texture_count or 0))
    except (TypeError, ValueError):
        texture_count = 0
    if import_state.has_texture_files:
        summary_lines.append(f"Textures: {texture_count:,} detected; route in Textures.")
    summary_lines.append(copy["preview_only_summary"])
    return SourcePartAssignmentSummaryState(
        title=copy["high_density_title"] if import_state.dense_warning else copy["added_parts_title"],
        summary_lines=tuple(summary_lines),
        show_texture_warning=bool(import_state.texture_warning),
        show_dense_warning=bool(import_state.dense_warning),
    )


def source_part_assignment_row_specs(
    *,
    appended_indices: Sequence[int],
    replacement_sources: Sequence[object],
    source_display_names: Sequence[str],
    target_display_names: Sequence[str],
    primary_target: int,
    text: dict[str, str] | None = None,
) -> tuple[SourcePartAssignmentRowSpec, ...]:
    copy = text or source_part_assignment_dialog_text()
    sources = tuple(replacement_sources or ())
    source_names = tuple(str(name) for name in tuple(source_display_names or ()))
    target_names = tuple(str(name) for name in tuple(target_display_names or ()))
    try:
        requested_primary_target = int(primary_target)
    except (TypeError, ValueError):
        requested_primary_target = -1
    default_target = requested_primary_target if 0 <= requested_primary_target < len(target_names) else -1
    options = (SourcePartAssignmentTargetOption(copy["preview_only_combo"], -1),) + tuple(
        SourcePartAssignmentTargetOption(f"{copy['attach_to_target_prefix']}{target_name}", target_index)
        for target_index, target_name in enumerate(target_names)
    )
    rows: list[SourcePartAssignmentRowSpec] = []
    for raw_index in tuple(appended_indices or ()):
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if not 0 <= source_index < len(sources):
            continue
        source = sources[source_index]
        display_name = source_names[source_index] if source_index < len(source_names) else f"Source {source_index}"
        rows.append(
            SourcePartAssignmentRowSpec(
                source_index=source_index,
                geometry_text=(
                    f"{len(getattr(source, 'vertices', ()) or ()):,.0f} vertices, "
                    f"{len(getattr(source, 'faces', ()) or ()):,.0f} faces"
                ),
                tooltip=str(getattr(source, "material", "") or getattr(source, "name", "") or ""),
                default_target=default_target,
                target_options=options,
            )
        )
    return tuple(rows)


def source_part_assignment_button_state(
    *,
    primary_target: int,
    target_count: int,
    texture_warning: bool,
    current_target_name: str = "",
    text: dict[str, str] | None = None,
) -> SourcePartAssignmentButtonState:
    copy = text or source_part_assignment_dialog_text()
    try:
        normalized_target_count = max(0, int(target_count))
    except (TypeError, ValueError):
        normalized_target_count = 0
    has_current_target = 0 <= int(primary_target) < normalized_target_count
    tooltip = ""
    if has_current_target:
        tooltip = f"{copy['attach_all_current_tooltip_prefix']}{current_target_name}."
    return SourcePartAssignmentButtonState(
        add_all_text=copy["attach_all_current"] if has_current_target else copy["attach_all_current_fallback"],
        add_all_enabled=has_current_target,
        add_all_tooltip=tooltip,
        assign_order_enabled=normalized_target_count > 0,
        textures_visible=bool(texture_warning),
    )


def source_part_assignment_target_index(raw_target_index: object) -> int:
    try:
        return int(raw_target_index)
    except (TypeError, ValueError):
        return -1


def source_part_assignment_target_for_source(
    row_targets: Sequence[tuple[int, int]],
    source_index: int,
) -> int:
    try:
        selected_source = int(source_index)
    except (TypeError, ValueError):
        return -1
    for raw_source_index, raw_target_index in tuple(row_targets or ()):
        try:
            row_source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if row_source_index == selected_source:
            return source_part_assignment_target_index(raw_target_index)
    return -1


def source_part_assignment_apply_state(
    *,
    row_targets: Sequence[tuple[int, int]],
    target_count: int,
) -> SourcePartAssignmentApplyState:
    try:
        normalized_target_count = max(0, int(target_count))
    except (TypeError, ValueError):
        normalized_target_count = 0
    assignments: dict[int, list[int]] = {}
    preview_indices: list[int] = []
    for raw_source_index, raw_target_index in tuple(row_targets or ()):
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        target_index = source_part_assignment_target_index(raw_target_index)
        if target_index == -1:
            preview_indices.append(source_index)
        elif 0 <= target_index < normalized_target_count:
            assignments.setdefault(target_index, []).append(source_index)
    assignments_by_target = {target: tuple(indices) for target, indices in assignments.items()}
    attached_indices = tuple(index for indices in assignments_by_target.values() for index in indices)
    return SourcePartAssignmentApplyState(
        assignments_by_target=assignments_by_target,
        preview_indices=tuple(preview_indices),
        attached_indices=attached_indices,
    )


def source_part_assignment_highlight_state(
    *,
    source_index: object,
    target_index: object | None,
    mapped_source_indices: Sequence[int] = (),
) -> SourcePartAssignmentHighlightState:
    try:
        normalized_source = int(source_index)
    except (TypeError, ValueError):
        normalized_source = -1
    if target_index is None:
        normalized_target = -1
        target_original_indices: tuple[int, ...] = ()
        target_source_indices: tuple[int, ...] = ()
    else:
        normalized_target = source_part_assignment_target_index(target_index)
        target_original_indices = (normalized_target,) if normalized_target >= 0 else ()
        collected = [normalized_source] if normalized_target >= 0 and normalized_source >= 0 else []
        for raw_mapped_source in tuple(mapped_source_indices or ()):
            try:
                mapped_source = int(raw_mapped_source)
            except (TypeError, ValueError):
                continue
            if mapped_source >= 0 and mapped_source not in collected:
                collected.append(mapped_source)
        target_source_indices = tuple(collected)
    return SourcePartAssignmentHighlightState(
        source_index=normalized_source,
        target_index=normalized_target,
        target_source_indices=target_source_indices,
        target_original_indices=target_original_indices,
    )


def source_part_assignment_route_state(
    *,
    action: str,
    appended_indices: Sequence[int],
    primary_target: int,
    target_count: int,
    row_targets: Sequence[tuple[int, int]] = (),
) -> SourcePartAssignmentRouteState:
    normalized_action = str(action or "").strip() or "cancel"
    appended = tuple(int(index) for index in tuple(appended_indices or ()))
    try:
        normalized_target_count = max(0, int(target_count))
    except (TypeError, ValueError):
        normalized_target_count = 0
    try:
        normalized_primary_target = int(primary_target)
    except (TypeError, ValueError):
        normalized_primary_target = -1

    if normalized_action == "textures":
        return SourcePartAssignmentRouteState("textures", {}, appended, (), True, False)
    if normalized_action == "preview":
        return SourcePartAssignmentRouteState("preview", {}, appended, (), False, False)
    if normalized_action == "cancel":
        return SourcePartAssignmentRouteState("cancel", {}, (), (), False, True)
    if normalized_action == "add_all" and 0 <= normalized_primary_target < normalized_target_count:
        return SourcePartAssignmentRouteState(
            "add_all",
            {normalized_primary_target: appended},
            (),
            appended,
            False,
            False,
        )
    if normalized_action == "by_order" and normalized_target_count > 0:
        start_target = normalized_primary_target if 0 <= normalized_primary_target < normalized_target_count else 0
        assignments: dict[int, list[int]] = {}
        for offset, source_index in enumerate(appended):
            target_index = min(normalized_target_count - 1, start_target + offset)
            assignments.setdefault(target_index, []).append(source_index)
        return SourcePartAssignmentRouteState(
            "by_order",
            {target: tuple(indices) for target, indices in assignments.items()},
            (),
            appended,
            False,
            False,
        )
    if normalized_action == "apply":
        apply_state = source_part_assignment_apply_state(
            row_targets=row_targets,
            target_count=normalized_target_count,
        )
        return SourcePartAssignmentRouteState(
            "apply",
            apply_state.assignments_by_target,
            apply_state.preview_indices,
            apply_state.attached_indices,
            False,
            False,
        )
    return SourcePartAssignmentRouteState("cancel", {}, (), (), False, True)


def source_part_added_import_message_lines(
    *,
    part_count: int,
    source_name: str,
    placement_note: str = "",
    texture_count: int = 0,
    texture_warning: bool = False,
    dense_warning: bool = False,
) -> list[str]:
    lines = [
        f"Added {int(part_count):,} mesh part(s) from {source_name}.",
        "Attach imported parts to an original draw/material target to make them exportable.",
    ]
    if placement_note:
        lines.append(f"Placement: {placement_note}.")
    if texture_count > 0:
        lines.append(
            f"Detected {int(texture_count):,} texture file(s). "
            "They are available in Textures and can be routed through the selected target material."
        )
    if texture_warning:
        lines.append(
            "No texture files were discovered for these parts. They will preview with a neutral material until you "
            "route textures in Materials & Textures."
        )
    if dense_warning:
        lines.append(
            "This import is very dense. PAC output can preserve separate under-limit source parts by cloning draw "
            "sections; PAM output still needs reduction or fewer sources per target."
        )
    lines.append("Preview-only parts are visible in this session but are blocked from final PAC/PAM export.")
    return lines


def source_part_assignment_import_state(
    *,
    source_indices: Sequence[int],
    replacement_sources: Sequence[object],
    source_name: str,
    placement_note: str = "",
    discovered_texture_count: int = 0,
    matched_texture_indices: Sequence[int] = (),
    vertex_limit: int = 65535,
) -> SourcePartAssignmentImportState:
    sources = tuple(replacement_sources or ())
    source_count = len(sources)
    appended_indices: list[int] = []
    for raw_index in tuple(source_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < source_count and index not in appended_indices:
            appended_indices.append(index)
    matched = set()
    for raw_index in tuple(matched_texture_indices or ()):
        try:
            matched.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    texture_count = max(0, int(discovered_texture_count or 0))
    has_texture_files = texture_count > 0
    try:
        limit = max(0, int(vertex_limit))
    except (TypeError, ValueError):
        limit = 0
    detail_lines: list[str] = []
    total_vertices = 0
    total_faces = 0
    dense_source = False
    matched_texture_count = 0
    for ordinal, index in enumerate(appended_indices, start=1):
        source = sources[index]
        vertices = tuple(getattr(source, "vertices", ()) or ())
        faces = tuple(getattr(source, "faces", ()) or ())
        vertex_count = len(vertices)
        face_count = len(faces)
        total_vertices += vertex_count
        total_faces += face_count
        dense_source = dense_source or bool(limit and vertex_count >= limit)
        if index in matched:
            matched_texture_count += 1
        material = getattr(source, "material", "") or getattr(source, "name", "") or "unnamed"
        detail_lines.append(
            f"{ordinal}. Source {index}: {material} - {vertex_count:,.0f} vertices, {face_count:,.0f} faces"
        )
    texture_warning = not has_texture_files and matched_texture_count <= 0
    dense_warning = bool((limit and total_vertices >= limit) or dense_source)
    message_lines = tuple(
        source_part_added_import_message_lines(
            part_count=len(appended_indices),
            source_name=str(source_name or ""),
            placement_note=placement_note,
            texture_count=texture_count if has_texture_files else 0,
            texture_warning=texture_warning,
            dense_warning=dense_warning,
        )
    )
    return SourcePartAssignmentImportState(
        appended_indices=tuple(appended_indices),
        total_vertices=total_vertices,
        total_faces=total_faces,
        matched_texture_count=matched_texture_count,
        has_texture_files=has_texture_files,
        texture_warning=texture_warning,
        dense_warning=dense_warning,
        detail_lines=tuple(detail_lines),
        message_lines=message_lines,
    )


def source_part_added_export_blocker_title() -> str:
    return "Attach Added Mesh Parts"


def source_part_added_export_blocker_message(displayed_sources: str) -> str:
    return (
        "Added mesh parts must be attached to an original target before final PAC/PAM export. "
        "Preview-only parts are shown in Live Alignment Preview only.\n\n"
        f"{displayed_sources}\n\n"
        "Select the added part in Geometry, choose a target, then use Add To Target."
    )


__all__ = [
    "SourcePartAssignmentApplyState",
    "SourcePartAssignmentButtonState",
    "SourcePartAssignmentHighlightState",
    "SourcePartAssignmentImportState",
    "SourcePartAssignmentRouteState",
    "SourcePartAssignmentRowSpec",
    "SourcePartAssignmentSummaryState",
    "SourcePartAssignmentTargetOption",
    "source_part_added_export_blocker_message",
    "source_part_added_export_blocker_title",
    "source_part_added_import_message_lines",
    "source_part_assignment_dialog_text",
    "source_part_assignment_apply_state",
    "source_part_assignment_button_state",
    "source_part_assignment_highlight_state",
    "source_part_assignment_import_state",
    "source_part_assignment_primary_target",
    "source_part_assignment_route_state",
    "source_part_assignment_row_specs",
    "source_part_assignment_summary_state",
    "source_part_assignment_target_for_source",
    "source_part_assignment_target_index",
    "source_part_assignment_tree_headers",
]
