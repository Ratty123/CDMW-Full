"""Runtime mesh assembly helpers for static mesh replacement."""

from __future__ import annotations

import copy
import math
from typing import Sequence

from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals
from .static_mesh_clone import _clone_parsed_mesh_fast, _clone_submesh_fast
from .static_mesh_geometry import (
    _apply_alignment_roll,
    _apply_transform,
    _bbox,
    _center,
    _compute_anchor_alignment,
    _dims,
    _is_marker_submesh,
    _normalize,
    _rotate_between,
    _rotate_xyz,
)
from .static_mesh_output_plan import (
    _STATIC_REPLACEMENT_VERTEX_LIMIT,
    plan_static_output_draw_sections,
)
from .static_mesh_source_parts import (
    _apply_source_part_adjustment,
    _apply_texture_uv_transform,
    _independent_parts_for_options,
    _source_part_adjustments_by_index,
    _texture_uv_transform_for_submesh,
    _texture_uv_transforms_by_key,
)
from .static_mesh_types import (
    StaticMaterialAtlasRect,
    StaticMeshReplacementOptions,
    StaticOriginalPartCopy,
    StaticOutputDrawSection,
    StaticReplacementTransform,
    StaticSourcePartAdjustment,
    StaticSubmeshMapping,
    StaticTextureUvTransform,
)


def _replacement_mesh_with_original_part_copies(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    original_part_copies: list[StaticOriginalPartCopy] | None,
) -> tuple[ParsedMesh, set[int]]:
    copies = list(original_part_copies or [])
    if not copies:
        return replacement_mesh, set()

    effective_mesh = _clone_parsed_mesh_fast(replacement_mesh)
    preserve_source_indices: set[int] = set()
    for copy_request in copies:
        try:
            original_index = int(copy_request.original_submesh_index)
        except (TypeError, ValueError):
            continue
        if original_index < 0 or original_index >= len(original_mesh.submeshes):
            continue
        copied_submesh = _clone_submesh_fast(original_mesh.submeshes[original_index])
        original_label = copied_submesh.material or copied_submesh.name or f"original {original_index}"
        copy_label = str(copy_request.label or "").strip() or f"{original_label} (original copy)"
        copied_submesh.name = copy_label
        if not copied_submesh.material:
            copied_submesh.material = original_label
        effective_mesh.submeshes.append(copied_submesh)
        copied_source_index = len(effective_mesh.submeshes) - 1
        if copy_request.keep_original_placement:
            preserve_source_indices.add(copied_source_index)

    all_vertices = [vertex for submesh in effective_mesh.submeshes for vertex in submesh.vertices]
    bbox_min, bbox_max = _bbox(all_vertices)
    effective_mesh.bbox_min = bbox_min
    effective_mesh.bbox_max = bbox_max
    effective_mesh.total_vertices = sum(len(submesh.vertices) for submesh in effective_mesh.submeshes)
    effective_mesh.total_faces = sum(len(submesh.faces) for submesh in effective_mesh.submeshes)
    effective_mesh.has_uvs = any(bool(submesh.uvs) for submesh in effective_mesh.submeshes)
    return effective_mesh, preserve_source_indices

def _build_mapped_replacement_mesh(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
    options: StaticMeshReplacementOptions,
    *,
    enforce_vertex_limit: bool = True,
    max_source_faces_per_submesh: int | None = None,
    output_draw_sections: list[StaticOutputDrawSection] | None = None,
) -> ParsedMesh:
    effective_replacement_mesh, preserve_source_indices = _replacement_mesh_with_original_part_copies(
        original_mesh,
        replacement_mesh,
        options.original_part_copies,
    )
    preserve_source_indices = set(preserve_source_indices)
    for index in getattr(options, "global_transform_exempt_source_indices", []) or []:
        try:
            source_index = int(index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < len(effective_replacement_mesh.submeshes):
            preserve_source_indices.add(source_index)
    adjustments_by_index = _source_part_adjustments_by_index(options.source_part_adjustments)
    mapped_enabled_source_indices: set[int] = set()
    for mapping in mappings:
        for source_index in mapping.source_submesh_indices:
            if (
                0 <= source_index < len(effective_replacement_mesh.submeshes)
                and not _is_marker_submesh(effective_replacement_mesh.submeshes[source_index])
                and adjustments_by_index.get(source_index, StaticSourcePartAdjustment(source_index)).enabled
            ):
                mapped_enabled_source_indices.add(source_index)
    independent_parts = _independent_parts_for_options(
        options,
        effective_replacement_mesh,
        include_preview_only=not enforce_vertex_limit,
    )
    independent_source_indices = {int(part.source_submesh_index) for part in independent_parts}
    transformed_sources = _transformed_replacement_sources(
        original_mesh,
        effective_replacement_mesh,
        options.transform,
        options.source_part_adjustments,
        options.texture_uv_transforms,
        global_transform_exempt_indices=preserve_source_indices | independent_source_indices,
        global_transform_source_indices=mapped_enabled_source_indices,
        max_source_faces_per_submesh=max_source_faces_per_submesh,
        output_source_indices=mapped_enabled_source_indices | independent_source_indices,
    )
    mapped_submeshes: list[SubMesh] = []
    sections = list(output_draw_sections or [])
    if not sections:
        if enforce_vertex_limit:
            sections, _dense_warnings, dense_errors = plan_static_output_draw_sections(
                original_mesh,
                effective_replacement_mesh,
                mappings,
                options,
            )
            if dense_errors:
                raise ValueError("; ".join(dense_errors))
        else:
            mappings_by_target = {mapping.target_submesh_index: mapping for mapping in mappings}
            sections = [
                StaticOutputDrawSection(
                    output_index=target_index,
                    target_submesh_index=target_index,
                    target_submesh_name=target.material or target.name or f"target {target_index}",
                    source_submesh_indices=list(
                        mappings_by_target.get(
                            target_index,
                            StaticSubmeshMapping(target_index, target.material or target.name or "", [], target_index),
                        ).source_submesh_indices
                    ),
                    target_material_slot_index=target_index,
                )
                for target_index, target in enumerate(original_mesh.submeshes)
            ]
    for section in sections:
        target_index = int(section.target_submesh_index)
        if target_index < 0 or target_index >= len(original_mesh.submeshes):
            if enforce_vertex_limit:
                raise ValueError(f"Output draw section references invalid target submesh index {target_index}.")
            continue
        target = original_mesh.submeshes[target_index]
        atlas_rect_by_source = _atlas_rects_by_source_index(section)
        source_parts: list[SubMesh] = []
        for source_index in section.source_submesh_indices:
            if not (
                0 <= source_index < len(transformed_sources)
                and not _is_marker_submesh(transformed_sources[source_index])
                and adjustments_by_index.get(source_index, StaticSourcePartAdjustment(source_index)).enabled
            ):
                continue
            source_part = _clone_submesh_fast(transformed_sources[source_index])
            atlas_rect = atlas_rect_by_source.get(int(source_index))
            if atlas_rect is not None:
                _rewrite_submesh_uvs_for_material_atlas(
                    source_part,
                    atlas_rect,
                    target_name=str(section.target_submesh_name or target.name or target.material or target_index),
                    source_index=int(source_index),
                    source_material_name=str(atlas_rect.source_material_name or source_part.material or source_part.name or source_index),
                )
            source_parts.append(source_part)
        if (
            not source_parts
            and not tuple(section.source_submesh_indices or ())
            and enforce_vertex_limit
        ):
            merged = _build_removed_runtime_placeholder_submesh(target)
        else:
            merged = _merge_source_submeshes(source_parts, target)
        section_label = str(section.target_submesh_name or "").strip()
        if section_label:
            if bool(getattr(options, "complete_external_swap", False)):
                # Complete PAC swaps use source-owned material authority, but
                # the PAC draw ABI itself must stay original.  The sidecar
                # routing name lives on the output section; the binary submesh
                # keeps the donor descriptor name/material.
                merged.name = target.name or section_label
                merged.material = target.material or target.name or section_label
                merged.texture = target.name or target.material or section_label
                setattr(merged, "source_owned_sidecar_name", section_label)
            elif not merged.material:
                merged.name = section_label
                merged.material = section_label
            else:
                merged.name = section_label
        if enforce_vertex_limit and len(merged.vertices) > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            raise ValueError(
                f"Static replacement target {target_index} has {len(merged.vertices):,} vertices; "
                f"current serializers use 16-bit indices and support at most {_STATIC_REPLACEMENT_VERTEX_LIMIT:,} vertices per draw section."
            )
        mapped_submeshes.append(merged)

    for independent_part in independent_parts:
        source_index = int(independent_part.source_submesh_index)
        if source_index < 0 or source_index >= len(transformed_sources):
            continue
        source_submesh = transformed_sources[source_index]
        if _is_marker_submesh(source_submesh):
            continue
        adjustment = adjustments_by_index.get(source_index, StaticSourcePartAdjustment(source_index))
        if not bool(adjustment.enabled):
            continue
        independent_submesh = _clone_submesh_fast(source_submesh)
        label = str(independent_part.label or "").strip()
        material_name = str(independent_part.material_name or "").strip()
        if label:
            independent_submesh.name = label
        if material_name:
            independent_submesh.material = material_name
        elif not str(independent_submesh.material or "").strip():
            independent_submesh.material = independent_submesh.name or f"independent_{source_index}"
        if enforce_vertex_limit and len(independent_submesh.vertices) > _STATIC_REPLACEMENT_VERTEX_LIMIT:
            raise ValueError(
                f"Independent replacement part {source_index} has {len(independent_submesh.vertices):,} vertices; "
                f"current serializers use 16-bit indices and support at most {_STATIC_REPLACEMENT_VERTEX_LIMIT:,} vertices per draw section."
            )
        if not independent_submesh.normals or len(independent_submesh.normals) != len(independent_submesh.vertices):
            independent_submesh.normals = _compute_smooth_normals(independent_submesh.vertices, independent_submesh.faces)
        independent_submesh.vertex_count = len(independent_submesh.vertices)
        independent_submesh.face_count = len(independent_submesh.faces)
        mapped_submeshes.append(independent_submesh)

    all_vertices = [vertex for submesh in mapped_submeshes for vertex in submesh.vertices]
    bbox_min, bbox_max = _bbox(all_vertices)
    return ParsedMesh(
        path=original_mesh.path,
        format=original_mesh.format,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        submeshes=mapped_submeshes,
        total_vertices=sum(len(sm.vertices) for sm in mapped_submeshes),
        total_faces=sum(len(sm.faces) for sm in mapped_submeshes),
        has_uvs=any(sm.uvs for sm in mapped_submeshes),
        has_bones=False,
    )


def _transformed_replacement_sources(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    texture_uv_transforms: list[StaticTextureUvTransform] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    *,
    max_source_faces_per_submesh: int | None = None,
    output_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
) -> list[SubMesh]:
    bound_indices = None if global_transform_source_indices is None else {int(index) for index in global_transform_source_indices}
    requested_output_indices = None if output_source_indices is None else {int(index) for index in output_source_indices}
    if requested_output_indices is None:
        indices_to_copy = set(range(len(replacement_mesh.submeshes)))
    else:
        indices_to_copy = set(requested_output_indices)
        if bound_indices is not None:
            indices_to_copy.update(bound_indices)
    sources: list[SubMesh] = []
    for source_index, submesh in enumerate(replacement_mesh.submeshes):
        if source_index in indices_to_copy:
            sources.append(_clone_submesh_fast(submesh))
            continue
        sources.append(
            SubMesh(
                name=str(getattr(submesh, "name", "") or ""),
                material=str(getattr(submesh, "material", "") or ""),
                texture=str(getattr(submesh, "texture", "") or ""),
            )
        )
    if not sources:
        return sources
    adjustments_by_index = _source_part_adjustments_by_index(source_part_adjustments or [])
    exempt_indices = set(global_transform_exempt_indices or set())

    # Manual source-part edits are fine-tuning controls. They should not change
    # the auto-alignment basis, and preview decimation should not change their
    # rotation/scale pivot. Compute both from the full source mesh before any
    # preview-only face sampling.
    basis_mesh = alignment_basis_mesh or replacement_mesh
    basis_sources = [
        basis_mesh.submeshes[source_index]
        if 0 <= source_index < len(getattr(basis_mesh, "submeshes", ()) or ())
        else submesh
        for source_index, submesh in enumerate(sources)
    ]
    alignment_bound_sources = [
        submesh
        for source_index, submesh in enumerate(basis_sources)
        if source_index not in exempt_indices and (bound_indices is None or source_index in bound_indices)
    ] or basis_sources
    alignment_replacement_mesh = copy.copy(basis_mesh)
    alignment_replacement_mesh.submeshes = list(alignment_bound_sources)

    all_vertices = [vertex for submesh in alignment_bound_sources for vertex in submesh.vertices]
    src_min, src_max = _bbox(all_vertices)
    dst_min, dst_max = _bbox([vertex for submesh in original_mesh.submeshes for vertex in submesh.vertices])
    alignment = _compute_anchor_alignment(original_mesh, alignment_replacement_mesh, transform)
    adjustment_pivots = {
        source_index: _center(*_bbox(submesh.vertices))
        for source_index, submesh in enumerate(basis_sources)
        if (
            source_index in adjustments_by_index
            and adjustments_by_index[source_index].enabled
            and not _is_marker_submesh(submesh)
            and bool(submesh.vertices)
        )
    }

    fit_scale_xyz = (1.0, 1.0, 1.0)
    fit_offset = (0.0, 0.0, 0.0)
    if transform.fit_to_original_bbox:
        src_dims = _dims(src_min, src_max)
        dst_dims = _dims(dst_min, dst_max)
        if transform.preserve_aspect_ratio:
            ratios = [
                dst_dims[index] / src_dims[index]
                for index in range(3)
                if src_dims[index] > 1e-8
            ]
            uniform = min(ratios) if ratios else 1.0
            fit_scale_xyz = (uniform, uniform, uniform)
        else:
            fit_scale_xyz = tuple(
                dst_dims[index] / src_dims[index] if src_dims[index] > 1e-8 else 1.0
                for index in range(3)
            )
        src_center = _center(src_min, src_max)
        dst_center = _center(dst_min, dst_max)
        fit_offset = tuple(dst_center[index] - src_center[index] * fit_scale_xyz[index] for index in range(3))

    max_preview_faces = _normalized_preview_face_limit(max_source_faces_per_submesh)
    if max_preview_faces > 0:
        sources = [_decimate_submesh_for_preview(submesh, max_preview_faces) for submesh in sources]

    uv_transforms_by_key = _texture_uv_transforms_by_key(texture_uv_transforms or [])
    if uv_transforms_by_key:
        for submesh in sources:
            uv_transform = _texture_uv_transform_for_submesh(submesh, uv_transforms_by_key)
            if uv_transform is not None:
                _apply_texture_uv_transform(submesh, uv_transform)

    for source_index, submesh in enumerate(sources):
        adjustment = adjustments_by_index.get(source_index)
        if adjustment is None or not adjustment.enabled or _is_marker_submesh(submesh):
            continue
        _apply_source_part_adjustment(submesh, adjustment, pivot=adjustment_pivots.get(source_index))

    for source_index, submesh in enumerate(sources):
        if source_index in exempt_indices:
            continue
        submesh.vertices = [
            _apply_transform(vertex, transform, fit_scale_xyz, fit_offset, alignment)
            for vertex in submesh.vertices
        ]
        if submesh.normals and len(submesh.normals) == len(submesh.vertices):
            submesh.normals = [
                _normalize(
                    _rotate_xyz(
                        _apply_alignment_roll(
                            _rotate_between(normal, alignment["source_axis"], alignment["target_axis"]),
                            alignment,
                        ),
                        transform.rotate_xyz_degrees,
                    )
                )
                for normal in submesh.normals
            ]
    return sources


def _mesh_delta_bounds(
    submeshes: Sequence[SubMesh],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    vertices = [vertex for submesh in submeshes for vertex in (submesh.vertices or [])]
    return _bbox(vertices)


def _mesh_edit_forward_transformed_delta(
    delta: tuple[float, float, float],
    *,
    source_index: int,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
) -> tuple[float, float, float]:
    value = (float(delta[0]), float(delta[1]), float(delta[2]))
    basis_mesh = alignment_basis_mesh or replacement_mesh
    source_count = len(getattr(replacement_mesh, "submeshes", ()) or ())
    if source_index < 0 or source_index >= source_count:
        return value
    basis_sources = [
        basis_mesh.submeshes[index]
        if 0 <= index < len(getattr(basis_mesh, "submeshes", ()) or ())
        else submesh
        for index, submesh in enumerate(replacement_mesh.submeshes)
    ]
    adjustments_by_index = _source_part_adjustments_by_index(source_part_adjustments or [])
    adjustment = adjustments_by_index.get(source_index)
    if adjustment is not None and adjustment.enabled and not _is_marker_submesh(replacement_mesh.submeshes[source_index]):
        sx, sy, sz = adjustment.scale_xyz or (1.0, 1.0, 1.0)
        uniform = float(adjustment.uniform_scale or 1.0)
        value = (
            value[0] * float(sx) * uniform,
            value[1] * float(sy) * uniform,
            value[2] * float(sz) * uniform,
        )
        value = _rotate_xyz(value, tuple(float(degree) for degree in adjustment.rotate_xyz_degrees))

    exempt_indices = {int(index) for index in (global_transform_exempt_indices or set())}
    if source_index in exempt_indices:
        return value

    bound_indices = None if global_transform_source_indices is None else {int(index) for index in global_transform_source_indices}
    alignment_bound_sources = [
        submesh
        for index, submesh in enumerate(basis_sources)
        if index not in exempt_indices and (bound_indices is None or index in bound_indices)
    ] or basis_sources
    alignment_replacement_mesh = copy.copy(basis_mesh)
    alignment_replacement_mesh.submeshes = list(alignment_bound_sources)
    alignment = _compute_anchor_alignment(original_mesh, alignment_replacement_mesh, transform)

    fit_scale_xyz = (1.0, 1.0, 1.0)
    if transform.fit_to_original_bbox:
        src_min, src_max = _mesh_delta_bounds(alignment_bound_sources)
        dst_min, dst_max = _mesh_delta_bounds(original_mesh.submeshes)
        src_dims = _dims(src_min, src_max)
        dst_dims = _dims(dst_min, dst_max)
        if transform.preserve_aspect_ratio:
            ratios = [
                dst_dims[index] / src_dims[index]
                for index in range(3)
                if src_dims[index] > 1e-8
            ]
            uniform = min(ratios) if ratios else 1.0
            fit_scale_xyz = (uniform, uniform, uniform)
        else:
            fit_scale_xyz = tuple(
                dst_dims[index] / src_dims[index] if src_dims[index] > 1e-8 else 1.0
                for index in range(3)
            )

    source_axis = alignment["source_axis"]
    target_axis = alignment["target_axis"]
    value = _apply_alignment_roll(_rotate_between(value, source_axis, target_axis), alignment)
    manual_scale = transform.scale_xyz or (transform.scale, transform.scale, transform.scale)
    align_scale = float(alignment["scale"])
    value = (
        value[0] * float(manual_scale[0]) * align_scale * fit_scale_xyz[0],
        value[1] * float(manual_scale[1]) * align_scale * fit_scale_xyz[1],
        value[2] * float(manual_scale[2]) * align_scale * fit_scale_xyz[2],
    )
    return _rotate_xyz(value, transform.rotate_xyz_degrees)


def _mesh_edit_forward_transformed_point(
    point: tuple[float, float, float],
    *,
    source_index: int,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
) -> tuple[float, float, float]:
    value = (float(point[0]), float(point[1]), float(point[2]))
    basis_mesh = alignment_basis_mesh or replacement_mesh
    source_count = len(getattr(replacement_mesh, "submeshes", ()) or ())
    if source_index < 0 or source_index >= source_count:
        return value
    basis_sources = [
        basis_mesh.submeshes[index]
        if 0 <= index < len(getattr(basis_mesh, "submeshes", ()) or ())
        else submesh
        for index, submesh in enumerate(replacement_mesh.submeshes)
    ]
    adjustments_by_index = _source_part_adjustments_by_index(source_part_adjustments or [])
    adjustment = adjustments_by_index.get(source_index)
    if adjustment is not None and adjustment.enabled and not _is_marker_submesh(replacement_mesh.submeshes[source_index]):
        basis_source = basis_sources[source_index] if source_index < len(basis_sources) else replacement_mesh.submeshes[source_index]
        pivot = _center(*_bbox(getattr(basis_source, "vertices", ()) or ()))
        sx, sy, sz = adjustment.scale_xyz or (1.0, 1.0, 1.0)
        uniform = float(adjustment.uniform_scale or 1.0)
        local = (
            (value[0] - pivot[0]) * float(sx) * uniform,
            (value[1] - pivot[1]) * float(sy) * uniform,
            (value[2] - pivot[2]) * float(sz) * uniform,
        )
        rotated = _rotate_xyz(local, tuple(float(degree) for degree in adjustment.rotate_xyz_degrees))
        offset = tuple(float(component) for component in adjustment.offset_xyz)
        value = (
            rotated[0] + pivot[0] + offset[0],
            rotated[1] + pivot[1] + offset[1],
            rotated[2] + pivot[2] + offset[2],
        )

    exempt_indices = {int(index) for index in (global_transform_exempt_indices or set())}
    if source_index in exempt_indices:
        return value

    bound_indices = None if global_transform_source_indices is None else {int(index) for index in global_transform_source_indices}
    alignment_bound_sources = [
        submesh
        for index, submesh in enumerate(basis_sources)
        if index not in exempt_indices and (bound_indices is None or index in bound_indices)
    ] or basis_sources
    alignment_replacement_mesh = copy.copy(basis_mesh)
    alignment_replacement_mesh.submeshes = list(alignment_bound_sources)
    alignment = _compute_anchor_alignment(original_mesh, alignment_replacement_mesh, transform)

    fit_scale_xyz = (1.0, 1.0, 1.0)
    fit_offset = (0.0, 0.0, 0.0)
    if transform.fit_to_original_bbox:
        src_min, src_max = _mesh_delta_bounds(alignment_bound_sources)
        dst_min, dst_max = _mesh_delta_bounds(original_mesh.submeshes)
        src_dims = _dims(src_min, src_max)
        dst_dims = _dims(dst_min, dst_max)
        if transform.preserve_aspect_ratio:
            ratios = [
                dst_dims[index] / src_dims[index]
                for index in range(3)
                if src_dims[index] > 1e-8
            ]
            uniform = min(ratios) if ratios else 1.0
            fit_scale_xyz = (uniform, uniform, uniform)
        else:
            fit_scale_xyz = tuple(
                dst_dims[index] / src_dims[index] if src_dims[index] > 1e-8 else 1.0
                for index in range(3)
            )
        src_center = _center(src_min, src_max)
        dst_center = _center(dst_min, dst_max)
        fit_offset = tuple(dst_center[index] - src_center[index] * fit_scale_xyz[index] for index in range(3))
    return _apply_transform(value, transform, fit_scale_xyz, fit_offset, alignment)


def _solve_linear_delta(
    columns: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
    target: tuple[float, float, float],
) -> tuple[float, float, float] | None:
    a, b, c = columns
    det = (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - b[0] * (a[1] * c[2] - a[2] * c[1])
        + c[0] * (a[1] * b[2] - a[2] * b[1])
    )
    if abs(det) <= 1.0e-10 or not math.isfinite(det):
        return None
    tx, ty, tz = target
    x = (
        tx * (b[1] * c[2] - b[2] * c[1])
        - b[0] * (ty * c[2] - tz * c[1])
        + c[0] * (ty * b[2] - tz * b[1])
    ) / det
    y = (
        a[0] * (ty * c[2] - tz * c[1])
        - tx * (a[1] * c[2] - a[2] * c[1])
        + c[0] * (a[1] * tz - a[2] * ty)
    ) / det
    z = (
        a[0] * (b[1] * tz - b[2] * ty)
        - b[0] * (a[1] * tz - a[2] * ty)
        + tx * (a[1] * b[2] - a[2] * b[1])
    ) / det
    result = (x, y, z)
    if not all(math.isfinite(value) for value in result):
        return None
    return result


def source_delta_for_transformed_delta(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_submesh_index: int,
    transformed_delta: tuple[float, float, float],
    *,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
) -> tuple[float, float, float]:
    """Map a displayed preview-space movement back into editable source mesh space."""
    try:
        source_index = int(source_submesh_index)
        target = (float(transformed_delta[0]), float(transformed_delta[1]), float(transformed_delta[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return (0.0, 0.0, 0.0)
    if source_index < 0 or source_index >= len(getattr(replacement_mesh, "submeshes", ()) or ()):
        return target
    common = {
        "source_index": source_index,
        "original_mesh": original_mesh,
        "replacement_mesh": replacement_mesh,
        "transform": transform,
        "source_part_adjustments": source_part_adjustments,
        "global_transform_exempt_indices": global_transform_exempt_indices,
        "global_transform_source_indices": global_transform_source_indices,
        "alignment_basis_mesh": alignment_basis_mesh,
    }
    columns = (
        _mesh_edit_forward_transformed_delta((1.0, 0.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 1.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 0.0, 1.0), **common),
    )
    return _solve_linear_delta(columns, target) or target


def source_point_for_transformed_point(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_submesh_index: int,
    transformed_point: tuple[float, float, float],
    *,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
) -> tuple[float, float, float]:
    """Map a displayed preview-space point back into editable source mesh space."""
    try:
        source_index = int(source_submesh_index)
        target = (float(transformed_point[0]), float(transformed_point[1]), float(transformed_point[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return (0.0, 0.0, 0.0)
    if source_index < 0 or source_index >= len(getattr(replacement_mesh, "submeshes", ()) or ()):
        return target
    common = {
        "source_index": source_index,
        "original_mesh": original_mesh,
        "replacement_mesh": replacement_mesh,
        "transform": transform,
        "source_part_adjustments": source_part_adjustments,
        "global_transform_exempt_indices": global_transform_exempt_indices,
        "global_transform_source_indices": global_transform_source_indices,
        "alignment_basis_mesh": alignment_basis_mesh,
    }
    origin = _mesh_edit_forward_transformed_point((0.0, 0.0, 0.0), **common)
    columns = (
        _mesh_edit_forward_transformed_delta((1.0, 0.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 1.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 0.0, 1.0), **common),
    )
    relative = tuple(target[index] - origin[index] for index in range(3))
    return _solve_linear_delta(columns, relative) or target


def source_distance_for_transformed_distance(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_submesh_index: int,
    transformed_distance: float,
    *,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
) -> float:
    """Approximate a displayed preview-space brush length in editable source mesh space."""
    try:
        source_index = int(source_submesh_index)
        distance = abs(float(transformed_distance))
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if source_index < 0 or source_index >= len(getattr(replacement_mesh, "submeshes", ()) or ()):
        return distance
    common = {
        "source_index": source_index,
        "original_mesh": original_mesh,
        "replacement_mesh": replacement_mesh,
        "transform": transform,
        "source_part_adjustments": source_part_adjustments,
        "global_transform_exempt_indices": global_transform_exempt_indices,
        "global_transform_source_indices": global_transform_source_indices,
        "alignment_basis_mesh": alignment_basis_mesh,
    }
    scales = []
    for column in (
        _mesh_edit_forward_transformed_delta((1.0, 0.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 1.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 0.0, 1.0), **common),
    ):
        length = math.sqrt(column[0] * column[0] + column[1] * column[1] + column[2] * column[2])
        if length > 1.0e-8 and math.isfinite(length):
            scales.append(length)
    if not scales:
        return distance
    return distance / (sum(scales) / float(len(scales)))


def _merge_source_submeshes(submeshes: list[SubMesh], target: SubMesh) -> SubMesh:
    merged = SubMesh(
        name=target.name,
        material=target.material,
        texture=target.texture,
    )
    wants_uvs = any(len(submesh.uvs) == len(submesh.vertices) for submesh in submeshes)
    wants_normals = any(len(submesh.normals) == len(submesh.vertices) for submesh in submeshes)
    for submesh in submeshes:
        base = len(merged.vertices)
        merged.vertices.extend(list(submesh.vertices or []))
        if wants_uvs:
            merged.uvs.extend(
                list(submesh.uvs or [])
                if len(submesh.uvs) == len(submesh.vertices)
                else [(0.0, 0.0)] * len(submesh.vertices)
            )
        if wants_normals:
            merged.normals.extend(
                list(submesh.normals or [])
                if len(submesh.normals) == len(submesh.vertices)
                else [(0.0, 1.0, 0.0)] * len(submesh.vertices)
            )
        for face in submesh.faces:
            if len(face) == 3:
                merged.faces.append((face[0] + base, face[1] + base, face[2] + base))
    if not merged.normals or len(merged.normals) != len(merged.vertices):
        merged.normals = _compute_smooth_normals(merged.vertices, merged.faces)
    merged.vertex_count = len(merged.vertices)
    merged.face_count = len(merged.faces)
    return merged


def _atlas_rects_by_source_index(section: StaticOutputDrawSection) -> dict[int, StaticMaterialAtlasRect]:
    rects: dict[int, StaticMaterialAtlasRect] = {}
    for rect in tuple(getattr(section, "atlas_rects", ()) or ()):
        for source_index in tuple(getattr(rect, "source_submesh_indices", ()) or ()):
            try:
                rects[int(source_index)] = rect
            except (TypeError, ValueError):
                continue
    return rects


def _rewrite_submesh_uvs_for_material_atlas(
    submesh: SubMesh,
    rect: StaticMaterialAtlasRect,
    *,
    target_name: str,
    source_index: int,
    source_material_name: str,
) -> None:
    if not submesh.uvs or len(submesh.uvs) != len(submesh.vertices):
        raise ValueError(
            f"Cannot atlas/bake {source_material_name} into {target_name}: source submesh {source_index} has no complete UV set."
        )
    rewritten: list[tuple[float, float]] = []
    for raw_u, raw_v in submesh.uvs:
        u = float(raw_u)
        v = float(raw_v)
        if u < -1e-4 or u > 1.0001 or v < -1e-4 or v > 1.0001:
            raise ValueError(
                f"Cannot atlas/bake {source_material_name} into {target_name}: source UV ({u:.4f}, {v:.4f}) "
                "is outside 0..1; tiled UVs are not supported for automatic complete-swap atlases."
            )
        clamped_u = max(0.0, min(1.0, u))
        clamped_v = max(0.0, min(1.0, v))
        rewritten.append(
            (
                float(rect.x) + clamped_u * float(rect.width),
                float(rect.y) + clamped_v * float(rect.height),
            )
        )
    submesh.uvs = rewritten


def _build_removed_runtime_placeholder_submesh(target: SubMesh) -> SubMesh:
    """Emit a valid, effectively invisible draw for runtime slots with no source mesh.

    Some PAC consumers appear to treat zero-count draw descriptors as invalid
    and can keep drawing the original section.  Empty/removed slots therefore
    become a tiny triangle cloned from the donor slot instead of a zero-count
    descriptor.
    """
    donor_index = 0
    for index, weights in enumerate(getattr(target, "bone_weights", ()) or ()):
        if weights:
            donor_index = index
            break
    if not getattr(target, "vertices", None):
        origin = (0.0, 0.0, 0.0)
    else:
        donor_index = max(0, min(donor_index, len(target.vertices) - 1))
        origin = target.vertices[donor_index]
    epsilon = 1.0e-5
    placeholder = SubMesh(
        name=target.name,
        material=target.material,
        texture=target.texture,
        vertices=[
            (float(origin[0]), float(origin[1]), float(origin[2])),
            (float(origin[0]) + epsilon, float(origin[1]), float(origin[2])),
            (float(origin[0]), float(origin[1]) + epsilon, float(origin[2])),
        ],
        uvs=[(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)],
        normals=[(0.0, 1.0, 0.0), (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        source_vertex_map=[donor_index, donor_index, donor_index],
        vertex_count=3,
        face_count=1,
    )
    return placeholder


def _build_complete_swap_runtime_placeholder_submesh(target: SubMesh) -> SubMesh:
    return _build_removed_runtime_placeholder_submesh(target)


def _normalized_preview_face_limit(value: int | None) -> int:
    try:
        limit = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, limit)


def _decimate_submesh_for_preview(submesh: SubMesh, max_faces: int) -> SubMesh:
    faces = list(submesh.faces or [])
    if max_faces <= 0 or len(faces) <= max_faces:
        return submesh
    if not submesh.vertices:
        return submesh

    step = max(1, math.ceil(len(faces) / float(max_faces)))
    sampled_faces = faces[::step][:max_faces]
    source_to_preview: dict[int, int] = {}
    preview_vertices: list[tuple[float, float, float]] = []
    preview_faces: list[tuple[int, int, int]] = []

    for face in sampled_faces:
        remapped_face: list[int] = []
        for raw_index in face[:3]:
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError):
                remapped_face = []
                break
            if source_index < 0 or source_index >= len(submesh.vertices):
                remapped_face = []
                break
            preview_index = source_to_preview.get(source_index)
            if preview_index is None:
                preview_index = len(preview_vertices)
                source_to_preview[source_index] = preview_index
                preview_vertices.append(submesh.vertices[source_index])
            remapped_face.append(preview_index)
        if len(remapped_face) == 3:
            preview_faces.append((remapped_face[0], remapped_face[1], remapped_face[2]))

    if not preview_faces:
        return submesh

    ordered_source_indices = [
        source_index
        for source_index, _preview_index in sorted(source_to_preview.items(), key=lambda item: item[1])
    ]
    preview = _clone_submesh_fast(submesh)
    preview.vertices = preview_vertices
    preview.faces = preview_faces
    preview.uvs = (
        [submesh.uvs[source_index] for source_index in ordered_source_indices]
        if len(submesh.uvs) == len(submesh.vertices)
        else []
    )
    preview.normals = (
        [submesh.normals[source_index] for source_index in ordered_source_indices]
        if len(submesh.normals) == len(submesh.vertices)
        else []
    )
    preview.bone_indices = (
        [submesh.bone_indices[source_index] for source_index in ordered_source_indices]
        if len(submesh.bone_indices) == len(submesh.vertices)
        else []
    )
    preview.bone_weights = (
        [submesh.bone_weights[source_index] for source_index in ordered_source_indices]
        if len(submesh.bone_weights) == len(submesh.vertices)
        else []
    )
    preview.source_vertex_map = (
        [submesh.source_vertex_map[source_index] for source_index in ordered_source_indices]
        if len(submesh.source_vertex_map) == len(submesh.vertices)
        else []
    )
    preview.vertex_count = len(preview.vertices)
    preview.face_count = len(preview.faces)
    preview.source_vertex_offsets = []
    preview.source_index_offset = -1
    preview.source_index_count = len(preview.faces) * 3
    return preview
