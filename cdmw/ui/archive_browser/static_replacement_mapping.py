"""Pure mapping edit helpers for static replacement."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from cdmw.ui.archive_browser.static_replacement_source_display import unique_mapping_indices


@dataclass(frozen=True)
class MappingTextValidation:
    source_indices: tuple[int, ...]
    invalid_token: str = ""
    missing_source_index: int | None = None


def _valid_source_index_set(valid_source_indices: Iterable[int]) -> set[int]:
    valid: set[int] = set()
    for raw_index in tuple(valid_source_indices or ()):
        try:
            valid.add(int(raw_index))
        except (TypeError, ValueError):
            continue
    return valid


def mapping_text_valid_source_indices(raw_text: object, valid_source_indices: Iterable[int]) -> tuple[int, ...]:
    valid = _valid_source_index_set(valid_source_indices)
    return tuple(index for index in unique_mapping_indices(str(raw_text or "")) if index in valid)


def mapping_text_has_indices(raw_text: object) -> bool:
    return bool(unique_mapping_indices(str(raw_text or "")))


def mapping_edit_committed_text(edit: object) -> str:
    committed_text = ""
    property_getter = getattr(edit, "property", None)
    if callable(property_getter):
        committed_text = str(property_getter("committed_mapping_text") or "")
    if not committed_text:
        text_getter = getattr(edit, "text", None)
        committed_text = str(text_getter() if callable(text_getter) else edit or "")
    return committed_text.strip()


def mapping_edit_indices(edit: object) -> tuple[int, ...]:
    committed_text = mapping_edit_committed_text(edit)
    return unique_mapping_indices(committed_text)


def mapping_source_indices_text(source_indices: Iterable[int]) -> str:
    return ", ".join(str(index) for index in tuple(source_indices or ()))


def mapping_indices_without_source(source_indices: Iterable[int], source_index: int) -> tuple[int, ...]:
    removed_source_index = int(source_index)
    return tuple(int(index) for index in tuple(source_indices or ()) if int(index) != removed_source_index)


def mapping_indices_for_source_target(
    source_indices: Iterable[int],
    source_index: int,
    *,
    target_matches: bool,
) -> tuple[int, ...]:
    normalized_source_index = int(source_index)
    updated = list(mapping_indices_without_source(source_indices, normalized_source_index))
    if bool(target_matches) and normalized_source_index not in updated:
        updated.append(normalized_source_index)
    return tuple(updated)


def mapping_target_index_for_edit(mapping_edits: Iterable[tuple[int, object]], edit: object) -> int:
    for candidate_target, candidate_edit in tuple(mapping_edits or ()):
        if candidate_edit is edit:
            return int(candidate_target)
    return -1


def mapping_source_target_route_state(target_index: int) -> dict[str, object]:
    normalized_target_index = int(target_index)
    preview_only = normalized_target_index < 0
    return {
        "preview_only": preview_only,
        "defer_preview": preview_only,
        "selected_target_index": -1 if preview_only else normalized_target_index,
        "pending_reason": "source unassigned" if preview_only else "",
    }


def mapping_edit_valid_source_indices(edit: object, valid_source_indices: Iterable[int]) -> tuple[int, ...]:
    valid = _valid_source_index_set(valid_source_indices)
    return tuple(index for index in mapping_edit_indices(edit) if index in valid)


def validate_mapping_text_source_indices(raw_text: object, valid_source_indices: Iterable[int]) -> MappingTextValidation:
    valid = _valid_source_index_set(valid_source_indices)
    source_indices: list[int] = []
    for raw_part in str(raw_text or "").strip().replace(",", " ").replace(";", " ").split():
        part = raw_part.strip()
        if not part:
            continue
        try:
            source_index = int(part)
        except ValueError:
            return MappingTextValidation(tuple(source_indices), invalid_token=part)
        if source_index not in valid:
            return MappingTextValidation(tuple(source_indices), missing_source_index=source_index)
        if source_index not in source_indices:
            source_indices.append(source_index)
    return MappingTextValidation(tuple(source_indices))


__all__ = [
    "MappingTextValidation",
    "mapping_edit_committed_text",
    "mapping_edit_indices",
    "mapping_edit_valid_source_indices",
    "mapping_indices_for_source_target",
    "mapping_indices_without_source",
    "mapping_source_indices_text",
    "mapping_source_target_route_state",
    "mapping_target_index_for_edit",
    "mapping_text_has_indices",
    "mapping_text_valid_source_indices",
    "validate_mapping_text_source_indices",
]
