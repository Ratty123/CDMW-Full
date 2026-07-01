"""Selected source-part label and selection-context text helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourcePartSelectionContextState:
    source_index: int
    target_index: int
    source_text: str
    target_text: str
    texture_text: str
    label_text: str
    tooltip_text: str


def selected_source_indices_state(
    selected_items: Sequence[object],
    *,
    source_index_from_item: Callable[[object], int],
    fallback_source_index: object = -1,
    include_fallback: bool = True,
) -> tuple[int, ...]:
    indices: list[int] = []
    for item in tuple(selected_items or ()):
        try:
            source_index = int(source_index_from_item(item))
        except (TypeError, ValueError):
            continue
        if source_index >= 0 and source_index not in indices:
            indices.append(source_index)
    if not indices and include_fallback:
        try:
            source_index = int(fallback_source_index)
        except (TypeError, ValueError):
            source_index = -1
        if source_index >= 0:
            indices.append(source_index)
    return tuple(indices)


def selected_source_part_name_text(source_index: int, label: object, *, multi_selected_count: int = 1) -> str:
    part_label = str(label or "")
    if int(multi_selected_count) > 1:
        return f"{int(multi_selected_count):,} parts selected; primary {int(source_index)}: {part_label}"
    return f"{int(source_index)}: {part_label}"


def selected_source_part_target_text(target_summary: object, *, multi_selected_count: int = 1) -> str:
    summary = str(target_summary or "none yet")
    if int(multi_selected_count) > 1:
        return f"Transform scope is explicit source selection. Primary mapped target(s): {summary}"
    return f"Mapped target(s): {summary}"


def source_part_selection_context_label_text(
    selected_tab: str,
    source_summary: str,
    target_summary: str,
    texture_summary: str,
) -> str:
    return (
        f"{str(selected_tab or 'Setup')} | Source: {str(source_summary or 'none')} | "
        f"Target: {str(target_summary or 'none')} | Texture: {str(texture_summary or 'none')}"
    )


def source_part_selection_context_tooltip(
    source_text: str,
    target_text: str,
    texture_text: str,
) -> str:
    return f"Source: {str(source_text or 'none')}\nTarget: {str(target_text or 'none')}\nTexture: {str(texture_text or 'none')}"


def source_part_selection_texture_row_text(target: str, role: str, source_label: str) -> str:
    return f"{str(target or 'target')} / {str(role or 'DDS')} -> {str(source_label or 'keep original')}"


def source_part_selection_texture_row_context_text(
    row_state: Mapping[str, object],
    *,
    role_label_for_slot: Callable[[str], str],
    simplify_part_label: Callable[[str], str],
) -> str:
    role = role_label_for_slot(str(row_state.get("slot_kind", "") or row_state.get("original_slot_kind", "") or "material"))
    source_text = str(row_state.get("source_path", "") or row_state.get("suggested_source", "") or "").strip()
    source_label = Path(source_text).name if source_text else ""
    target = simplify_part_label(str(row_state.get("target_name", "") or "target"))
    return source_part_selection_texture_row_text(target, role, source_label)


def source_part_selection_added_texture_text(source_label: str, role_label: str, source_label_text: str) -> str:
    return f"{str(source_label or 'source')} / {str(role_label or 'Texture')} -> {str(source_label_text or 'none')}"


def source_part_selection_added_texture_context_text(
    added_source_index: object,
    added_role: str,
    source_path: object,
    *,
    source_display_name: Callable[[int], str],
    added_part_texture_role_label: Callable[[str], str],
) -> str:
    try:
        source_index = int(added_source_index)
    except (TypeError, ValueError):
        return ""
    if source_index < 0:
        return ""
    source_label = Path(str(source_path)).name if source_path else ""
    return source_part_selection_added_texture_text(
        source_display_name(source_index),
        added_part_texture_role_label(added_role),
        source_label,
    )


def source_part_selection_texture_fallback(material_name: str) -> str:
    return str(material_name or "").strip() or "none"


def _compact_context_value(value: object, *, limit: int = 46) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def source_part_selection_context_state(
    *,
    selected_tab: str,
    source_index: object,
    target_index: object,
    selected_source_highlight_indices: Sequence[int],
    selected_target_highlight_indices: Sequence[int],
    texture_text: str,
    source_display_name: Callable[[int], str],
    target_display_name: Callable[[int], str],
) -> SourcePartSelectionContextState:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    try:
        normalized_target_index = int(target_index)
    except (TypeError, ValueError):
        normalized_target_index = -1
    if normalized_source_index < 0 and selected_source_highlight_indices:
        normalized_source_index = min(int(index) for index in selected_source_highlight_indices)
    if normalized_target_index < 0 and selected_target_highlight_indices:
        normalized_target_index = min(int(index) for index in selected_target_highlight_indices)
    source_text = source_display_name(normalized_source_index) if normalized_source_index >= 0 else "none"
    target_text = target_display_name(normalized_target_index) if normalized_target_index >= 0 else "none"
    normalized_texture_text = str(texture_text or "none")
    return SourcePartSelectionContextState(
        source_index=normalized_source_index,
        target_index=normalized_target_index,
        source_text=source_text,
        target_text=target_text,
        texture_text=normalized_texture_text,
        label_text=source_part_selection_context_label_text(
            selected_tab,
            _compact_context_value(source_text),
            _compact_context_value(target_text),
            _compact_context_value(normalized_texture_text, limit=58),
        ),
        tooltip_text=source_part_selection_context_tooltip(source_text, target_text, normalized_texture_text),
    )


__all__ = [
    "SourcePartSelectionContextState",
    "selected_source_indices_state",
    "selected_source_part_name_text",
    "selected_source_part_target_text",
    "source_part_selection_added_texture_context_text",
    "source_part_selection_added_texture_text",
    "source_part_selection_context_state",
    "source_part_selection_context_label_text",
    "source_part_selection_context_tooltip",
    "source_part_selection_texture_fallback",
    "source_part_selection_texture_row_context_text",
    "source_part_selection_texture_row_text",
]
