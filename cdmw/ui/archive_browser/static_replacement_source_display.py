"""Pure source display label helpers for static replacement."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, MutableMapping, Sequence

from cdmw.ui.archive_browser.static_replacement_source_assignment_state import (
    SourceAssignmentRowState,
    source_assigned_target_indices,
    source_assignment_index,
    source_assignment_row_state,
    source_assignment_state_tooltip,
    source_assignment_targets_tooltip,
)
from cdmw.ui.archive_browser.static_replacement_source_matching import (
    source_indices_for_material_name,
    source_indices_for_route_parts,
    source_material_part_summary,
    source_renderable_indices,
)


def source_role_override_value(
    source_index: int,
    source_role_overrides: Mapping[int, object],
    source_part_adjustments: Mapping[int, object],
) -> str:
    override = str(source_role_overrides.get(source_index, "") or "").strip()
    if override:
        return override
    adjustment = source_part_adjustments.get(source_index)
    return str(getattr(adjustment, "material_role", "") or "").strip()


def source_role_label(
    source_index: int,
    replacement_mesh: object | None,
    source_role_overrides: Mapping[int, object],
    source_part_adjustments: Mapping[int, object],
    *,
    role_hint: Callable[[str], str],
) -> str:
    override = source_role_override_value(source_index, source_role_overrides, source_part_adjustments)
    if override:
        return override
    if replacement_mesh is None:
        return "unknown"
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    if source_index < 0 or source_index >= len(submeshes):
        return "unknown"
    source = submeshes[source_index]
    return role_hint(f"{getattr(source, 'name', '')} {getattr(source, 'material', '')}")


def source_index_is_enabled_renderable(
    source_index: int,
    replacement_mesh: object | None,
    source_part_adjustments: Mapping[int, object],
    *,
    is_marker_source: Callable[[object], bool],
) -> bool:
    if replacement_mesh is None:
        return False
    try:
        source_index = int(source_index)
        if source_index < 0:
            return False
        source = tuple(getattr(replacement_mesh, "submeshes", ()) or ())[source_index]
    except (TypeError, ValueError):
        return False
    except IndexError:
        return False
    if is_marker_source(source):
        return False
    adjustment = source_part_adjustments.get(source_index)
    return True if adjustment is None else bool(getattr(adjustment, "enabled", True))


def enabled_renderable_source_indices(
    source_indices: Sequence[int],
    *,
    source_index_is_enabled_renderable: Callable[[int], bool],
) -> tuple[int, ...]:
    return tuple(index for index in nonnegative_indices(source_indices) if source_index_is_enabled_renderable(index))


def mapped_source_vertex_counts(
    source_indices: Sequence[int],
    replacement_mesh: object | None,
    source_part_adjustments: Mapping[int, object],
    *,
    default_adjustment: Callable[[int], object],
    is_marker_source: Callable[[object], bool],
) -> tuple[tuple[int, int], ...]:
    if replacement_mesh is None:
        return ()
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    counts: list[tuple[int, int]] = []
    for source_index in tuple(source_indices or ()):
        if source_index < 0 or source_index >= len(submeshes):
            continue
        source = submeshes[source_index]
        if is_marker_source(source):
            continue
        adjustment = source_part_adjustments.get(source_index, default_adjustment(source_index))
        if not bool(getattr(adjustment, "enabled", False)):
            continue
        counts.append((int(source_index), len(getattr(source, "vertices", ()) or ())))
    return tuple(counts)


def mapped_target_vertex_count(
    source_indices: Sequence[int],
    replacement_mesh: object | None,
    source_part_adjustments: Mapping[int, object],
    *,
    default_adjustment: Callable[[int], object],
    is_marker_source: Callable[[object], bool],
) -> int:
    return sum(
        vertex_count
        for _source_index, vertex_count in mapped_source_vertex_counts(
            source_indices,
            replacement_mesh,
            source_part_adjustments,
            default_adjustment=default_adjustment,
            is_marker_source=is_marker_source,
        )
    )


def mapping_preserve_split_group_count(
    counts: Sequence[tuple[int, int]],
    vertex_limit: int,
    *,
    source_display_name: Callable[[int], str],
) -> tuple[int, str | None]:
    if any(vertex_count > vertex_limit for _source_index, vertex_count in counts):
        bad_source, bad_count = next(
            (source_index, vertex_count)
            for source_index, vertex_count in counts
            if vertex_count > vertex_limit
        )
        return 0, f"{source_display_name(bad_source)} has {bad_count:,} vertices (limit {vertex_limit:,})."
    group_count = 1
    group_vertices = 0
    for _source_index, vertex_count in counts:
        if group_vertices and group_vertices + vertex_count > vertex_limit:
            group_count += 1
            group_vertices = 0
        group_vertices += vertex_count
    return max(1, group_count), None


def mapping_vertex_limit_issues(
    mappings: Sequence[object],
    *,
    original_format: str,
    vertex_limit: int,
    target_display_name: Callable[[int], str],
    mapped_target_vertex_count: Callable[[Sequence[int]], int],
    preserve_split_group_count: Callable[[Sequence[int]], tuple[int, str | None]],
) -> tuple[str, ...]:
    issues: list[str] = []
    normalized_original_format = str(original_format or "").lower()
    for mapping in tuple(mappings or ()):
        source_indices = tuple(getattr(mapping, "source_submesh_indices", ()) or ())
        vertex_count = mapped_target_vertex_count(source_indices)
        if vertex_count <= vertex_limit:
            continue
        split_count, split_error = preserve_split_group_count(source_indices)
        if split_error:
            issues.append(split_error)
            continue
        target_index = int(getattr(mapping, "target_submesh_index", -1))
        if normalized_original_format == "pac" and split_count > 1:
            continue
        if normalized_original_format != "pac" and split_count > 1:
            issues.append(
                f"{target_display_name(target_index)} needs {split_count} draw sections "
                f"for {vertex_count:,} vertices, but only PAC draw-section cloning is supported."
            )
            continue
        issues.append(f"{target_display_name(target_index)} receives {vertex_count:,} vertices (limit {vertex_limit:,}).")
    return tuple(issues)


def mapping_vertex_limit_status_line(
    vertex_count: int,
    *,
    split_count: int,
    split_error: str | None,
    original_format: str,
    vertex_limit: int,
) -> str | None:
    if vertex_count <= vertex_limit:
        return None
    if not split_error and str(original_format or "").lower() == "pac" and split_count > 1:
        return f"Dense output: {vertex_count:,} vertices will export as {split_count} PAC draw sections."
    return (
        f"Vertex limit: {vertex_count:,}/{vertex_limit:,} vertices. "
        "Split, decimate, or map fewer sources into this target before continuing."
    )


def routing_effect_lines(
    target_index: int,
    source_indices: Sequence[int],
    *,
    selection_ok: bool,
    selection_summary: str,
    target_display_name: Callable[[int], str],
    source_display_name: Callable[[int], str],
    source_material_labels: Callable[[Sequence[int]], Sequence[str]],
) -> tuple[str, ...]:
    if target_index < 0:
        return (
            "Effect: select a target draw slot to see what the current routing will do.",
            "Fix path: choose a source row and target row, then replace, add, remove, or empty the target.",
        )
    target_text = target_display_name(target_index)
    if not selection_ok:
        return (
            f"Effect: {selection_summary}",
            "Fix path: type valid source row numbers from Replacement sources, separated by commas.",
        )
    source_list = [int(index) for index in source_indices]
    if not source_list:
        return (
            f"Effect: {target_text} will be removed from the output geometry.",
            "DDS/sidecar impact: original texture parameters for this target are pruned when a patched material sidecar is built.",
            "Fix path: select a replacement source and use Replace Target.",
        )
    if len(source_list) == 1:
        return (
            f"Effect: {target_text} will be replaced by {source_display_name(source_list[0])}.",
            "Texture impact: this target uses the material route shown in Materials & Textures.",
        )
    material_labels = source_material_labels(source_list)
    if len(material_labels) > 1:
        return (
            f"Effect: {target_text} merges {len(source_list):,} sources into one game draw/material slot.",
            "Texture risk: those sources appear to use different materials "
            f"({', '.join(tuple(material_labels)[:4])}); one target slot can bind only one material set.",
            "Fix path: map each material group to a different target, keep the extra part preview-only, or bake/atlas the textures first.",
        )
    return (
        f"Effect: {target_text} merges {len(source_list):,} sources into one game draw/material slot.",
        "Texture impact: the merged sources share one material/texture route; use Materials & Textures if the shared material is wrong.",
    )


def source_display_name(
    source_index: int,
    replacement_mesh: object | None,
    source_display_overrides: Mapping[int, object],
    source_display_label_cache: MutableMapping[int, str],
    source_display_duplicate_counts_cache: MutableMapping[str, int],
) -> str:
    if replacement_mesh is None:
        return f"source {source_index}"
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    if source_index < 0 or source_index >= len(submeshes):
        return f"{source_index}: invalid"
    cached_label = source_display_label_cache.get(int(source_index))
    if cached_label is not None:
        return cached_label
    override = str(source_display_overrides.get(source_index, "") or "").strip()
    if override:
        result = f"{source_index}: {override}"
        source_display_label_cache[int(source_index)] = result
        return result
    source = submeshes[source_index]
    label = getattr(source, "material", "") or getattr(source, "name", "") or f"source {source_index}"
    if not source_display_duplicate_counts_cache:
        source_display_duplicate_counts_cache.update(source_display_duplicate_counts(submeshes))
    duplicate_count = int(source_display_duplicate_counts_cache.get(str(label or "").strip().lower(), 0) or 0)
    if duplicate_count > 1:
        label = (
            f"{label} "
            f"({len(getattr(source, 'vertices', ()) or ()):,.0f}v/"
            f"{len(getattr(source, 'faces', ()) or ()):,.0f}f)"
        )
    result = f"{source_index}: {label}"
    source_display_label_cache[int(source_index)] = result
    return result


def source_display_duplicate_counts(submeshes: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in tuple(submeshes or ()):
        candidate_label = getattr(candidate, "material", "") or getattr(candidate, "name", "") or ""
        candidate_key = str(candidate_label or "").strip().lower()
        if candidate_key:
            counts[candidate_key] = int(counts.get(candidate_key, 0) or 0) + 1
    return counts


def selected_source_summary(
    raw_text: str,
    replacement_mesh: object | None,
    *,
    display_name: Callable[[int], str],
    is_marker_source: Callable[[object], bool],
) -> tuple[str, bool]:
    if replacement_mesh is None:
        return "No replacement mesh loaded.", False
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    parts = [part.strip() for part in re.split(r"[,;\s]+", raw_text or "") if part.strip()]
    if not parts:
        return "Empty target: this original draw section will not emit replacement geometry.", True
    names: list[str] = []
    for part in parts:
        try:
            source_index = int(part)
        except ValueError:
            return f"Invalid source index: {part}", False
        if source_index < 0 or source_index >= len(submeshes):
            return f"Invalid source index: {source_index}", False
        source = submeshes[source_index]
        if is_marker_source(source):
            return f"Source {source_index} is an anchor marker, not render geometry.", False
        names.append(display_name(source_index))
    return "Selected: " + " + ".join(names), True


def source_index_help_text(
    replacement_mesh: object | None,
    *,
    display_name: Callable[[int], str],
    is_marker_source: Callable[[object], bool],
) -> str:
    if replacement_mesh is None:
        return "Replacement parts used are the row numbers in Replacement sources."
    valid_sources: list[str] = []
    for source_index, source in enumerate(tuple(getattr(replacement_mesh, "submeshes", ()) or ())):
        if is_marker_source(source):
            continue
        valid_sources.append(display_name(source_index))
    examples = "; ".join(valid_sources[:12])
    if len(valid_sources) > 12:
        examples += "; ..."
    return (
        "Replacement parts used chooses which imported source rows feed this original target slot. "
        "Use one number to replace the target, comma-separated numbers to merge multiple sources, "
        "or leave blank to emit no replacement geometry for that target.\n"
        f"Available sources: {examples or '-'}"
    )


def target_display_name(target_index: int, original_mesh: object | None) -> str:
    if original_mesh is None:
        return f"{target_index}: invalid"
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if target_index < 0 or target_index >= len(submeshes):
        return f"{target_index}: invalid"
    target = submeshes[target_index]
    label = getattr(target, "material", "") or getattr(target, "name", "") or f"target {target_index}"
    return f"{target_index}: {label}"


def target_index_for_name(target_name: str, original_mesh: object | None) -> int:
    if original_mesh is None:
        return -1
    target_key = str(target_name or "").strip().lower()
    if not target_key:
        return -1
    for target_index, target in enumerate(tuple(getattr(original_mesh, "submeshes", ()) or ())):
        label = str(getattr(target, "material", "") or getattr(target, "name", "") or f"target {target_index}").strip()
        if label.lower() == target_key:
            return target_index
    return -1


def target_contract_source_indices(
    target_label_text: str,
    original_mesh: object | None,
    mapping_edits_by_target: Mapping[int, object],
    mappings_by_target: Mapping[int, object],
) -> tuple[int, ...]:
    target_index = target_index_for_name(target_label_text, original_mesh)
    if target_index < 0:
        return ()
    edit = mapping_edits_by_target.get(target_index)
    if edit is not None:
        return _mapping_indices_from_text(
            str(edit.text() if hasattr(edit, "text") else edit),
            preserve_duplicates=True,
        )
    mapping = mappings_by_target.get(target_index)
    if mapping is not None:
        return tuple(int(index) for index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()) if int(index) >= 0)
    return ()


def target_outliner_state(
    target_index: int,
    source_indices: Sequence[int],
    *,
    original_mesh: object | None,
    replacement_mesh: object | None,
    enabled_renderable_source_indices: Callable[[Sequence[int]], tuple[int, ...]],
    target_physics_status_text: Callable[[str, object], str],
) -> tuple[str, str]:
    if target_index < 0:
        return "Invalid", "#f85149"
    if not source_indices:
        return "Removed", "#fb923c"
    replacement_submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if any(source_index < 0 or replacement_mesh is None or source_index >= len(replacement_submeshes) for source_index in source_indices):
        return "Invalid", "#f85149"
    enabled_source_indices = enabled_renderable_source_indices(source_indices)
    if not enabled_source_indices:
        return "Removed", "#fb923c"
    physics = "-"
    original_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ()) if original_mesh is not None else ()
    if 0 <= target_index < len(original_submeshes):
        target = original_submeshes[target_index]
        physics = target_physics_status_text(
            str(getattr(target, "material", "") or getattr(target, "name", "") or f"target {target_index}"),
            target,
        )
    if physics == "Review":
        return "Physics", "#f2cc60"
    if len(enabled_source_indices) > 1:
        return "Merged", "#d29922"
    return "Mapped", "#3fb950"


def source_outliner_state(
    source_index: int,
    assigned_targets: Sequence[int],
    *,
    source_part_adjustments: Mapping[int, object],
    preview_only_source_indices: Sequence[int] | set[int],
    independent_output_source_indices: Sequence[int] | set[int],
    assigned_target_indices: Callable[[int], tuple[int, ...]],
) -> tuple[str, str]:
    source_index = int(source_index)
    adjustment = source_part_adjustments.get(source_index)
    if adjustment is not None and not bool(getattr(adjustment, "enabled", False)):
        return "Disabled", "#fb923c"
    if assigned_targets or assigned_target_indices(source_index):
        return "Assigned", "#3fb950"
    if source_index in preview_only_source_indices:
        return "Preview-only", "#8b949e"
    if source_index in independent_output_source_indices:
        return "Independent", "#79c0ff"
    return "Unassigned", "#d29922"


def source_outliner_label(
    source_index: int,
    replacement_mesh: object | None,
    source_display_overrides: Mapping[int, object],
    *,
    simplify_label: Callable[[str], str],
) -> str:
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if source_index < 0 or source_index >= len(submeshes):
        return f"{source_index}: source"
    source = submeshes[source_index]
    label = str(source_display_overrides.get(source_index, "") or "").strip()
    if not label:
        label = str(getattr(source, "material", "") or getattr(source, "name", "") or f"source {source_index}").strip()
    return f"Source {source_index}: {simplify_label(label)}"


def source_outliner_geometry(source_index: int, replacement_mesh: object | None) -> str:
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if source_index < 0 or source_index >= len(submeshes):
        return "-"
    source = submeshes[source_index]
    return (
        f"{len(getattr(source, 'vertices', ()) or ()):,.0f} vertices, "
        f"{len(getattr(source, 'faces', ()) or ()):,.0f} faces"
    )


def source_tree_status_text(
    state_text: str,
    state_color: str,
    dds_badge: str,
) -> tuple[str, str]:
    if dds_badge:
        return f"{state_text} | {dds_badge}", "#d29922" if dds_badge == "Route DDS" else "#3fb950"
    return state_text, state_color


def source_outliner_dds_text(
    source_index: int,
    dds_badge: str,
    *,
    source_texture_slot_count: Callable[[Sequence[int]], int],
) -> str:
    if dds_badge:
        return dds_badge
    return f"Src {source_texture_slot_count((source_index,))}"


def removed_target_dds_cell_text(
    current_dds: str,
    patch_enabled: bool | None,
) -> str:
    if current_dds in {"Sidecar unknown", "Orig 0 | Src 0"}:
        return current_dds
    if patch_enabled is True:
        return "Will prune"
    if patch_enabled is False:
        return "Kept"
    return "Orig refs"


def format_index_list(indices: Sequence[int], *, display_name: Callable[[int], str]) -> str:
    if not indices:
        return "-"
    return ", ".join(display_name(int(index)) for index in indices[:4]) + (
        f" +{len(indices) - 4}" if len(indices) > 4 else ""
    )


def nonnegative_indices(raw_indices: Sequence[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw_index in tuple(raw_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            normalized.append(index)
    return tuple(normalized)


def mapping_indices_with_appended_source(raw_text: str, source_index: int) -> tuple[int, ...]:
    parts = [part.strip() for part in re.split(r"[,;\s]+", str(raw_text or "")) if part.strip()]
    source_text = str(int(source_index))
    if source_text not in parts:
        parts.append(source_text)
    return tuple(int(part) for part in parts if str(part).strip().isdigit())


def _mapping_indices_from_text(raw_text: object, *, preserve_duplicates: bool = False) -> tuple[int, ...]:
    parsed: list[int] = []
    for raw_part in re.split(r"[,;\s]+", str(raw_text or "").strip()):
        if not raw_part:
            continue
        try:
            value = int(raw_part)
        except ValueError:
            continue
        if preserve_duplicates or value not in parsed:
            parsed.append(value)
    return tuple(parsed)


def unique_mapping_indices(raw_text: str) -> tuple[int, ...]:
    return _mapping_indices_from_text(raw_text)


def disabled_source_part_indices(source_part_adjustments: Mapping[int, object]) -> tuple[int, ...]:
    return tuple(
        sorted(
            int(source_index)
            for source_index, adjustment in source_part_adjustments.items()
            if not bool(getattr(adjustment, "enabled", False))
        )
    )


def current_source_part_adjustments(
    source_part_adjustments: Mapping[int, object],
    *,
    is_default_adjustment: Callable[[object], bool],
) -> list[object]:
    return [
        adjustment
        for _source_index, adjustment in sorted(source_part_adjustments.items())
        if not is_default_adjustment(adjustment)
    ]


def remap_source_index_collection(values: Sequence[int], index_map: Mapping[int, int]) -> set[int]:
    remapped: set[int] = set()
    for raw_index in tuple(values or ()):
        try:
            old_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        new_index = index_map.get(old_index)
        if new_index is not None and int(new_index) >= 0:
            remapped.add(int(new_index))
    return remapped


def remap_selected_source_index(value: int, index_map: Mapping[int, int]) -> int:
    try:
        old_index = int(value)
    except (TypeError, ValueError):
        return -1
    new_index = index_map.get(old_index)
    return int(new_index) if new_index is not None else -1


def remap_source_index_dict(
    values: Mapping[int, object],
    index_map: Mapping[int, int],
    *,
    copy_values: bool = False,
) -> dict[int, object]:
    remapped: dict[int, object] = {}
    for raw_index, value in dict(values or {}).items():
        try:
            old_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        new_index = index_map.get(old_index)
        if new_index is None:
            continue
        remapped[int(new_index)] = copy.deepcopy(value) if copy_values else value
    return remapped


def source_target_summary(
    source_index: int,
    mapping_edits: Sequence[tuple[int, object]],
    original_mesh: object | None,
) -> str:
    assigned_targets: list[str] = []
    if original_mesh is None:
        return "-"
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    for target_index, edit in mapping_edits:
        raw_text = str(edit.text() if hasattr(edit, "text") else edit).strip()
        if not raw_text:
            continue
        if source_index not in set(_mapping_indices_from_text(raw_text)):
            continue
        if 0 <= target_index < len(submeshes):
            target = submeshes[target_index]
            label = getattr(target, "material", "") or getattr(target, "name", "") or f"target {target_index}"
            assigned_targets.append(f"{target_index}: {label}")
    return ", ".join(assigned_targets) if assigned_targets else ""


def source_indices_for_target_name(
    target_name: str,
    mapping_edits: Sequence[tuple[int, object]],
    original_mesh: object | None,
) -> tuple[int, ...]:
    if original_mesh is None:
        return ()
    target_key = str(target_name or "").strip().lower()
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    for target_index, edit in mapping_edits:
        if target_index < 0 or target_index >= len(submeshes):
            continue
        target = submeshes[target_index]
        candidate = str(getattr(target, "material", "") or getattr(target, "name", "") or f"target {target_index}")
        if candidate.strip().lower() != target_key:
            continue
        if hasattr(edit, "property"):
            raw_text = str(edit.property("committed_mapping_text") or "")
        else:
            raw_text = ""
        if not raw_text:
            raw_text = str(edit.text() if hasattr(edit, "text") else edit)
        return unique_mapping_indices(raw_text)
    return ()


def output_impact_counts(
    mapping_edits: Sequence[tuple[int, object]],
    texture_override_rows: Sequence[Mapping[str, object]],
    *,
    parse_mapping_edit: Callable[[object], Sequence[int]],
    enabled_renderable_source_indices: Callable[[Sequence[int]], tuple[int, ...]],
    sidecar_enabled: bool,
    prune_unmapped_enabled: bool,
) -> tuple[int, int, int, int, str]:
    removed_count = 0
    used_sources: set[int] = set()
    disabled_mapped_sources: set[int] = set()
    for _target_index, edit in mapping_edits:
        source_indices = parse_mapping_edit(edit)
        enabled_source_indices = enabled_renderable_source_indices(source_indices)
        if not enabled_source_indices:
            removed_count += 1
        used_sources.update(int(index) for index in enabled_source_indices)
        disabled_mapped_sources.update(
            int(index) for index in source_indices if int(index) not in enabled_source_indices
        )
    generated_dds_count = len(
        [
            row
            for row in texture_override_rows
            if str(row.get("checked", "") or "").lower() in {"1", "true"}
            or bool(str(row.get("assigned_source", "") or row.get("suggested_source", "") or "").strip())
        ]
    )
    sidecar_status = (
        "visible only"
        if sidecar_enabled and prune_unmapped_enabled
        else "prune removed"
        if removed_count and sidecar_enabled
        else "keep"
        if removed_count
        else "-"
    )
    return removed_count, len(used_sources), len(disabled_mapped_sources), generated_dds_count, sidecar_status


def source_display_cache_revision_initial_state() -> dict[str, int]:
    return {"value": 0}


def invalidate_source_display_cache(
    label_cache: MutableMapping[int, str],
    duplicate_counts_cache: MutableMapping[str, int],
    revision_state: MutableMapping[str, int],
) -> int:
    label_cache.clear()
    duplicate_counts_cache.clear()
    next_revision = int(revision_state.get("value", 0) or 0) + 1
    revision_state["value"] = next_revision
    return next_revision


__all__ = [
    "SourceAssignmentRowState",
    "current_source_part_adjustments",
    "disabled_source_part_indices",
    "enabled_renderable_source_indices",
    "format_index_list",
    "invalidate_source_display_cache",
    "mapping_indices_with_appended_source",
    "mapping_preserve_split_group_count",
    "mapping_vertex_limit_status_line",
    "mapping_vertex_limit_issues",
    "mapped_source_vertex_counts",
    "mapped_target_vertex_count",
    "nonnegative_indices",
    "output_impact_counts",
    "removed_target_dds_cell_text",
    "remap_selected_source_index",
    "remap_source_index_collection",
    "remap_source_index_dict",
    "routing_effect_lines",
    "selected_source_summary",
    "source_assigned_target_indices",
    "source_assignment_index",
    "source_assignment_row_state",
    "source_assignment_state_tooltip",
    "source_assignment_targets_tooltip",
    "source_display_cache_revision_initial_state",
    "source_display_duplicate_counts",
    "source_display_name",
    "source_indices_for_material_name",
    "source_indices_for_route_parts",
    "source_index_is_enabled_renderable",
    "source_index_help_text",
    "source_material_part_summary",
    "source_outliner_dds_text",
    "source_outliner_geometry",
    "source_outliner_label",
    "source_outliner_state",
    "source_renderable_indices",
    "source_role_label",
    "source_role_override_value",
    "source_indices_for_target_name",
    "source_target_summary",
    "source_tree_status_text",
    "target_contract_source_indices",
    "target_display_name",
    "target_index_for_name",
    "target_outliner_state",
    "unique_mapping_indices",
]
