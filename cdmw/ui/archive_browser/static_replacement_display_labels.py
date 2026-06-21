"""Static replacement source and target display-label helpers."""

from __future__ import annotations

from collections.abc import Mapping


def source_fallback_label(source_index: int) -> str:
    return f"source {int(source_index)}"


def target_fallback_name(target_index: int) -> str:
    return f"target {int(target_index)}"


def source_part_display_label(
    source_index: int,
    source: object,
    source_display_overrides: Mapping[int, object],
) -> str:
    label = str(source_display_overrides.get(int(source_index), "") or "").strip()
    if label:
        return label
    return str(
        getattr(source, "material", "")
        or getattr(source, "name", "")
        or source_fallback_label(source_index)
    ).strip()


def source_group_label_or_fallback(source_index: int, group_label: object) -> str:
    return str(group_label or source_fallback_label(source_index))


def target_submesh_display_name(target_index: int, target: object) -> str:
    return str(getattr(target, "material", "") or getattr(target, "name", "") or target_fallback_name(target_index))


__all__ = [
    "source_fallback_label",
    "source_group_label_or_fallback",
    "source_part_display_label",
    "target_fallback_name",
    "target_submesh_display_name",
]
