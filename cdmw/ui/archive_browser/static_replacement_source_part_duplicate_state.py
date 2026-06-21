"""Selected source-part duplicate state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePartDuplicateRouteState:
    available: bool
    source_index: int
    new_index: int
    mapped_target_indices: tuple[int, ...]
    output_route: str
    undo_label: str
    copy_suffix: str
    status_text: str


@dataclass(frozen=True, slots=True)
class SourcePartDuplicatePresentationState:
    role_override: str
    display_override: str

def source_part_duplicate_available(
    *,
    source_index: int,
    source_count: int,
    has_base_mesh: bool,
) -> bool:
    try:
        normalized_source_index = int(source_index)
        normalized_source_count = max(0, int(source_count))
    except (TypeError, ValueError):
        return False
    return bool(has_base_mesh and 0 <= normalized_source_index < normalized_source_count)


def source_part_duplicate_role_override(existing_role: object, fallback_role: object) -> str:
    return str(existing_role or fallback_role or "").strip()


def source_part_duplicate_display_override(source_label: object, copy_suffix: object) -> str:
    label = str(source_label or "").strip()
    suffix = str(copy_suffix or "").strip()
    return f"{label} ({suffix})" if suffix else label


def source_part_duplicate_undo_label(*, mirrored: bool) -> str:
    return "Mirror duplicate source part" if mirrored else "Duplicate source part"


def source_part_duplicate_copy_suffix(*, mirrored: bool) -> str:
    return "mirrored copy" if mirrored else "copy"


def source_part_duplicate_status(*, mirrored: bool, source_index: int, new_index: int) -> str:
    action = "Mirrored duplicate" if mirrored else "Duplicated"
    return f"{action} source part {int(source_index)} as {int(new_index)}."


def _int_tuple(values: Sequence[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw_index in tuple(values or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index not in normalized:
            normalized.append(index)
    return tuple(normalized)


def _int_set(values: Sequence[int]) -> set[int]:
    return set(_int_tuple(values))


def source_part_duplicate_output_route(
    *,
    source_index: int,
    mapped_target_indices: Sequence[int],
    independent_output_source_indices: Sequence[int],
    preview_only_source_indices: Sequence[int],
) -> str:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        return ""
    if normalized_source_index in _int_set(independent_output_source_indices):
        return "independent"
    if normalized_source_index in _int_set(preview_only_source_indices) or not _int_tuple(mapped_target_indices):
        return "preview"
    return ""


def source_part_duplicate_route_state(
    *,
    mirrored: bool,
    source_index: object,
    source_count: int,
    has_base_mesh: bool,
    new_index: int,
    mapped_target_indices: Sequence[int],
    independent_output_source_indices: Sequence[int],
    preview_only_source_indices: Sequence[int],
) -> SourcePartDuplicateRouteState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    try:
        normalized_new_index = int(new_index)
    except (TypeError, ValueError):
        normalized_new_index = -1
    mapped_targets = _int_tuple(mapped_target_indices)
    output_route = source_part_duplicate_output_route(
        source_index=normalized_source_index,
        mapped_target_indices=mapped_targets,
        independent_output_source_indices=independent_output_source_indices,
        preview_only_source_indices=preview_only_source_indices,
    )
    return SourcePartDuplicateRouteState(
        available=source_part_duplicate_available(
            source_index=normalized_source_index,
            source_count=source_count,
            has_base_mesh=has_base_mesh,
        ),
        source_index=normalized_source_index,
        new_index=normalized_new_index,
        mapped_target_indices=mapped_targets,
        output_route=output_route,
        undo_label=source_part_duplicate_undo_label(mirrored=mirrored),
        copy_suffix=source_part_duplicate_copy_suffix(mirrored=mirrored),
        status_text=source_part_duplicate_status(
            mirrored=mirrored,
            source_index=normalized_source_index,
            new_index=normalized_new_index,
        ),
    )


def source_part_duplicate_presentation_state(
    *,
    existing_role: object,
    fallback_role: object,
    source_label: object,
    copy_suffix: object,
) -> SourcePartDuplicatePresentationState:
    return SourcePartDuplicatePresentationState(
        role_override=source_part_duplicate_role_override(existing_role, fallback_role),
        display_override=source_part_duplicate_display_override(source_label, copy_suffix),
    )


__all__ = [
    "SourcePartDuplicatePresentationState",
    "SourcePartDuplicateRouteState",
    "source_part_duplicate_available",
    "source_part_duplicate_copy_suffix",
    "source_part_duplicate_display_override",
    "source_part_duplicate_output_route",
    "source_part_duplicate_presentation_state",
    "source_part_duplicate_role_override",
    "source_part_duplicate_route_state",
    "source_part_duplicate_status",
    "source_part_duplicate_undo_label",
]
