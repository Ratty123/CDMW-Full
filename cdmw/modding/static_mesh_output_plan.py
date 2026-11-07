"""Static mesh replacement output draw-section planning."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from copy import copy

from .mesh_parser import ParsedMesh
from .static_mesh_geometry import _is_marker_submesh
from .static_mesh_source_parts import (
    _apply_texture_uv_transform,
    _source_part_adjustments_by_index,
    _texture_uv_transform_for_submesh,
    _texture_uv_transforms_by_key,
)
from .static_mesh_types import (
    StaticMaterialAtlasRect,
    StaticMeshReplacementOptions,
    StaticOutputDrawSection,
    StaticSourcePartAdjustment,
    StaticSubmeshMapping,
)

_STATIC_REPLACEMENT_VERTEX_LIMIT = 65535
_MATERIAL_ATLAS_UV_INSET_FRACTION = 1.0 / 64.0


def _atlas_uv_transform(
    rect: StaticMaterialAtlasRect,
    *,
    padding: int = 0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    width = max(0.0, float(rect.width))
    height = max(0.0, float(rect.height))
    fraction = _MATERIAL_ATLAS_UV_INSET_FRACTION if int(padding or 0) > 0 else 0.0
    inset_u = min(width * fraction, width * 0.25)
    inset_v = min(height * fraction, height * 0.25)
    return (
        (float(rect.x) + inset_u, float(rect.y) + inset_v),
        (max(0.0, width - inset_u * 2.0), max(0.0, height - inset_v * 2.0)),
    )

def _dense_export_mode(options: StaticMeshReplacementOptions) -> str:
    mode = str(getattr(options, "dense_export_mode", "preserve_split") or "preserve_split").strip().lower()
    return mode if mode in {"preserve_split", "legacy_merge"} else "preserve_split"


def _source_vertex_count(
    replacement_mesh: ParsedMesh,
    source_index: int,
    options: StaticMeshReplacementOptions,
) -> int:
    if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
        return 0
    source = replacement_mesh.submeshes[source_index]
    if _is_marker_submesh(source):
        return 0
    adjustment = _source_part_adjustments_by_index(options.source_part_adjustments).get(
        source_index,
        StaticSourcePartAdjustment(source_index),
    )
    if not bool(adjustment.enabled):
        return 0
    return len(getattr(source, "vertices", ()) or ())


class _SourceGroup(list):
    """Source indices for one draw section, plus face ranges for split sources."""

    def __init__(self, indices: Iterable[int] = ()) -> None:
        super().__init__(indices)
        self.face_ranges: dict[int, tuple[int, int, int]] = {}
        self.vertex_count = 0


def _vertex_limit_chunks(
    source: object,
    limit: int = _STATIC_REPLACEMENT_VERTEX_LIMIT,
) -> list[tuple[int, int, int]]:
    """Split a source's faces into contiguous runs of at most ``limit`` vertices.

    Returns ``(first face, end face, distinct vertex count)`` per run. Vertices
    on a run boundary are counted in both runs, as the builder copies them.
    """
    faces = list(getattr(source, "faces", ()) or ())
    vertex_total = len(getattr(source, "vertices", ()) or ())
    cache_key = (len(faces), vertex_total, int(limit))
    cached = getattr(source, "_cdmw_vertex_limit_chunks", None)
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == cache_key:
        return list(cached[1])
    chunks: list[tuple[int, int, int]] = []
    marks = [-1] * vertex_total
    start = 0
    used = 0
    for face_index, face in enumerate(faces):
        fresh = [vertex for vertex in dict.fromkeys(face) if 0 <= vertex < vertex_total and marks[vertex] != start]
        if used and used + len(fresh) > limit:
            chunks.append((start, face_index, used))
            start = face_index
            used = 0
            fresh = [vertex for vertex in dict.fromkeys(face) if 0 <= vertex < vertex_total]
        for vertex in fresh:
            marks[vertex] = start
        used += len(fresh)
    if used or not chunks:
        chunks.append((start, len(faces), used))
    try:
        setattr(source, "_cdmw_vertex_limit_chunks", (cache_key, tuple(chunks)))
    except (AttributeError, TypeError):
        pass
    return chunks


def _group_vertex_count(
    replacement_mesh: ParsedMesh,
    group: Sequence[int],
    options: StaticMeshReplacementOptions,
) -> int:
    ranges = getattr(group, "face_ranges", None) or {}
    total = 0
    for source_index in group:
        if int(source_index) in ranges:
            source = replacement_mesh.submeshes[int(source_index)]
            start, end, _faces = ranges[int(source_index)]
            total += next(
                (count for first, last, count in _vertex_limit_chunks(source) if (first, last) == (start, end)),
                _source_vertex_count(replacement_mesh, int(source_index), options),
            )
        else:
            total += _source_vertex_count(replacement_mesh, int(source_index), options)
    return total


def _source_split_warning(source_index: int, vertex_count: int, piece_count: int) -> str:
    return (
        f"Replacement source {source_index} has {vertex_count:,} vertices, more than the "
        f"{_STATIC_REPLACEMENT_VERTEX_LIMIT:,} a PAC draw section can hold; it will be split into "
        f"{piece_count} draw sections."
    )


def _partition_source_indices_for_vertex_limit(
    replacement_mesh: ParsedMesh,
    source_indices: Iterable[int],
    options: StaticMeshReplacementOptions,
    warnings: list[str] | None = None,
) -> tuple[list[list[int]], list[str]]:
    """Pack sources into draw-section groups under the 16-bit vertex limit.

    A source that is too large on its own is split into contiguous face runs,
    each emitted as its own group with ``face_ranges`` set for that source.
    """
    groups: list[list[int]] = []
    errors: list[str] = []
    current_group = _SourceGroup()

    def flush() -> None:
        nonlocal current_group
        if current_group:
            groups.append(current_group)
        current_group = _SourceGroup()

    for raw_source_index in source_indices:
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        vertex_count = _source_vertex_count(replacement_mesh, source_index, options)
        if vertex_count <= 0:
            continue
        if vertex_count > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            source = replacement_mesh.submeshes[source_index]
            face_total = len(getattr(source, "faces", ()) or ())
            chunks = _vertex_limit_chunks(source)
            if len(chunks) > 1 and warnings is not None:
                warnings.append(_source_split_warning(source_index, vertex_count, len(chunks)))
            for start, end, chunk_vertices in chunks:
                if source_index in current_group or (
                    current_group and current_group.vertex_count + chunk_vertices > _STATIC_REPLACEMENT_VERTEX_LIMIT
                ):
                    flush()
                current_group.append(source_index)
                current_group.face_ranges[source_index] = (start, end, face_total)
                current_group.vertex_count += chunk_vertices
            continue
        if current_group and current_group.vertex_count + vertex_count > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            flush()
        current_group.append(source_index)
        current_group.vertex_count += vertex_count
    flush()
    if not groups:
        groups.append([])
    return groups, errors


def _face_ranges_for_groups(groups: Iterable[Sequence[int]]) -> dict[int, tuple[int, int, int]]:
    ranges: dict[int, tuple[int, int, int]] = {}
    for group in groups:
        ranges.update(getattr(group, "face_ranges", None) or {})
    return ranges


def _complete_swap_atlas_mode(options: StaticMeshReplacementOptions) -> str:
    mode = str(getattr(options, "complete_swap_atlas_mode", "auto_when_needed") or "auto_when_needed").strip().lower()
    return mode if mode in {"auto_when_needed", "off", "block"} else "auto_when_needed"


def _atlas_rects_for_source_groups(
    groups: Sequence[tuple[list[int], str]],
) -> tuple[StaticMaterialAtlasRect, ...]:
    visible_groups = [(list(indices), str(label or "").strip()) for indices, label in groups if indices]
    if len(visible_groups) <= 1:
        return ()
    columns = max(1, math.ceil(math.sqrt(len(visible_groups))))
    rows = max(1, math.ceil(len(visible_groups) / columns))
    rects: list[StaticMaterialAtlasRect] = []
    for index, (source_indices, label) in enumerate(visible_groups):
        column = index % columns
        row = index // columns
        rects.append(
            StaticMaterialAtlasRect(
                source_material_name=label,
                source_submesh_indices=tuple(int(source_index) for source_index in source_indices),
                x=float(column) / float(columns),
                y=float(row) / float(rows),
                width=1.0 / float(columns),
                height=1.0 / float(rows),
            )
        )
    return tuple(rects)


def _reserve_tiled_material_slots(
    assigned_groups: dict[int, list[tuple[list[int], str]]],
    replacement_mesh: ParsedMesh,
    options: StaticMeshReplacementOptions,
) -> str:
    """Keep repeating UVs out of atlases without adding PAC runtime draw slots."""
    if not any(len(groups) > 1 for groups in assigned_groups.values()):
        return ""
    transforms = _texture_uv_transforms_by_key(options.texture_uv_transforms)
    tiled_sources = set()
    for index in {index for groups in assigned_groups.values() for indices, _ in groups for index in indices}:
        source = replacement_mesh.submeshes[index]
        transform = _texture_uv_transform_for_submesh(source, transforms)
        if transform is not None:
            source = copy(source)
            _apply_texture_uv_transform(source, transform)
        if any(float(value) < -0.0001 or float(value) > 1.0001 for uv in source.uvs for value in uv):
            tiled_sources.add(index)
    if not any(len(groups) > 1 and any(tiled_sources.intersection(indices) for indices, _ in groups)
               for groups in assigned_groups.values()):
        return ""
    groups = [(target, group) for target, values in assigned_groups.items() for group in values]
    # Reserve a whole slot for each tiled material before packing ordinary UVs.
    groups.sort(key=lambda item: not bool(tiled_sources.intersection(item[1][0])))
    routed, vertex_counts, reserved = {}, {}, set()
    for preferred, group in groups:
        indices, _label = group
        tiled = bool(tiled_sources.intersection(indices))
        count = _group_vertex_count(replacement_mesh, indices, options)
        candidates = [preferred, *(target for target in assigned_groups if target != preferred)]
        candidates.sort(key=lambda target: target in routed)
        target = next((target for target in candidates
                       if target not in reserved and (not tiled or target not in routed)
                       and vertex_counts.get(target, 0) + count <= _STATIC_REPLACEMENT_VERTEX_LIMIT), None)
        if target is None:
            return (f"Cannot preserve tiled material groups in {len(assigned_groups)} runtime material slot(s) "
                    "within the PAC vertex limit. Choose a template with more material slots or reduce the source materials.")
        routed.setdefault(target, []).append(group)
        vertex_counts[target] = vertex_counts.get(target, 0) + count
        if tiled:
            reserved.add(target)
    assigned_groups.clear()
    assigned_groups.update(routed)
    return ""


def plan_static_output_draw_sections(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
    options: StaticMeshReplacementOptions | None = None,
) -> tuple[list[StaticOutputDrawSection], list[str], list[str]]:
    """Plan export draw sections, preserving dense source parts when possible."""
    normalized_options = options or StaticMeshReplacementOptions()
    mode = _dense_export_mode(normalized_options)
    mappings_by_target = {mapping.target_submesh_index: mapping for mapping in mappings}
    original_sections: list[StaticOutputDrawSection] = []
    cloned_sections: list[StaticOutputDrawSection] = []
    warnings: list[str] = []
    errors: list[str] = []

    source_material_key_counts = Counter(
        str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip().lower()
        for source in tuple(getattr(replacement_mesh, "submeshes", ()) or ())
        if str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip()
    )
    source_adjustments_by_index = _source_part_adjustments_by_index(normalized_options.source_part_adjustments)

    def _source_adjustment_material_key(source_index: int, material_key: str) -> str:
        if not material_key:
            return ""
        adjustment = source_adjustments_by_index.get(source_index)
        if adjustment is None:
            return ""
        role = str(getattr(adjustment, "material_role", "") or "").strip().lower()
        glow_rgb = tuple(getattr(adjustment, "emissive_color_rgb", ()) or ())
        material_tint = tuple(getattr(adjustment, "material_tint_rgb", ()) or ())
        has_material_adjustment = (
            abs(float(getattr(adjustment, "material_brightness", 0.0) or 0.0)) > 0.0001
            or abs(float(getattr(adjustment, "material_contrast", 0.0) or 0.0)) > 0.0001
            or abs(float(getattr(adjustment, "material_saturation", 0.0) or 0.0)) > 0.0001
            or abs(float(getattr(adjustment, "material_gamma", 1.0) or 1.0) - 1.0) > 0.0001
            or bool(material_tint)
            or abs(float(getattr(adjustment, "material_colourise_strength", 0.0) or 0.0)) > 0.0001
        )
        if not role and not glow_rgb and not has_material_adjustment:
            return ""
        if not has_material_adjustment and int(source_material_key_counts.get(material_key, 0) or 0) <= 1:
            return ""
        return f"__source_part_{source_index}_{material_key}"

    def _source_group_label(source_indices: list[int], fallback: str) -> str:
        for source_index in source_indices:
            if 0 <= source_index < len(replacement_mesh.submeshes):
                source = replacement_mesh.submeshes[source_index]
                explicit_key = str(getattr(source, "cdmw_source_texture_set_key", "") or "").strip()
                if explicit_key:
                    return explicit_key
                material_key = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip().lower()
                adjustment_key = _source_adjustment_material_key(source_index, material_key)
                if adjustment_key:
                    return adjustment_key
                label = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip()
                if label:
                    return label
        return fallback

    if bool(getattr(normalized_options, "complete_external_swap", False)):
        source_owned_target_names = [
            str(name or "").strip()
            for name in tuple(getattr(normalized_options, "source_owned_target_names", ()) or ())
        ]

        def _runtime_name_for_target_index(target_index: int, fallback: str) -> str:
            if 0 <= target_index < len(source_owned_target_names) and source_owned_target_names[target_index]:
                return source_owned_target_names[target_index]
            return fallback

        assigned_groups: dict[int, list[tuple[list[int], str]]] = {}
        extra_groups: list[tuple[int, list[int], str]] = []
        mapped_empty_targets: set[int] = set()
        atlas_mode = _complete_swap_atlas_mode(normalized_options)

        for target_index, target in enumerate(original_mesh.submeshes):
            mapping = mappings_by_target.get(target_index)
            source_indices = list(mapping.source_submesh_indices if mapping is not None else [])
            target_name = (
                str(getattr(mapping, "target_submesh_name", "") or "").strip()
                if mapping is not None
                else ""
            ) or target.material or target.name or f"target {target_index}"
            grouped_sources: dict[str, list[int]] = {}
            for source_index in source_indices:
                if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
                    continue
                source = replacement_mesh.submeshes[source_index]
                label = _source_group_label([source_index], f"source {source_index}")
                grouped_sources.setdefault(label.lower(), []).append(source_index)
            runtime_target_name = _runtime_name_for_target_index(target_index, target_name)
            source_group_batches: list[list[int]] = []
            for source_group in grouped_sources.values():
                groups, group_errors = _partition_source_indices_for_vertex_limit(
                    replacement_mesh,
                    source_group,
                    normalized_options,
                    warnings,
                )
                errors.extend(group_errors)
                source_group_batches.extend(group for group in groups if group)
            if not source_group_batches:
                if mapping is not None:
                    mapped_empty_targets.add(target_index)
                continue
            assigned_groups[target_index] = [(source_group_batches[0], _source_group_label(source_group_batches[0], target_name))]
            for group in source_group_batches[1:]:
                extra_groups.append((target_index, group, _source_group_label(group, target_name)))

        free_target_indices = [
            index
            for index in range(len(original_mesh.submeshes))
            if index not in assigned_groups and index not in mapped_empty_targets
        ]
        for source_target_index, group, source_label in extra_groups:
            if not free_target_indices:
                split_sources = sorted(
                    index
                    for index in (getattr(group, "face_ranges", None) or {})
                    if len(_vertex_limit_chunks(replacement_mesh.submeshes[index])) > 1
                )
                if split_sources:
                    # Atlasing a split piece back into its slot would exceed the limit again.
                    source_index = split_sources[0]
                    vertex_count = _source_vertex_count(replacement_mesh, source_index, normalized_options)
                    errors.append(
                        f"Replacement source {source_index} has {vertex_count:,} vertices and "
                        f"must be split across more than one draw section, but this template has no free material "
                        f"slot for the extra piece. Decimate it below {_STATIC_REPLACEMENT_VERTEX_LIMIT:,} vertices, "
                        "or choose a template with more material slots."
                    )
                    continue
                if atlas_mode == "auto_when_needed":
                    assigned_groups.setdefault(source_target_index, []).append((group, source_label))
                    continue
                target = original_mesh.submeshes[source_target_index]
                runtime_name = _runtime_name_for_target_index(
                    source_target_index,
                    target.material or target.name or f"target {source_target_index}",
                )
                errors.append(
                    "PAC runtime ABI has only "
                    f"{len(original_mesh.submeshes):,} safe draw slot(s); atlas or explicit slot mapping required "
                    f"because {runtime_name} receives additional source material group {source_label}."
                )
                continue
            assigned_index = free_target_indices.pop(0)
            assigned_groups[assigned_index] = [(group, source_label)]

        if atlas_mode == "auto_when_needed":
            tiled_error = _reserve_tiled_material_slots(assigned_groups, replacement_mesh, normalized_options)
            if tiled_error:
                errors.append(tiled_error)

        for target_index, target in enumerate(original_mesh.submeshes):
            target_name = target.material or target.name or f"target {target_index}"
            runtime_target_name = _runtime_name_for_target_index(target_index, target.name or target_name)
            runtime_material_name = target.material or target.name or target_name
            assigned = assigned_groups.get(target_index)
            if not assigned:
                original_sections.append(
                    StaticOutputDrawSection(
                        output_index=0,
                        target_submesh_index=target_index,
                        target_submesh_name=runtime_target_name,
                        source_submesh_indices=[],
                        target_material_slot_index=target_index,
                        clone_source_target_index=target_index,
                        donor_material_name=target.material or target.name or target_name,
                        vertex_count=0,
                        is_cloned_section=False,
                        runtime_slot_name=target.name or target_name,
                        runtime_material_name=runtime_material_name,
                        lod_strategy="preserve_runtime_abi_placeholder",
                        section0_preserved=True,
                    )
                )
                continue
            merged_face_ranges = _face_ranges_for_groups(group for group, _source_label in assigned if group)
            merged_vertex_count = sum(
                _group_vertex_count(replacement_mesh, group, normalized_options)
                for group, _source_label in assigned
                if group
            )
            merged_groups = [(list(group), str(source_label or "").strip()) for group, source_label in assigned if group]
            merged_source_indices = [
                source_index
                for group, _source_label in merged_groups
                for source_index in group
            ]
            atlas_rects = _atlas_rects_for_source_groups(merged_groups)
            source_label = (
                " + ".join(label for _group, label in merged_groups if label)
                if atlas_rects
                else (merged_groups[0][1] if merged_groups else "")
            )
            if atlas_rects:
                vertex_count = merged_vertex_count
                if vertex_count > _STATIC_REPLACEMENT_VERTEX_LIMIT:
                    errors.append(
                        f"Atlas/bake target {runtime_target_name} would contain {vertex_count:,} vertices; "
                        f"PAC draw sections support at most {_STATIC_REPLACEMENT_VERTEX_LIMIT:,}."
                    )
            original_sections.append(
                StaticOutputDrawSection(
                    output_index=0,
                    target_submesh_index=target_index,
                    target_submesh_name=runtime_target_name,
                    source_submesh_indices=list(merged_source_indices),
                    target_material_slot_index=target_index,
                    clone_source_target_index=target_index,
                    donor_material_name=runtime_target_name,
                    vertex_count=merged_vertex_count,
                    is_cloned_section=False,
                    runtime_slot_name=target.name or target_name,
                    runtime_material_name=runtime_material_name,
                    source_material_name=source_label,
                    lod_strategy="preserve_runtime_abi_decimated_from_lod0",
                    section0_preserved=True,
                    atlas_source_material_names=tuple(rect.source_material_name for rect in atlas_rects),
                    atlas_rects=atlas_rects,
                    atlas_material_name=f"{runtime_target_name}_baked_atlas" if atlas_rects else "",
                    source_face_ranges=merged_face_ranges,
                )
            )
        planned = original_sections
        for output_index, section in enumerate(planned):
            section.output_index = output_index
        if planned:
            warnings.append(
                "Complete source-owned swap will preserve the original PAC runtime draw ABI and route source material groups into existing slots: "
                f"{sum(1 for section in planned if section.source_submesh_indices)} source-owned section(s); "
                f"{sum(1 for section in planned if not section.source_submesh_indices)} original runtime slot placeholder(s)."
            )
            atlas_sections = [section for section in planned if tuple(getattr(section, "atlas_rects", ()) or ())]
            for section in atlas_sections:
                warnings.append(
                    "Complete source-owned swap will atlas/bake "
                    f"{', '.join(section.atlas_source_material_names)} into runtime slot {section.target_submesh_name}."
                )
        else:
            errors.append("Complete source-owned swap found no replacement source material groups to export.")
        return planned, warnings, errors

    for target_index, target in enumerate(original_mesh.submeshes):
        mapping = mappings_by_target.get(target_index)
        source_indices = list(mapping.source_submesh_indices if mapping is not None else [])
        target_name = (
            str(getattr(mapping, "target_submesh_name", "") or "").strip()
            if mapping is not None
            else ""
        ) or target.material or target.name or f"target {target_index}"
        material_slot_index = (
            int(getattr(mapping, "target_material_slot_index", target_index) or target_index)
            if mapping is not None
            else target_index
        )

        if mode == "legacy_merge":
            groups = [source_indices]
            oversized_groups = [
                sum(_source_vertex_count(replacement_mesh, source_index, normalized_options) for source_index in source_indices)
            ]
            if oversized_groups[0] > _STATIC_REPLACEMENT_VERTEX_LIMIT:
                errors.append(
                    f"{target_name} receives {oversized_groups[0]:,} vertices; "
                    f"legacy merge mode exceeds the {_STATIC_REPLACEMENT_VERTEX_LIMIT:,}-vertex draw-section limit."
                )
        else:
            groups, group_errors = _partition_source_indices_for_vertex_limit(
                replacement_mesh,
                source_indices,
                normalized_options,
                warnings,
            )
            errors.extend(group_errors)

        first_group = groups[0] if groups else []
        original_sections.append(
                StaticOutputDrawSection(
                    output_index=0,
                    target_submesh_index=target_index,
                    target_submesh_name=target_name,
                    source_submesh_indices=list(first_group),
                    target_material_slot_index=material_slot_index,
                    clone_source_target_index=-1,
                    donor_material_name=target.material or target.name or target_name,
                    vertex_count=_group_vertex_count(replacement_mesh, first_group, normalized_options),
                is_cloned_section=False,
                source_face_ranges=_face_ranges_for_groups([first_group]),
            )
        )
        for group in groups[1:]:
            cloned_sections.append(
                StaticOutputDrawSection(
                    output_index=0,
                    target_submesh_index=target_index,
                    target_submesh_name=target_name,
                    source_submesh_indices=list(group),
                    target_material_slot_index=material_slot_index,
                    clone_source_target_index=target_index,
                    donor_material_name=target.material or target.name or target_name,
                    vertex_count=_group_vertex_count(replacement_mesh, group, normalized_options),
                    is_cloned_section=True,
                    source_face_ranges=_face_ranges_for_groups([group]),
                )
            )

    planned = original_sections + cloned_sections
    for output_index, section in enumerate(planned):
        section.output_index = output_index
    if cloned_sections:
        if bool(getattr(normalized_options, "complete_external_swap", False)):
            warnings.append(
                "Complete source-owned swap will preserve source material groups by cloning PAC draw section(s): "
                f"{len(cloned_sections)} cloned section(s)."
            )
        else:
            warnings.append(
                "Dense replacement will preserve source parts by cloning PAC draw section(s): "
                f"{len(cloned_sections)} cloned section(s)."
            )
    return planned, warnings, errors
