"""Selected source-part material grouping and target assignment rules."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence


def source_part_target_sources_initial_state(target_count: int) -> dict[int, list[int]]:
    return {target_index: [] for target_index in range(max(0, int(target_count)))}


def source_part_group_target_score(
    *,
    group_label: str,
    source_texts: Sequence[str],
    target_index: int,
    target_label: str,
    assigned_targets: set[int],
    source_initial_targets: Mapping[str, Mapping[int, int]],
    semantic_tokens: Callable[[str], set[str]],
) -> float:
    group_tokens = semantic_tokens(str(group_label or ""))
    target_tokens = semantic_tokens(str(target_label or ""))
    score = float(len(group_tokens & target_tokens) * 14)
    for token in group_tokens & target_tokens:
        score += min(8.0, len(token) * 0.75)
    source_target_counter = source_initial_targets.get(str(group_label or ""))
    if source_target_counter:
        score += float(source_target_counter.get(int(target_index), 0) * 45)
    for source_text in tuple(source_texts or ()):
        score += float(len(semantic_tokens(str(source_text or "")) & target_tokens) * 8)
    if int(target_index) in assigned_targets:
        score -= 10000.0
    return score


def source_part_group_initial_target_counts(
    suggested_mappings: Sequence[object],
    source_material_group_label: Callable[[int], str],
) -> dict[str, Counter[int]]:
    source_initial_targets: defaultdict[str, Counter[int]] = defaultdict(Counter)
    for mapping in tuple(suggested_mappings or ()):
        try:
            target_index = int(getattr(mapping, "target_submesh_index", -1))
        except (TypeError, ValueError):
            target_index = -1
        for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
            label = source_material_group_label(int(source_index))
            if label:
                source_initial_targets[label][target_index] += 1
    return dict(source_initial_targets)


def source_part_material_groups(
    replacement_mesh: object | None,
    source_part_adjustments: Mapping[int, object],
    *,
    source_material_group_label: Callable[[int], str],
    source_group_label_or_fallback: Callable[[int, str], str],
    is_marker_source: Callable[[object], bool],
    excluded_source_indices: Sequence[int] = (),
) -> tuple[dict[str, list[int]], dict[str, int]]:
    source_groups: dict[str, list[int]] = {}
    source_face_counts: dict[str, int] = {}
    excluded = {int(index) for index in tuple(excluded_source_indices or ())}
    for source_index, source in enumerate(getattr(replacement_mesh, "submeshes", ()) or ()):
        if int(source_index) in excluded or is_marker_source(source):
            continue
        adjustment = source_part_adjustments.get(source_index)
        if adjustment is not None and not bool(getattr(adjustment, "enabled", True)):
            continue
        label = source_group_label_or_fallback(
            source_index,
            source_material_group_label(source_index),
        )
        source_groups.setdefault(label, []).append(source_index)
        source_face_counts[label] = source_face_counts.get(label, 0) + len(getattr(source, "faces", ()) or ())
    return source_groups, source_face_counts


def source_part_group_items(
    source_groups: Mapping[str, Sequence[int]],
    source_face_counts: Mapping[str, int],
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    return tuple(
        (str(group_label), tuple(int(index) for index in source_indices))
        for group_label, source_indices in sorted(
            source_groups.items(),
            key=lambda item: (source_face_counts.get(item[0], 0), len(item[1])),
            reverse=True,
        )
    )


def source_part_group_source_texts(
    replacement_mesh: object | None,
    source_indices: Sequence[int],
) -> tuple[str, ...]:
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    source_texts: list[str] = []
    for source_index in tuple(source_indices or ()):
        try:
            index = int(source_index)
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(submeshes):
            continue
        source = submeshes[index]
        source_texts.append(f"{getattr(source, 'name', '')} {getattr(source, 'material', '')}")
    return tuple(source_texts)


def source_part_assign_groups_to_targets(
    group_items: Sequence[tuple[str, Sequence[int]]],
    *,
    target_count: int,
    score_group_for_target: Callable[[str, Sequence[int], int], float],
    assigned_targets: set[int] | None = None,
) -> tuple[dict[int, list[int]], tuple[str, ...]]:
    target_total = max(0, int(target_count))
    target_sources = source_part_target_sources_initial_state(target_total)
    assigned = assigned_targets if assigned_targets is not None else set()
    overflow_groups: list[str] = []
    for group_label, source_indices in tuple(group_items or ()):
        if target_total <= 0:
            overflow_groups.append(str(group_label))
            continue
        free_targets = [index for index in range(target_total) if index not in assigned]
        if free_targets:
            target_index = max(
                free_targets,
                key=lambda candidate: score_group_for_target(str(group_label), source_indices, candidate),
            )
            assigned.add(target_index)
            target_sources[target_index] = [int(index) for index in tuple(source_indices or ())]
            continue
        target_index = max(
            range(target_total),
            key=lambda candidate: score_group_for_target(str(group_label), source_indices, candidate),
        )
        target_sources.setdefault(target_index, []).extend(int(index) for index in tuple(source_indices or ()))
        overflow_groups.append(str(group_label))
    return target_sources, tuple(overflow_groups)


def source_part_assign_material_groups_to_targets(
    group_items: Sequence[tuple[str, Sequence[int]]],
    *,
    target_count: int,
    original_mesh: object | None,
    replacement_mesh: object | None,
    target_display_name: Callable[[int, object], str],
    source_initial_targets: Mapping[str, Mapping[int, int]],
    semantic_tokens: Callable[[str], set[str]],
) -> tuple[dict[int, list[int]], tuple[str, ...]]:
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    assigned_targets: set[int] = set()

    def _score_group_for_target(group_label: str, source_indices: Sequence[int], target_index: int) -> float:
        target = submeshes[target_index] if 0 <= int(target_index) < len(submeshes) else object()
        target_label = target_display_name(int(target_index), target) if target is not None else ""
        return source_part_group_target_score(
            group_label=group_label,
            source_texts=source_part_group_source_texts(replacement_mesh, source_indices),
            target_index=target_index,
            target_label=target_label,
            assigned_targets=assigned_targets,
            source_initial_targets=source_initial_targets,
            semantic_tokens=semantic_tokens,
        )

    return source_part_assign_groups_to_targets(
        group_items,
        target_count=target_count,
        score_group_for_target=_score_group_for_target,
        assigned_targets=assigned_targets,
    )


__all__ = [
    "source_part_assign_groups_to_targets",
    "source_part_assign_material_groups_to_targets",
    "source_part_group_initial_target_counts",
    "source_part_group_items",
    "source_part_group_source_texts",
    "source_part_group_target_score",
    "source_part_material_groups",
    "source_part_target_sources_initial_state",
]
