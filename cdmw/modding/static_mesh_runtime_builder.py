"""Runtime mesh assembly helpers for static mesh replacement."""

from __future__ import annotations

import copy
import math
from typing import Sequence

from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals
from .mesh_skinning import ensure_final_target_skin_weights, finalize_merged_skin_provenance
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
from .static_mesh_output_plan import _STATIC_REPLACEMENT_VERTEX_LIMIT, _atlas_uv_transform, plan_static_output_draw_sections
from .static_mesh_scene_frame import build_static_transform_frame
from .static_mesh_preview_decimation import decimate_submesh_for_preview
from .static_mesh_source_parts import (
    _apply_source_part_adjustment,
    _apply_texture_uv_transform,
    _independent_parts_for_options,
    _source_part_adjustments_by_index,
    _texture_uv_transform_for_submesh,
    _texture_uv_transform_payload,
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


def _mesh_metadata_for_submeshes(
    submeshes: Sequence[SubMesh],
) -> tuple[tuple[float, float, float], tuple[float, float, float], int, int, bool]:
    submesh_list = list(submeshes or ())
    try:
        from .mesh_native_core import summarize_native_mesh_submesh_metadata

        report = summarize_native_mesh_submesh_metadata(submesh_list)
    except Exception:
        report = None
    if isinstance(report, dict):
        try:
            total_vertices = int(report.get("total_vertices", -1))
            total_faces = int(report.get("total_faces", -1))
            bbox_min = tuple(float(value) for value in tuple(report.get("bbox_min") or ())[:3])
            bbox_max = tuple(float(value) for value in tuple(report.get("bbox_max") or ())[:3])
        except (TypeError, ValueError, OverflowError):
            total_vertices = -1
            total_faces = -1
            bbox_min = ()
            bbox_max = ()
        if total_vertices >= 0 and total_faces >= 0 and len(bbox_min) == 3 and len(bbox_max) == 3:
            return (
                (bbox_min[0], bbox_min[1], bbox_min[2]),
                (bbox_max[0], bbox_max[1], bbox_max[2]),
                total_vertices,
                total_faces,
                bool(report.get("has_uvs")),
            )

    all_vertices = [vertex for submesh in submesh_list for vertex in submesh.vertices]
    bbox_min, bbox_max = _bbox(all_vertices)
    return (
        bbox_min,
        bbox_max,
        sum(len(submesh.vertices) for submesh in submesh_list),
        sum(len(submesh.faces) for submesh in submesh_list),
        any(bool(submesh.uvs) for submesh in submesh_list),
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

    bbox_min, bbox_max, total_vertices, total_faces, has_uvs = _mesh_metadata_for_submeshes(effective_mesh.submeshes)
    effective_mesh.bbox_min = bbox_min
    effective_mesh.bbox_max = bbox_max
    effective_mesh.total_vertices = total_vertices
    effective_mesh.total_faces = total_faces
    effective_mesh.has_uvs = has_uvs
    return effective_mesh, preserve_source_indices


def _mapped_alignment_source_indices(
    mappings: Sequence[StaticSubmeshMapping], replacement_mesh: ParsedMesh, exempt_indices: set[int]
) -> set[int]:
    return {
        int(source_index)
        for mapping in mappings
        for source_index in mapping.source_submesh_indices
        if 0 <= int(source_index) < len(replacement_mesh.submeshes)
        and int(source_index) not in exempt_indices
        and not _is_marker_submesh(replacement_mesh.submeshes[int(source_index)])
    }


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
        global_transform_source_indices=mapped_enabled_source_indices, alignment_source_indices=_mapped_alignment_source_indices(mappings, effective_replacement_mesh, preserve_source_indices | independent_source_indices),
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
                    source_material_name=str(atlas_rect.source_material_name or source_part.material or source_part.name or source_index), padding=int(getattr(section, "atlas_padding", 8) or 8),
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
        if enforce_vertex_limit:
            ensure_final_target_skin_weights(merged, target, target_index=target_index, summary=getattr(options, "_skin_weight_transfer_summary", None))
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
    bbox_min, bbox_max, total_vertices, total_faces, has_uvs = _mesh_metadata_for_submeshes(mapped_submeshes)
    return ParsedMesh(
        path=original_mesh.path,
        format=original_mesh.format,
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        submeshes=mapped_submeshes,
        total_vertices=total_vertices,
        total_faces=total_faces,
        has_uvs=has_uvs,
        has_bones=any(bool(submesh.bone_indices) and bool(submesh.bone_weights) for submesh in mapped_submeshes),
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
    alignment_source_indices: set[int] | None = None,
) -> list[SubMesh]:
    bound_indices = None if global_transform_source_indices is None else {int(index) for index in global_transform_source_indices}
    alignment_bound_indices = (
        bound_indices
        if alignment_source_indices is None
        else {int(index) for index in alignment_source_indices}
    )
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
    fallback_state: tuple[
        dict[str, tuple[float, float, float] | float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] | None = None

    def fallback_global_transform_state() -> tuple[
        dict[str, tuple[float, float, float] | float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]:
        nonlocal fallback_state
        if fallback_state is not None:
            return fallback_state
        fallback_state = _global_transform_state(
            original_mesh,
            basis_mesh,
            basis_sources,
            transform,
            exempt_indices,
            alignment_bound_indices,
        )
        return fallback_state

    max_preview_faces = _normalized_preview_face_limit(max_source_faces_per_submesh)
    if max_preview_faces > 0:
        native_decimated_indices = _apply_native_preview_decimation(sources, max_preview_faces)
        sources = [
            submesh if source_index in native_decimated_indices else _decimate_submesh_for_preview(submesh, max_preview_faces)
            for source_index, submesh in enumerate(sources)
        ]

    uv_transforms_by_key = _texture_uv_transforms_by_key(texture_uv_transforms or [])
    if uv_transforms_by_key:
        native_uv_transformed_indices = _apply_native_texture_uv_transforms(sources, uv_transforms_by_key)
        for source_index, submesh in enumerate(sources):
            if source_index in native_uv_transformed_indices:
                continue
            uv_transform = _texture_uv_transform_for_submesh(submesh, uv_transforms_by_key)
            if uv_transform is not None:
                _apply_texture_uv_transform(submesh, uv_transform)

    native_adjusted_indices = _apply_native_source_part_adjustments(
        sources,
        adjustments_by_index=adjustments_by_index,
        adjustment_pivot_sources=basis_sources,
    )
    for source_index, submesh in enumerate(sources):
        if source_index in native_adjusted_indices:
            continue
        adjustment = adjustments_by_index.get(source_index)
        if adjustment is None or not adjustment.enabled or _is_marker_submesh(submesh):
            continue
        basis_source = basis_sources[source_index] if 0 <= source_index < len(basis_sources) else submesh
        pivot_vertices = getattr(basis_source, "vertices", ()) or ()
        fallback_pivot = _center(*_bbox(pivot_vertices)) if pivot_vertices else None
        _apply_source_part_adjustment(submesh, adjustment, pivot=fallback_pivot)

    native_transformed_indices = _apply_native_global_source_transforms(
        sources,
        original_mesh=original_mesh,
        replacement_mesh=replacement_mesh,
        transform=transform,
        exempt_indices=exempt_indices,
        global_transform_source_indices=global_transform_source_indices,
        alignment_source_indices=alignment_bound_indices,
        alignment_basis_mesh=basis_mesh,
    )
    for source_index, submesh in enumerate(sources):
        if source_index in exempt_indices or source_index in native_transformed_indices:
            continue
        alignment, fit_scale_xyz, fit_offset = fallback_global_transform_state()
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


def _apply_native_preview_decimation(sources: list[SubMesh], max_preview_faces: int) -> set[int]:
    try:
        from .mesh_native_core import decimate_native_mesh_preview_submeshes

        decimated = decimate_native_mesh_preview_submeshes(sources, max_preview_faces)
    except Exception:
        return set()
    return set(decimated or ())


def _apply_native_texture_uv_transforms(
    sources: Sequence[SubMesh],
    uv_transforms_by_key: dict[str, StaticTextureUvTransform],
) -> set[int]:
    transforms_by_index: dict[int, dict[str, object]] = {}
    for source_index, submesh in enumerate(sources):
        if not getattr(submesh, "uvs", None) or len(submesh.uvs) != len(submesh.vertices):
            continue
        uv_transform = _texture_uv_transform_for_submesh(submesh, uv_transforms_by_key)
        if uv_transform is None:
            continue
        transforms_by_index[source_index] = _texture_uv_transform_payload(uv_transform)
    if not transforms_by_index:
        return set()
    try:
        from .mesh_native_core import apply_native_mesh_uv_transform_submeshes

        transformed = apply_native_mesh_uv_transform_submeshes(
            sources,
            transforms_by_index,
        )
    except Exception:
        transformed = None
    return set(transformed or ())


def _apply_native_source_part_adjustments(
    sources: Sequence[SubMesh],
    *,
    adjustments_by_index: dict[int, StaticSourcePartAdjustment],
    adjustment_pivot_sources: Sequence[SubMesh],
) -> set[int]:
    native_adjustments: dict[int, dict[str, object]] = {}
    for source_index, submesh in enumerate(sources):
        adjustment = adjustments_by_index.get(source_index)
        if adjustment is None or not adjustment.enabled or _is_marker_submesh(submesh):
            continue
        payload: dict[str, object] = {
            "scale_xyz": tuple(adjustment.scale_xyz or (1.0, 1.0, 1.0)),
            "uniform_scale": float(adjustment.uniform_scale or 1.0),
            "offset_xyz": tuple(adjustment.offset_xyz or (0.0, 0.0, 0.0)),
            "rotate_xyz_degrees": tuple(adjustment.rotate_xyz_degrees or (0.0, 0.0, 0.0)),
        }
        pivot_source = adjustment_pivot_sources[source_index] if 0 <= source_index < len(adjustment_pivot_sources) else submesh
        pivot_vertices = tuple(getattr(pivot_source, "vertices", ()) or ())
        if pivot_vertices:
            payload["pivot_vertices"] = pivot_vertices
        native_adjustments[source_index] = payload
    if not native_adjustments:
        return set()
    try:
        from .mesh_native_core import apply_native_mesh_affine_transform_submeshes

        adjusted = apply_native_mesh_affine_transform_submeshes(
            sources,
            source_part_adjustments_by_index=native_adjustments,
        )
    except Exception:
        adjusted = None
    return set(adjusted or ())


def _apply_native_global_source_transforms(
    sources: Sequence[SubMesh],
    *,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    exempt_indices: set[int],
    global_transform_source_indices: set[int] | None,
    alignment_source_indices: set[int] | None,
    alignment_basis_mesh: ParsedMesh | None,
) -> set[int]:
    position_matrices: dict[int, tuple[float, ...]] = {}
    normal_matrices: dict[int, tuple[float, ...]] = {}
    for source_index, submesh in enumerate(sources):
        if source_index in exempt_indices or not getattr(submesh, "vertices", None):
            continue
        position_matrix = source_affine_for_transformed_preview(
            original_mesh,
            replacement_mesh,
            transform,
            source_index,
            source_part_adjustments=None,
            global_transform_exempt_indices=exempt_indices,
            global_transform_source_indices=global_transform_source_indices,
            alignment_source_indices=alignment_source_indices,
            alignment_basis_mesh=alignment_basis_mesh,
        )
        if position_matrix is None:
            continue
        normals = getattr(submesh, "normals", ()) or ()
        if normals and len(normals) == len(submesh.vertices):
            normal_matrix = source_normal_transform_for_transformed_preview(
                original_mesh,
                replacement_mesh,
                transform,
                source_index,
                source_part_adjustments=None,
                global_transform_exempt_indices=exempt_indices,
                global_transform_source_indices=global_transform_source_indices,
                alignment_source_indices=alignment_source_indices,
                alignment_basis_mesh=alignment_basis_mesh,
            )
            if normal_matrix is None:
                continue
            normal_matrices[source_index] = normal_matrix
        position_matrices[source_index] = position_matrix
    if not position_matrices:
        return set()
    try:
        from .mesh_native_core import apply_native_mesh_affine_transform_submeshes

        transformed = apply_native_mesh_affine_transform_submeshes(
            sources,
            position_matrices_by_index=position_matrices,
            normal_matrices_by_index=normal_matrices,
        )
    except Exception:
        transformed = None
    return set(transformed or ())


def _mesh_delta_bounds(
    submeshes: Sequence[SubMesh],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    bbox_min, bbox_max, _total_vertices, _total_faces, _has_uvs = _mesh_metadata_for_submeshes(submeshes)
    return bbox_min, bbox_max


def _global_transform_state(
    original_mesh: ParsedMesh,
    basis_mesh: ParsedMesh,
    basis_sources: Sequence[SubMesh],
    transform: StaticReplacementTransform,
    exempt_indices: set[int],
    bound_indices: set[int] | None,
    *,
    include_grid_floor: bool = True,
) -> tuple[
    dict[str, tuple[float, float, float] | float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    alignment_bound_sources = [
        submesh
        for source_index, submesh in enumerate(basis_sources)
        if source_index not in exempt_indices and (bound_indices is None or source_index in bound_indices)
    ] or list(basis_sources)
    alignment_replacement_mesh = copy.copy(basis_mesh)
    alignment_replacement_mesh.submeshes = list(alignment_bound_sources)
    frame = build_static_transform_frame(
        original_mesh,
        alignment_replacement_mesh,
        transform,
        include_grid_floor=include_grid_floor,
        bounds_for_submeshes=_mesh_delta_bounds,
    )
    return (
        frame.alignment.as_legacy_alignment(),
        frame.alignment.fit_scale_xyz,
        frame.alignment.fit_offset,
    )


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
    alignment, fit_scale_xyz, _fit_offset = _global_transform_state(
        original_mesh,
        basis_mesh,
        alignment_bound_sources,
        transform,
        set(),
        None,
        include_grid_floor=False,
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


def _mesh_edit_forward_transformed_normal(
    normal: tuple[float, float, float],
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
    value = _normalize((float(normal[0]), float(normal[1]), float(normal[2])))
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
        value = _normalize(_rotate_xyz(value, tuple(float(degree) for degree in adjustment.rotate_xyz_degrees)))

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

    return _normalize(
        _rotate_xyz(
            _apply_alignment_roll(
                _rotate_between(value, alignment["source_axis"], alignment["target_axis"]),
                alignment,
            ),
            transform.rotate_xyz_degrees,
        )
    )


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
    alignment, fit_scale_xyz, fit_offset = _global_transform_state(
        original_mesh,
        basis_mesh,
        basis_sources,
        transform,
        exempt_indices,
        bound_indices,
    )
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
    alignment_source_indices: set[int] | None = None,
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
        "global_transform_source_indices": global_transform_source_indices if alignment_source_indices is None else alignment_source_indices,
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
    alignment_source_indices: set[int] | None = None,
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
        "global_transform_source_indices": global_transform_source_indices if alignment_source_indices is None else alignment_source_indices,
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


def source_affine_for_transformed_preview(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_submesh_index: int,
    *,
    normalization_center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    normalization_scale: float = 1.0,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
    alignment_source_indices: set[int] | None = None,
) -> tuple[float, ...] | None:
    try:
        source_index = int(source_submesh_index)
        center = (
            float(normalization_center[0]),
            float(normalization_center[1]),
            float(normalization_center[2]),
        )
        scale = float(normalization_scale or 1.0)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if not math.isfinite(scale) or abs(scale) <= 1.0e-8:
        scale = 1.0
    if source_index < 0 or source_index >= len(getattr(replacement_mesh, "submeshes", ()) or ()):
        return None
    common = {
        "source_index": source_index,
        "original_mesh": original_mesh,
        "replacement_mesh": replacement_mesh,
        "transform": transform,
        "source_part_adjustments": source_part_adjustments,
        "global_transform_exempt_indices": global_transform_exempt_indices,
        "global_transform_source_indices": global_transform_source_indices if alignment_source_indices is None else alignment_source_indices,
        "alignment_basis_mesh": alignment_basis_mesh,
    }
    origin = _mesh_edit_forward_transformed_point((0.0, 0.0, 0.0), **common)
    columns = (
        _mesh_edit_forward_transformed_delta((1.0, 0.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 1.0, 0.0), **common),
        _mesh_edit_forward_transformed_delta((0.0, 0.0, 1.0), **common),
    )
    if not all(math.isfinite(value) for row in (origin, *columns) for value in row):
        return None
    translation = tuple((origin[index] - center[index]) * scale for index in range(3))
    scaled_columns = tuple(
        tuple(column[index] * scale for index in range(3))
        for column in columns
    )
    return (
        scaled_columns[0][0], scaled_columns[1][0], scaled_columns[2][0], translation[0],
        scaled_columns[0][1], scaled_columns[1][1], scaled_columns[2][1], translation[1],
        scaled_columns[0][2], scaled_columns[1][2], scaled_columns[2][2], translation[2],
    )


def source_normal_transform_for_transformed_preview(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    transform: StaticReplacementTransform,
    source_submesh_index: int,
    *,
    source_part_adjustments: list[StaticSourcePartAdjustment] | None = None,
    global_transform_exempt_indices: set[int] | None = None,
    global_transform_source_indices: set[int] | None = None,
    alignment_basis_mesh: ParsedMesh | None = None,
    alignment_source_indices: set[int] | None = None,
) -> tuple[float, ...] | None:
    try:
        source_index = int(source_submesh_index)
    except (TypeError, ValueError, OverflowError):
        return None
    if source_index < 0 or source_index >= len(getattr(replacement_mesh, "submeshes", ()) or ()):
        return None
    common = {
        "source_index": source_index,
        "original_mesh": original_mesh,
        "replacement_mesh": replacement_mesh,
        "transform": transform,
        "source_part_adjustments": source_part_adjustments,
        "global_transform_exempt_indices": global_transform_exempt_indices,
        "global_transform_source_indices": global_transform_source_indices if alignment_source_indices is None else alignment_source_indices,
        "alignment_basis_mesh": alignment_basis_mesh,
    }
    columns = (
        _mesh_edit_forward_transformed_normal((1.0, 0.0, 0.0), **common),
        _mesh_edit_forward_transformed_normal((0.0, 1.0, 0.0), **common),
        _mesh_edit_forward_transformed_normal((0.0, 0.0, 1.0), **common),
    )
    if not all(math.isfinite(value) for row in columns for value in row):
        return None
    return (
        columns[0][0], columns[1][0], columns[2][0],
        columns[0][1], columns[1][1], columns[2][1],
        columns[0][2], columns[1][2], columns[2][2],
    )


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
    alignment_source_indices: set[int] | None = None,
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
        "global_transform_source_indices": global_transform_source_indices if alignment_source_indices is None else alignment_source_indices,
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
    try:
        from .mesh_native_core import merge_native_mesh_submeshes

        native_merged = merge_native_mesh_submeshes(submeshes)
    except Exception:
        native_merged = None
    if native_merged is not None:
        native_merged.name = target.name
        native_merged.material = target.material
        native_merged.texture = target.texture
        finalize_merged_skin_provenance(native_merged, submeshes, target)
        return native_merged

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
    finalize_merged_skin_provenance(merged, submeshes, target)
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
    padding: int = 0,
) -> None:
    if not submesh.uvs or len(submesh.uvs) != len(submesh.vertices):
        raise ValueError(
            f"Cannot atlas/bake {source_material_name} into {target_name}: source submesh {source_index} has no complete UV set."
        )
    offset, scale = _atlas_uv_transform(rect, padding=padding)
    try:
        from .mesh_native_core import apply_native_mesh_uv_atlas_submesh

        native_rewritten = apply_native_mesh_uv_atlas_submesh(
            submesh,
            offset=offset,
            scale=scale,
        )
    except ValueError as exc:
        invalid_uv = exc.args[1] if len(exc.args) > 1 else (0.0, 0.0)
        u, v = float(invalid_uv[0]), float(invalid_uv[1])
        raise ValueError(
            f"Cannot atlas/bake {source_material_name} into {target_name}: source UV ({u:.4f}, {v:.4f}) "
            "is outside 0..1; tiled UVs are not supported for automatic complete-swap atlases."
        ) from exc
    except Exception:
        native_rewritten = None
    if native_rewritten:
        return
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
                float(offset[0]) + clamped_u * float(scale[0]),
                float(offset[1]) + clamped_v * float(scale[1]),
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
    return decimate_submesh_for_preview(submesh, max_faces)
