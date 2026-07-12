from __future__ import annotations

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions,
    StaticReplacementTransform,
    StaticSourcePartAdjustment,
    StaticSubmeshMapping,
    _build_mapped_replacement_mesh,
    _transformed_replacement_sources,
    source_affine_for_transformed_preview,
)


def _mesh(path: str, submeshes: list[SubMesh]) -> ParsedMesh:
    return ParsedMesh(
        path=path,
        format="pac",
        submeshes=submeshes,
        total_vertices=sum(len(submesh.vertices) for submesh in submeshes),
        total_faces=sum(len(submesh.faces) for submesh in submeshes),
        has_uvs=any(bool(submesh.uvs) for submesh in submeshes),
    )


def test_hidden_part_does_not_change_surviving_part_alignment_or_affine() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 10.0, 0.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )
    replacement = _mesh(
        "replacement.obj",
        [
            SubMesh(
                name="survivor",
                material="survivor",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            ),
            SubMesh(
                name="hidden_later",
                material="hidden_later",
                vertices=[(10.0, 0.0, 0.0), (20.0, 0.0, 0.0), (10.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            ),
        ],
    )
    mapping = StaticSubmeshMapping(0, "target", [0, 1], 0)
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        source_anchor=(0.0, 0.0, 0.0),
        target_anchor=(0.0, 0.0, 0.0),
        source_axis=(0.0, 0.0, 1.0),
        target_axis=(0.0, 0.0, 1.0),
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        scale_to_original_length=False,
    )
    full_alignment_basis = {0, 1}

    visible_sources = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        global_transform_source_indices={0, 1},
        alignment_source_indices=full_alignment_basis,
        output_source_indices={0, 1},
    )
    hidden_sources = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        [StaticSourcePartAdjustment(source_submesh_index=1, enabled=False)],
        global_transform_source_indices={0},
        alignment_source_indices=full_alignment_basis,
        output_source_indices={0},
    )
    assert hidden_sources[0].vertices == visible_sources[0].vertices
    assert hidden_sources[1].vertices == []

    visible_affine = source_affine_for_transformed_preview(
        original,
        replacement,
        transform,
        0,
        global_transform_source_indices={0, 1},
        alignment_source_indices=full_alignment_basis,
    )
    hidden_affine = source_affine_for_transformed_preview(
        original,
        replacement,
        transform,
        0,
        global_transform_source_indices={0},
        alignment_source_indices=full_alignment_basis,
    )
    assert hidden_affine == visible_affine

    visible_output = _build_mapped_replacement_mesh(
        original,
        replacement,
        [mapping],
        StaticMeshReplacementOptions(transform=transform),
        enforce_vertex_limit=False,
    )
    hidden_output = _build_mapped_replacement_mesh(
        original,
        replacement,
        [mapping],
        StaticMeshReplacementOptions(
            transform=transform,
            source_part_adjustments=[StaticSourcePartAdjustment(source_submesh_index=1, enabled=False)],
        ),
        enforce_vertex_limit=False,
    )
    assert hidden_output.submeshes[0].vertices == visible_output.submeshes[0].vertices[:3]
    assert hidden_output.total_faces == 1
    assert visible_output.total_faces == 2
