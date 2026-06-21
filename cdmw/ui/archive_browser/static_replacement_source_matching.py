"""Pure source matching helpers for static replacement."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence


def source_material_part_summary(
    material_name: str,
    replacement_mesh: object | None,
    *,
    texture_set_count: int,
    is_marker_source: Callable[[object], bool],
) -> str:
    material_key = str(material_name or "").strip().lower()
    matched_parts: list[str] = []
    all_parts: list[str] = []
    for source_index, source in enumerate(getattr(replacement_mesh, "submeshes", ()) or ()):
        if is_marker_source(source):
            continue
        label = str(getattr(source, "material", "") or getattr(source, "name", "") or f"source {source_index}").strip()
        display_label = f"{source_index}: {label}"
        all_parts.append(display_label)
        source_key = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip().lower()
        if material_key and (source_key == material_key or material_key in source_key or source_key in material_key):
            matched_parts.append(display_label)
    if matched_parts:
        shown = ", ".join(matched_parts[:4])
        return shown + (", ..." if len(matched_parts) > 4 else "")
    if int(texture_set_count) == 1 and all_parts:
        shown = ", ".join(all_parts[:4])
        return shown + (", ..." if len(all_parts) > 4 else "")
    return "No matching imported part"


def source_indices_for_material_name(
    material_name: str,
    replacement_mesh: object | None,
    *,
    texture_set_count: int,
    is_marker_source: Callable[[object], bool],
) -> tuple[int, ...]:
    material_key = str(material_name or "").strip().lower()
    if not material_key:
        return ()
    matched_indices: list[int] = []
    all_indices: list[int] = []
    for source_index, source in enumerate(getattr(replacement_mesh, "submeshes", ()) or ()):
        if is_marker_source(source):
            continue
        all_indices.append(source_index)
        source_key = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip().lower()
        texture_key = str(getattr(source, "texture", "") or "").strip().lower()
        if (
            source_key == material_key
            or (source_key and (material_key in source_key or source_key in material_key))
            or (texture_key and material_key in texture_key)
        ):
            matched_indices.append(source_index)
    if matched_indices:
        return tuple(dict.fromkeys(matched_indices))
    if int(texture_set_count) == 1 and all_indices:
        return tuple(all_indices)
    return ()


def source_renderable_indices(
    replacement_mesh: object | None,
    source_part_adjustments: Mapping[int, object] | None = None,
    *,
    is_marker_source: Callable[[object], bool],
    excluded_source_indices: Sequence[int] | set[int] = (),
    require_enabled: bool = True,
) -> tuple[int, ...]:
    excluded = {int(index) for index in tuple(excluded_source_indices or ())}
    adjustments = dict(source_part_adjustments or {})
    return tuple(
        source_index
        for source_index, source in enumerate(getattr(replacement_mesh, "submeshes", ()) or ())
        if source_index not in excluded
        and not is_marker_source(source)
        and (not require_enabled or bool(getattr(adjustments.get(source_index), "enabled", True)))
    )


def source_indices_for_route_parts(
    source_part_names: Sequence[object],
    replacement_mesh: object | None,
    *,
    source_material_name: str = "",
    source_display_name: Callable[[int], str],
    source_indices_for_material_name: Callable[[str], Sequence[int]],
    is_marker_source: Callable[[object], bool],
) -> tuple[int, ...]:
    route_part_keys = {
        str(part or "").strip().lower()
        for part in tuple(source_part_names or ())
        if str(part or "").strip() and str(part or "").strip() != "-"
    }
    if not route_part_keys or replacement_mesh is None:
        return tuple(source_indices_for_material_name(source_material_name))
    matched_indices: list[int] = []
    for source_index, source in enumerate(getattr(replacement_mesh, "submeshes", ()) or ()):
        if is_marker_source(source):
            continue
        candidate_keys = {
            str(getattr(source, "material", "") or "").strip().lower(),
            str(getattr(source, "name", "") or "").strip().lower(),
            str(getattr(source, "texture", "") or "").strip().lower(),
        }
        display_label = str(source_display_name(source_index) or "").strip().lower()
        if display_label:
            candidate_keys.add(display_label)
            candidate_keys.add(re.sub(r"^\s*\d+\s*:\s*", "", display_label))
        if route_part_keys & {key for key in candidate_keys if key}:
            matched_indices.append(source_index)
    if matched_indices:
        return tuple(dict.fromkeys(matched_indices))
    return tuple(source_indices_for_material_name(source_material_name))


__all__ = [
    "source_indices_for_material_name",
    "source_indices_for_route_parts",
    "source_material_part_summary",
    "source_renderable_indices",
]
