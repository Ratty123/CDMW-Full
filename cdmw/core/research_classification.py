"""Research classification grouping and review detail."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence

from cdmw.core.archive_format import archive_entry_role
from cdmw.core.classification_registry import get_registered_texture_classification
from cdmw.core.common import raise_if_cancelled
from cdmw.core.research_archive_analysis import (
    TEXTURE_IMAGE_EXTENSIONS,
    TEXTURE_SIDECAR_EXTENSIONS,
    build_archive_research_snapshot,
    derive_texture_group_key,
)
from cdmw.domain.research.classification import (
    _default_semantic_subtype_for_type,
    unknown_resolver_choice_for,
    unknown_resolver_choice_label,
)
from cdmw.domain.research.contracts import (
    TextureClassificationRow,
    TextureSetGroup,
    UnknownResolverGroup,
    UnknownResolverMember,
    UnknownResolverSuggestion,
)
from cdmw.models import ArchiveEntry

def _build_unknown_resolver_suggestions(
    group_key: str,
    *,
    members: Sequence[UnknownResolverMember],
    sidecar_paths: Sequence[str],
    stop_event: Optional[object] = None,
) -> List[UnknownResolverSuggestion]:
    raise_if_cancelled(stop_event, "Research refresh cancelled.")
    suggestions: List[UnknownResolverSuggestion] = []
    seen: set[str] = set()
    known_counter = Counter(
        member.current_kind
        for member in members
        if member.current_kind and member.current_kind != "unknown" and member.extension == ".dds"
    )
    normalized_group = group_key.replace("\\", "/").lower()
    joined_member_paths = " ".join(member.path.lower() for member in members)

    def add_suggestion(texture_type: str, semantic_subtype: str, confidence: int, reason: str) -> None:
        choice_key = unknown_resolver_choice_for(texture_type, semantic_subtype)
        if choice_key in seen:
            return
        seen.add(choice_key)
        suggestions.append(
            UnknownResolverSuggestion(
                choice_key=choice_key,
                texture_type=texture_type,
                semantic_subtype=semantic_subtype,
                confidence=int(confidence),
                reason=reason,
            )
        )

    if known_counter:
        dominant_kind, dominant_count = known_counter.most_common(1)[0]
        add_suggestion(
            dominant_kind,
            _default_semantic_subtype_for_type(dominant_kind),
            92 if dominant_count > 1 else 82,
            f"Family already contains {dominant_count} classified {dominant_kind} companion map(s).",
        )

    if "/ui/" in normalized_group or "/hud/" in normalized_group:
        add_suggestion("ui", "ui", 80, "Group path looks UI-related.")
    if any(token in joined_member_paths for token in ("emissive", "_emi", "_emc", "_glow", "_emit")):
        add_suggestion("emissive", "emissive", 78, "Member names contain emissive/glow hints.")
    if any(token in joined_member_paths for token in ("roughness", "smoothness", "gloss", "glossiness")):
        add_suggestion("roughness", "roughness", 80, "Member names contain explicit roughness/gloss/smoothness hints.")
    if any(token in joined_member_paths for token in ("displacement", "dmap", "height", "disp")):
        add_suggestion("height", "displacement", 80, "Member names contain explicit height/displacement hints.")
    if any(token in joined_member_paths for token in ("specular", "_spec", "_sp")):
        add_suggestion("mask", "specular", 74, "Member names contain specular hints.")
    if any(token in joined_member_paths for token in ("opacity", "alpha", "_mask")):
        add_suggestion("mask", "opacity_mask", 72, "Member names contain alpha/opacity mask hints.")

    if not suggestions:
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        variant_like_count = sum(1 for member in members if re.search(r"(?<=\d)[a-z]\.dds$", member.path, re.IGNORECASE))
        if variant_like_count >= 1 or sidecar_paths:
            add_suggestion(
                "color",
                "albedo",
                66,
                "Texture family has visible variant or sidecar evidence, which often indicates a color/albedo set.",
            )
        else:
            add_suggestion(
                "color",
                "albedo",
                58,
                "Texture path has no strong technical hint; visible color/albedo is the safest first review guess.",
            )
        add_suggestion(
            "mask",
            "mask",
            34,
            "If the texture behaves like grayscale support data, review it as a generic mask instead.",
        )

    suggestions.sort(key=lambda suggestion: (-suggestion.confidence, suggestion.choice_key))
    return suggestions[:3]


def _build_unknown_resolver_member_suggestions(
    group_key: str,
    selected_member_path: str,
    *,
    members: Sequence[UnknownResolverMember],
    sidecar_paths: Sequence[str],
    stop_event: Optional[object] = None,
) -> List[UnknownResolverSuggestion]:
    raise_if_cancelled(stop_event, "Research refresh cancelled.")
    normalized_selected = selected_member_path.replace("\\", "/").lower()
    selected_member = next(
        (
            member
            for member in members
            if member.extension == ".dds" and member.path.replace("\\", "/").lower() == normalized_selected
        ),
        None,
    )
    if selected_member is None:
        return _build_unknown_resolver_suggestions(
            group_key,
            members=members,
            sidecar_paths=sidecar_paths,
            stop_event=stop_event,
        )

    suggestions: List[UnknownResolverSuggestion] = []
    seen: set[str] = set()
    sibling_known_counter = Counter(
        member.current_kind
        for member in members
        if member.extension == ".dds"
        and member.path.replace("\\", "/").lower() != normalized_selected
        and member.current_kind
        and member.current_kind != "unknown"
    )
    normalized_group = group_key.replace("\\", "/").lower()
    selected_path_lower = selected_member.path.lower()

    def add_suggestion(texture_type: str, semantic_subtype: str, confidence: int, reason: str) -> None:
        choice_key = unknown_resolver_choice_for(texture_type, semantic_subtype)
        if choice_key in seen:
            return
        seen.add(choice_key)
        suggestions.append(
            UnknownResolverSuggestion(
                choice_key=choice_key,
                texture_type=texture_type,
                semantic_subtype=semantic_subtype,
                confidence=int(confidence),
                reason=reason,
            )
        )

    if selected_member.current_kind and selected_member.current_kind not in {"unknown", "sidecar"}:
        add_suggestion(
            selected_member.current_kind,
            _default_semantic_subtype_for_type(selected_member.current_kind),
            96,
            f"Selected DDS is currently classified in Research as {selected_member.current_kind}.",
        )

    if selected_member.role_hint == "ui":
        add_suggestion("ui", "ui", 90, "Selected DDS has a UI archive role hint.")
    elif selected_member.role_hint == "normal":
        add_suggestion("normal", "normal", 90, "Selected DDS has a normal-map archive role hint.")
    elif selected_member.role_hint == "material":
        add_suggestion("mask", "mask", 72, "Selected DDS has a material/technical archive role hint.")

    if sibling_known_counter:
        dominant_kind, dominant_count = sibling_known_counter.most_common(1)[0]
        add_suggestion(
            dominant_kind,
            _default_semantic_subtype_for_type(dominant_kind),
            78 if dominant_count > 1 else 70,
            f"Family already contains {dominant_count} classified {dominant_kind} companion map(s).",
        )

    if "/ui/" in normalized_group or "/hud/" in normalized_group:
        add_suggestion("ui", "ui", 76, "Group path looks UI-related.")
    if any(token in selected_path_lower for token in ("emissive", "_emi", "_emc", "_glow", "_emit")):
        add_suggestion("emissive", "emissive", 78, "Selected DDS name contains emissive/glow hints.")
    if any(token in selected_path_lower for token in ("roughness", "smoothness", "gloss", "glossiness")):
        add_suggestion("roughness", "roughness", 80, "Selected DDS name contains roughness/gloss hints.")
    if any(token in selected_path_lower for token in ("displacement", "dmap", "height", "disp")):
        add_suggestion("height", "displacement", 80, "Selected DDS name contains height/displacement hints.")
    if any(token in selected_path_lower for token in ("specular", "_spec", "_sp")):
        add_suggestion("mask", "specular", 74, "Selected DDS name contains specular hints.")
    if any(token in selected_path_lower for token in ("opacity", "alpha", "_mask")):
        add_suggestion("mask", "opacity_mask", 72, "Selected DDS name contains alpha/opacity mask hints.")

    if not suggestions:
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        variant_like_count = sum(1 for member in members if re.search(r"(?<=\d)[a-z]\.dds$", member.path, re.IGNORECASE))
        if variant_like_count >= 1 or sidecar_paths:
            add_suggestion(
                "color",
                "albedo",
                66,
                "Texture family has visible variant or sidecar evidence, which often indicates a color/albedo set.",
            )
        else:
            add_suggestion(
                "color",
                "albedo",
                58,
                "Texture path has no strong technical hint; visible color/albedo is the safest first review guess.",
            )
        add_suggestion(
            "mask",
            "mask",
            34,
            "If the texture behaves like grayscale support data, review it as a generic mask instead.",
        )

    suggestions.sort(key=lambda suggestion: (-suggestion.confidence, suggestion.choice_key))
    return suggestions[:3]


def build_unknown_resolver_groups(
    entries: Sequence[ArchiveEntry],
    classification_rows: Sequence[TextureClassificationRow],
    *,
    include_classified: bool = False,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Building classification review groups...",
) -> List[UnknownResolverGroup]:
    entries_by_group: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        normalized_path = entry.path.replace("\\", "/")
        if entry.extension in TEXTURE_IMAGE_EXTENSIONS or entry.extension in TEXTURE_SIDECAR_EXTENSIONS:
            entries_by_group[derive_texture_group_key(normalized_path)].append(entry)
    return _build_unknown_resolver_groups_from_grouped_entries(
        entries_by_group,
        classification_rows,
        include_classified=include_classified,
        stop_event=stop_event,
        on_progress=on_progress,
        progress_label=progress_label,
    )


def _build_unknown_resolver_groups_from_grouped_entries(
    entries_by_group: Dict[str, List[ArchiveEntry]],
    classification_rows: Sequence[TextureClassificationRow],
    *,
    include_classified: bool = False,
    stop_event: Optional[object] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    progress_label: str = "Building classification review groups...",
) -> List[UnknownResolverGroup]:
    rows_by_path = {row.path.replace("\\", "/"): row for row in classification_rows}

    groups: List[UnknownResolverGroup] = []
    group_items = list(entries_by_group.items())
    group_total = len(group_items)
    progress_interval = max(group_total // 100, 1) if group_total > 0 else 1
    for index, (group_key, group_entries) in enumerate(group_items, start=1):
        raise_if_cancelled(stop_event, "Research refresh cancelled.")
        texture_rows: List[TextureClassificationRow] = []
        for entry in group_entries:
            raise_if_cancelled(stop_event, "Research refresh cancelled.")
            if entry.extension not in TEXTURE_IMAGE_EXTENSIONS:
                continue
            normalized_path = entry.path.replace("\\", "/")
            row = rows_by_path.get(normalized_path)
            if row is None:
                continue
            texture_rows.append(row)
        if not texture_rows:
            continue
        unknown_rows = [row for row in texture_rows if row.texture_type == "unknown"]
        if not unknown_rows and not include_classified:
            if on_progress is not None and (index == group_total or index % progress_interval == 0):
                on_progress(index, group_total, f"{progress_label} {index:,} / {group_total:,}")
            continue

        members: List[UnknownResolverMember] = []
        sidecar_paths: List[str] = []
        total_dds_members = 0
        local_approval_count = 0
        for entry in sorted(group_entries, key=lambda member: member.path):
            raise_if_cancelled(stop_event, "Research refresh cancelled.")
            normalized_path = entry.path.replace("\\", "/")
            row = rows_by_path.get(normalized_path)
            if entry.extension in TEXTURE_SIDECAR_EXTENSIONS:
                sidecar_paths.append(normalized_path)
            if row is None and entry.extension not in TEXTURE_IMAGE_EXTENSIONS:
                continue
            current_kind = row.texture_type if row is not None else "sidecar"
            reason = row.reason if row is not None else "Sidecar/support file in the same family."
            registered = get_registered_texture_classification(normalized_path) if entry.extension == ".dds" else None
            if entry.extension == ".dds":
                total_dds_members += 1
                if registered is not None:
                    local_approval_count += 1
            members.append(
                UnknownResolverMember(
                    path=normalized_path,
                    package_label=entry.package_label,
                    current_kind=current_kind,
                    reason=reason,
                    role_hint=archive_entry_role(entry),
                    extension=entry.extension,
                    is_unknown=bool(row is not None and row.texture_type == "unknown"),
                    local_texture_type=str(getattr(registered, "texture_type", "") or ""),
                    local_semantic_subtype=str(getattr(registered, "semantic_subtype", "") or ""),
                )
            )

        package_labels = sorted({member.package_label for member in members})
        known_kinds = sorted({member.current_kind for member in members if member.current_kind not in {"unknown", "sidecar"}})
        suggestions = _build_unknown_resolver_suggestions(
            group_key,
            members=members,
            sidecar_paths=sidecar_paths,
            stop_event=stop_event,
        )
        top_suggestion = suggestions[0] if suggestions else None
        suggestion_label = (
            f"{unknown_resolver_choice_label(top_suggestion.choice_key)} ({top_suggestion.confidence}%)"
            if top_suggestion is not None
            else "Manual review"
        )
        groups.append(
            UnknownResolverGroup(
                group_key=group_key,
                display_name=PurePosixPath(group_key).name or group_key,
                unknown_count=len(unknown_rows),
                total_members=len([member for member in members if member.extension in TEXTURE_IMAGE_EXTENSIONS]),
                package_labels=package_labels,
                known_kinds=known_kinds,
                sidecar_paths=sidecar_paths,
                suggestion_label=suggestion_label,
                members=members,
                suggestions=suggestions,
                local_approval_state=(
                    "All"
                    if total_dds_members > 0 and local_approval_count >= total_dds_members
                    else "Partial"
                    if local_approval_count > 0
                    else "None"
                ),
            )
        )
        if on_progress is not None and (index == group_total or index % progress_interval == 0):
            on_progress(index, group_total, f"{progress_label} {index:,} / {group_total:,}")

    groups.sort(key=lambda group: (-group.unknown_count, group.display_name.casefold()))
    raise_if_cancelled(stop_event, "Research refresh cancelled.")
    return groups


def build_unknown_resolver_detail(
    group: UnknownResolverGroup,
    selected_member_path: str,
    *,
    entries_by_path: Dict[str, ArchiveEntry],
) -> str:
    normalized_selected = selected_member_path.replace("\\", "/")
    selected_entry = entries_by_path.get(normalized_selected)
    member_suggestions = _build_unknown_resolver_member_suggestions(
        group.group_key,
        normalized_selected,
        members=group.members,
        sidecar_paths=group.sidecar_paths,
    )
    detail_lines: List[str] = [
        f"Group: {group.display_name}",
        f"Group key: {group.group_key}",
        f"Unknown members: {group.unknown_count}",
        f"Texture members in family: {group.total_members}",
        f"Known family kinds: {', '.join(group.known_kinds) if group.known_kinds else 'none'}",
        f"Packages: {', '.join(group.package_labels[:4])}" + (" ..." if len(group.package_labels) > 4 else ""),
        "",
        "Suggested labels:",
    ]
    if member_suggestions:
        for suggestion in member_suggestions:
            detail_lines.append(
                f"- {unknown_resolver_choice_label(suggestion.choice_key)} ({suggestion.confidence}%): {suggestion.reason}"
            )
    else:
        detail_lines.append("- No strong automatic suggestion. Manual review is recommended.")

    if group.sidecar_paths:
        detail_lines.extend(["", "Family sidecar/reference files:"])
        for sidecar_path in group.sidecar_paths[:6]:
            detail_lines.append(f"- {sidecar_path}")
        if len(group.sidecar_paths) > 6:
            detail_lines.append(f"- ... and {len(group.sidecar_paths) - 6} more")

    detail_lines.extend(["", f"Selected member: {normalized_selected}"])
    registered = get_registered_texture_classification(normalized_selected)
    if selected_entry is not None:
        detail_lines.append(f"- Package: {selected_entry.package_label}")
        detail_lines.append(f"- Role hint: {archive_entry_role(selected_entry) or 'none'}")
        detail_lines.append(f"- Stored size: {selected_entry.orig_size:,} bytes")
        if registered is not None:
            detail_lines.append(
                f"- Saved local approval: yes ({registered.texture_type}/{registered.semantic_subtype})"
            )
        else:
            detail_lines.append("- Saved local approval: no (current classification may only be inferred from naming/family context)")
        if selected_entry.extension == ".dds":
            detail_lines.append("- DDS header and image are loaded by the background preview worker.")
            detail_lines.append("- Review the selected DDS in the center preview pane for visual confirmation.")
    else:
        detail_lines.append("- Entry metadata unavailable in the current archive view.")
        if registered is not None:
            detail_lines.append(
                f"- Saved local approval: yes ({registered.texture_type}/{registered.semantic_subtype})"
            )
        else:
            detail_lines.append("- Saved local approval: no")

    detail_lines.extend(
        [
            "",
            "Approval flow:",
            "- Choose the label that best matches the selected DDS file or its family.",
            "- Save Current Role Locally stores the selected DDS file's current inferred Research role as the local approval.",
            "- Apply To Current File stores an override only for the selected DDS file.",
            "- Apply To Unknown Files In Current Family bulk-applies the label only to unresolved DDS files in that family.",
            "- Apply To Unknown Files In Selected Families does the same across all selected families in the review queue.",
            "- Clear Current File removes the override only from the selected DDS file.",
            "- Clear Current Family and Clear Selected Families remove saved overrides for all DDS files in those families.",
            "- The member list is only shown for the rare families that contain multiple texture files.",
            "- The approval is stored locally and reused by Research and texture policy in future runs.",
        ]
    )
    return "\n".join(detail_lines)


def bundle_texture_sets(entries: Sequence[ArchiveEntry], *, limit: int = 2000) -> List[TextureSetGroup]:
    snapshot = build_archive_research_snapshot(entries, classification_limit=0, group_limit=limit)
    groups = snapshot.get("texture_groups", [])
    return groups if isinstance(groups, list) else []


__all__ = [
    "build_unknown_resolver_detail",
    "build_unknown_resolver_groups",
    "bundle_texture_sets",
]
