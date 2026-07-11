"""Classification-review state rules for the Research tab."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional, Sequence

from cdmw.domain.research.contracts import (
    UnknownResolverGroup,
    UnknownResolverMember,
)
from cdmw.domain.research.classification import (
    default_unknown_resolver_label_choice,
    unknown_resolver_choice_for,
)

__all__ = [
    "UnknownResolverControlState",
    "can_accept_unknown_current_role",
    "classification_review_focus_candidates",
    "is_unknown_member_classifiable",
    "normalize_classification_review_focus_key",
    "preferred_unknown_choice_for_member",
    "primary_unknown_member",
    "semantic_subtype_for_unknown_member",
    "unknown_no_current_family_unknown_status_text",
    "unknown_no_current_role_status_text",
    "unknown_no_selected_families_unknown_status_text",
    "unknown_group_classification_text",
    "unknown_group_display_name",
    "unknown_group_empty_status_text",
    "unknown_group_filter_progress_status_text",
    "unknown_group_focus_status_text",
    "unknown_group_matches_filters",
    "unknown_group_package_text",
    "unknown_group_ready_status_text",
    "unknown_group_target_paths",
    "unknown_label_choice_index",
    "unknown_label_tuple",
    "unknown_member_local_text",
    "unknown_removed_current_file_status_text",
    "unknown_removed_family_status_text",
    "unknown_removed_selected_families_status_text",
    "unknown_resolver_control_state",
    "unknown_saved_current_file_status_text",
    "unknown_saved_current_role_status_text",
    "unknown_saved_family_status_text",
    "unknown_saved_selected_families_status_text",
    "unknown_select_dds_status_text",
    "unknown_select_families_status_text",
    "unknown_select_family_status_text",
    "wildcard_filter_matches",
]


@dataclass(frozen=True, slots=True)
class UnknownResolverControlState:
    label_combo_enabled: bool
    preview_button_enabled: bool
    accept_current_role_enabled: bool
    apply_current_file_enabled: bool
    apply_selected_enabled: bool
    apply_group_enabled: bool
    clear_current_file_enabled: bool
    clear_selected_enabled: bool
    clear_group_enabled: bool
    select_all_enabled: bool
    clear_family_selection_enabled: bool


def unknown_group_focus_status_text() -> str:
    return (
        "Workflow needs a saved local approval for the selected DDS file(s). 'Current' can be inferred from archive context; "
        "'Local' is the explicit saved approval Texture Workflow requires."
    )


def unknown_group_filter_progress_status_text(*, scanned: int, total: int, matched: int) -> str:
    return f"Filtering classification review... {scanned:,} / {total:,} scanned | {matched:,} matched"


def unknown_group_empty_status_text(
    *,
    showing_classified: bool,
    has_focus_keys: bool,
) -> str:
    if has_focus_keys:
        return (
            "No current-run unclassified DDS files matched the current Research snapshot. "
            "Scan archives or broaden the current Archive Browser view if needed."
        )
    return (
        "No review items are available in the current Research snapshot."
        if showing_classified
        else "No unresolved review items match the current filters."
    )


def unknown_group_ready_status_text(
    *,
    item_count: int,
    registry_text: str,
    showing_classified: bool,
    has_focus_keys: bool,
) -> str:
    base_text = (
        f"{item_count:,} review item(s) are available. Approved labels are stored in {registry_text}."
        if showing_classified
        else f"{item_count:,} unresolved item(s) need review. Approved labels are stored in {registry_text}."
    )
    if not has_focus_keys:
        return base_text
    return (
        base_text
        + " Showing the current run's targeted DDS files. 'Current' can be inferred from Research; "
        "'Local' is what Texture Workflow requires."
    )


def unknown_select_dds_status_text() -> str:
    return "Select a DDS file in Family Members first."


def unknown_no_current_role_status_text() -> str:
    return "The selected DDS does not currently have a concrete role to accept yet."


def unknown_select_family_status_text() -> str:
    return "Select a texture family first."


def unknown_select_families_status_text() -> str:
    return "Select one or more texture families first."


def unknown_no_current_family_unknown_status_text() -> str:
    return "No unknown DDS files remain in the current family."


def unknown_no_selected_families_unknown_status_text() -> str:
    return "No unknown DDS files remain in the selected families."


def unknown_saved_current_role_status_text(texture_type: str, semantic_subtype: str) -> str:
    return (
        f"Saved current role locally as {texture_type}/{semantic_subtype} for the selected DDS file. "
        "Refreshing Research..."
    )


def unknown_saved_current_file_status_text(texture_type: str, semantic_subtype: str) -> str:
    return f"Saved classification {texture_type}/{semantic_subtype} for the current DDS file. Refreshing Research..."


def unknown_saved_family_status_text(texture_type: str, semantic_subtype: str, updated: int) -> str:
    return (
        f"Saved classification {texture_type}/{semantic_subtype} for {updated} file(s) in the current family. "
        "Refreshing Research..."
    )


def unknown_saved_selected_families_status_text(
    texture_type: str,
    semantic_subtype: str,
    updated: int,
    group_count: int,
) -> str:
    return (
        f"Saved classification {texture_type}/{semantic_subtype} for {updated} file(s) across "
        f"{group_count} selected family/families. Refreshing Research..."
    )


def unknown_removed_current_file_status_text() -> str:
    return "Removed the saved classification override from the current DDS file. Refreshing Research..."


def unknown_removed_family_status_text(removed: int) -> str:
    return f"Removed {removed} saved classification override(s) from the current family. Refreshing Research..."


def unknown_removed_selected_families_status_text(removed: int, group_count: int) -> str:
    return (
        f"Removed {removed} saved classification override(s) across {group_count} selected family/families. "
        "Refreshing Research..."
    )


def normalize_classification_review_focus_key(path_value: str) -> str:
    return str(path_value or "").strip().replace("\\", "/").strip("/").casefold()


def classification_review_focus_candidates(path_value: str) -> set[str]:
    normalized = str(path_value or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return set()
    candidates = {normalize_classification_review_focus_key(normalized)}
    parts = normalized.split("/")
    if len(parts) > 1 and len(parts[0]) == 4 and parts[0].isdigit():
        stripped = "/".join(parts[1:]).strip("/")
        if stripped:
            candidates.add(normalize_classification_review_focus_key(stripped))
    return candidates


def wildcard_filter_matches(value: str, pattern_text: str) -> bool:
    normalized_value = str(value or "").casefold()
    normalized_pattern = str(pattern_text or "").strip().casefold()
    if not normalized_pattern:
        return True
    if "*" not in normalized_pattern and "?" not in normalized_pattern:
        normalized_pattern = f"*{normalized_pattern}*"
    return fnmatch.fnmatchcase(normalized_value, normalized_pattern)


def unknown_group_display_name(
    group: UnknownResolverGroup,
    *,
    primary_member: Optional[UnknownResolverMember],
) -> str:
    if primary_member is None:
        return group.display_name
    basename = PurePosixPath(primary_member.path).name
    extra_members = max(group.total_members - 1, 0)
    return f"{basename} (+{extra_members})" if extra_members > 0 else basename


def unknown_group_classification_text(group: UnknownResolverGroup) -> str:
    if group.unknown_count > 0:
        return group.suggestion_label or "Unknown"
    return ", ".join(group.known_kinds) if group.known_kinds else "Classified"


def unknown_group_package_text(group: UnknownResolverGroup) -> str:
    return ", ".join(group.package_labels[:2]) + ("..." if len(group.package_labels) > 2 else "")


def unknown_member_local_text(member: UnknownResolverMember) -> str:
    local_texture_type = str(member.local_texture_type or "").strip().lower()
    local_semantic_subtype = str(member.local_semantic_subtype or "").strip().lower()
    if not local_texture_type:
        return "No"
    return (
        f"Yes: {local_texture_type}/{local_semantic_subtype}"
        if local_semantic_subtype
        else f"Yes: {local_texture_type}"
    )


def primary_unknown_member(group: Optional[UnknownResolverGroup]) -> Optional[UnknownResolverMember]:
    if group is None:
        return None
    for member in group.members:
        if member.is_unknown and member.extension == ".dds":
            return member
    for member in group.members:
        if member.extension == ".dds":
            return member
    return group.members[0] if group.members else None


def is_unknown_member_classifiable(member: Optional[UnknownResolverMember]) -> bool:
    return bool(member is not None and member.extension == ".dds")


def can_accept_unknown_current_role(member: Optional[UnknownResolverMember]) -> bool:
    if not is_unknown_member_classifiable(member):
        return False
    texture_type = str(member.current_kind or "").strip().lower()
    return texture_type not in {"", "unknown", "sidecar"}


def unknown_resolver_control_state(
    *,
    has_group: bool,
    has_selected_groups: bool,
    current_member: Optional[UnknownResolverMember],
    has_rows: bool,
) -> UnknownResolverControlState:
    has_member = is_unknown_member_classifiable(current_member)
    return UnknownResolverControlState(
        label_combo_enabled=has_group,
        preview_button_enabled=has_member,
        accept_current_role_enabled=can_accept_unknown_current_role(current_member),
        apply_current_file_enabled=has_member,
        apply_selected_enabled=has_group,
        apply_group_enabled=has_selected_groups,
        clear_current_file_enabled=has_member,
        clear_selected_enabled=has_group,
        clear_group_enabled=has_selected_groups,
        select_all_enabled=has_rows,
        clear_family_selection_enabled=has_rows and has_selected_groups,
    )


def unknown_label_tuple(raw: object) -> tuple[str, str, str]:
    if isinstance(raw, tuple) and len(raw) == 3:
        return (str(raw[0]), str(raw[1]), str(raw[2]))
    return ("color_albedo", "color", "albedo")


def unknown_label_choice_index(items: Sequence[object], choice_key: str) -> int:
    for index, data in enumerate(items):
        if isinstance(data, tuple) and data and data[0] == choice_key:
            return index
    return -1


def unknown_group_matches_filters(
    group: UnknownResolverGroup,
    *,
    pending_focus_keys: set[str],
    name_filter: str,
    package_filter: str,
    primary_member: Optional[UnknownResolverMember],
) -> bool:
    if pending_focus_keys:
        if not any(
            classification_review_focus_candidates(member.path) & pending_focus_keys
            for member in group.members
            if member.extension == ".dds"
        ):
            return False
    if name_filter:
        name_candidates = [
            group.display_name,
            group.group_key,
            unknown_group_display_name(group, primary_member=primary_member),
        ]
        if primary_member is not None:
            name_candidates.append(primary_member.path)
        if not any(wildcard_filter_matches(candidate, name_filter) for candidate in name_candidates if candidate):
            return False
    if package_filter:
        if not any(wildcard_filter_matches(package_label, package_filter) for package_label in group.package_labels):
            return False
    return True


def unknown_group_target_paths(
    groups: Sequence[UnknownResolverGroup],
    *,
    unknown_only: bool,
) -> list[str]:
    target_paths: list[str] = []
    seen_paths: set[str] = set()
    for group in groups:
        for member in group.members:
            if member.extension != ".dds":
                continue
            if unknown_only and not member.is_unknown:
                continue
            if member.path in seen_paths:
                continue
            seen_paths.add(member.path)
            target_paths.append(member.path)
    return target_paths


def semantic_subtype_for_unknown_member(member: UnknownResolverMember) -> str:
    texture_type = str(member.current_kind or "").strip().lower()
    path_lower = member.path.lower()
    if texture_type == "mask":
        if any(token in path_lower for token in ("specular", "_spec", "_sp")):
            return "specular"
        if any(token in path_lower for token in ("opacity", "alpha", "_mask")):
            return "opacity_mask"
        return "mask"
    if texture_type == "color":
        return "albedo"
    if texture_type == "ui":
        return "ui"
    if texture_type == "emissive":
        return "emissive"
    if texture_type == "normal":
        return "normal"
    if texture_type == "roughness":
        return "roughness"
    if texture_type == "height":
        return "displacement"
    if texture_type == "vector":
        return "vector"
    return texture_type or "unknown"


def preferred_unknown_choice_for_member(
    member: Optional[UnknownResolverMember],
    group: Optional[UnknownResolverGroup],
) -> str:
    if member is not None:
        texture_type = str(member.current_kind or "").strip().lower()
        if texture_type and texture_type not in {"unknown", "sidecar"}:
            semantic_subtype = semantic_subtype_for_unknown_member(member)
            return unknown_resolver_choice_for(texture_type, semantic_subtype)
    if group is not None and group.suggestions:
        return group.suggestions[0].choice_key
    return default_unknown_resolver_label_choice()
