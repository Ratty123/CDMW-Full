"""Selected source-part mapping state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cdmw.ui.archive_browser.static_replacement_source_part_duplicate_state import (
    source_part_duplicate_output_route,
)

@dataclass(frozen=True, slots=True)
class SourcePartUnmapTargetState:
    target_index: int
    remaining_source_indices: tuple[int, ...]
    push_undo: bool


@dataclass(frozen=True, slots=True)
class SourcePartMapToTargetState:
    source_index: int
    target_index: int
    source_indices: tuple[int, ...]

    @property
    def available(self) -> bool:
        return self.source_index >= 0 and self.target_index >= 0


def _int_set(values: Sequence[int]) -> set[int]:
    normalized: set[int] = set()
    for raw_index in tuple(values or ()):
        try:
            normalized.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    return normalized


def source_part_mapping_indices_for_target(
    current_indices: Sequence[int],
    *,
    source_index: int,
    replace: bool,
) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw_index in tuple(current_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index not in normalized:
            normalized.append(index)
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        return tuple(normalized)
    if replace:
        return (normalized_source_index,)
    if normalized_source_index not in normalized:
        normalized.append(normalized_source_index)
    return tuple(normalized)


def source_part_map_to_target_state(
    *,
    source_index: object,
    target_index: object,
    current_indices: Sequence[int],
    replace: bool,
) -> SourcePartMapToTargetState:
    try:
        normalized_source_index = int(source_index)
        normalized_target_index = int(target_index)
    except (TypeError, ValueError):
        return SourcePartMapToTargetState(source_index=-1, target_index=-1, source_indices=())
    if normalized_source_index < 0 or normalized_target_index < 0:
        return SourcePartMapToTargetState(
            source_index=normalized_source_index,
            target_index=normalized_target_index,
            source_indices=(),
        )
    return SourcePartMapToTargetState(
        source_index=normalized_source_index,
        target_index=normalized_target_index,
        source_indices=source_part_mapping_indices_for_target(
            current_indices,
            source_index=normalized_source_index,
            replace=replace,
        ),
    )


def source_part_should_be_preview_only_after_unmap(
    *,
    source_index: int,
    appended_source_indices: Sequence[int],
    mapped_source_indices: Sequence[int],
) -> bool:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        return False
    appended = _int_set(appended_source_indices)
    mapped = _int_set(mapped_source_indices)
    return normalized_source_index in appended and normalized_source_index not in mapped


def source_part_unmapped_indices_for_target(
    current_indices: Sequence[int],
    *,
    source_index: int,
) -> tuple[int, ...]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    normalized: list[int] = []
    for raw_index in tuple(current_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index == normalized_source_index or index in normalized:
            continue
        normalized.append(index)
    return tuple(normalized)


def source_part_unmap_target_states(
    *,
    source_index: int,
    target_indices: Sequence[int],
    target_source_indices: Mapping[int, Sequence[int]],
) -> tuple[SourcePartUnmapTargetState, ...]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        return ()
    if normalized_source_index < 0:
        return ()
    states: list[SourcePartUnmapTargetState] = []
    for ordinal, raw_target_index in enumerate(tuple(target_indices or ())):
        try:
            target_index = int(raw_target_index)
        except (TypeError, ValueError):
            continue
        if target_index not in target_source_indices:
            continue
        states.append(
            SourcePartUnmapTargetState(
                target_index=target_index,
                remaining_source_indices=source_part_unmapped_indices_for_target(
                    target_source_indices.get(target_index, ()),
                    source_index=normalized_source_index,
                ),
                push_undo=ordinal == 0,
            )
        )
    return tuple(states)


__all__ = [
    "SourcePartMapToTargetState",
    "SourcePartUnmapTargetState",
    "source_part_duplicate_output_route",
    "source_part_map_to_target_state",
    "source_part_mapping_indices_for_target",
    "source_part_should_be_preview_only_after_unmap",
    "source_part_unmap_target_states",
    "source_part_unmapped_indices_for_target",
]
