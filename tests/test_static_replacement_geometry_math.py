from __future__ import annotations

from math import sqrt
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_geometry_math import (
    add_vector3_delta,
    appended_part_work_area_fit,
    center_offset_for_bounds,
    copy_source_part_with_adjustment,
    fit_uniform_scale_for_bounds,
    global_fast_preview_transform_delta,
    global_transform_values,
    mirror_submesh_x,
    part_bbox,
    part_bbox_center,
    part_bbox_diagonal,
    part_fast_preview_transform_delta,
    part_transform_values,
    point_inside_expanded_bbox,
    reference_vertices_for_appended_part,
    source_mirror_plane_x,
    transformed_vertices_for_work_area,
    vertices_for_source_indices,
)


def test_part_bbox_center_and_diagonal_handle_empty_and_extents() -> None:
    assert part_bbox(()) == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    bounds = part_bbox(((2.0, -1.0, 4.0), (-2.0, 3.0, 1.0)))

    assert bounds == ((-2.0, -1.0, 1.0), (2.0, 3.0, 4.0))
    assert part_bbox_center(bounds) == (0.0, 1.0, 2.5)
    assert part_bbox_diagonal(bounds) == sqrt(41)


def test_point_inside_expanded_bbox_uses_margin() -> None:
    bounds = ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))

    assert point_inside_expanded_bbox((1.1, 0.5, 0.5), bounds, margin=0.11) is True
    assert point_inside_expanded_bbox((1.2, 0.5, 0.5), bounds, margin=0.11) is False


def test_add_vector3_delta_pads_truncates_and_adds_components() -> None:
    assert add_vector3_delta((1.0, 2.0), (3.0,)) == (4.0, 2.0, 0.0)
    assert add_vector3_delta((1.0, 2.0, 3.0, 4.0), (-1.0, 0.5, 2.0, 9.0)) == (0.0, 2.5, 5.0)


def test_part_transform_values_uses_adjustment_fields_and_preserves_truncation() -> None:
    adjustment = SimpleNamespace(
        offset_xyz=("1.0", 2.0, 3.0, 4.0),
        rotate_xyz_degrees=(5.0, "6.0"),
        scale_xyz=None,
        uniform_scale="2.5",
    )

    assert part_transform_values(adjustment) == (
        (1.0, 2.0, 3.0),
        (5.0, 6.0),
        (1.0, 1.0, 1.0),
        2.5,
    )


def test_part_transform_values_uses_defaults_for_missing_adjustment_fields() -> None:
    assert part_transform_values(SimpleNamespace()) == (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        1.0,
    )


def test_global_transform_values_converts_offset_rotation_and_scale_vectors() -> None:
    assert global_transform_values(
        ("1.0", 2.0, 3.0, 4.0),
        (5.0, "6.0", 7.0),
        (8.0, 9.0),
    ) == (
        (1.0, 2.0, 3.0),
        (5.0, 6.0, 7.0),
        (8.0, 9.0),
    )


def test_global_fast_preview_transform_delta_scales_translation_and_ratios_scale() -> None:
    baked = ((1.0, 2.0, 3.0), (10.0, 20.0, 30.0), (2.0, 0.0, 4.0))
    current = ((3.0, 5.0, 7.0), (11.0, 18.0, 35.0), (4.0, 9.0, 1.0))

    assert global_fast_preview_transform_delta(baked, current, preview_scale=2.0) == (
        (4.0, 6.0, 8.0),
        (1.0, -2.0, 5.0),
        (2.0, 1.0, 0.25),
    )


def test_part_fast_preview_transform_delta_applies_uniform_scale_ratio() -> None:
    baked = ((1.0, 2.0, 3.0), (10.0, 20.0, 30.0), (2.0, 0.0, 4.0), 2.0)
    current = ((3.0, 5.0, 7.0), (11.0, 18.0, 35.0), (8.0, 9.0, 2.0), 0.5)

    assert part_fast_preview_transform_delta(baked, current, preview_scale=0.5) == (
        (1.0, 1.5, 2.0),
        (1.0, -2.0, 5.0),
        (1.0, 1.0, 0.125),
    )


def test_fit_uniform_scale_and_center_offset_for_bounds() -> None:
    source_vertices = ((0.0, 0.0, 0.0), (2.0, 4.0, 1.0))
    target_vertices = ((10.0, 10.0, 10.0), (14.0, 18.0, 14.0))

    assert fit_uniform_scale_for_bounds(source_vertices, target_vertices) == 2.0
    assert center_offset_for_bounds(source_vertices, target_vertices) == (11.0, 12.0, 11.5)
    assert fit_uniform_scale_for_bounds((), target_vertices) is None
    assert center_offset_for_bounds(source_vertices, ()) is None


def test_vertices_for_source_indices_collects_valid_source_vertices() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[(0.0, 0.0, 0.0)]),
            SimpleNamespace(vertices=[]),
            SimpleNamespace(vertices=[(2.0, 2.0, 2.0)]),
        ]
    )

    assert vertices_for_source_indices(mesh, (0, 2, 5)) == [
        (0.0, 0.0, 0.0),
        (2.0, 2.0, 2.0),
    ]


def test_reference_vertices_for_appended_part_prefers_target_original_then_all() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[]),
            SimpleNamespace(vertices=[(1.0, 1.0, 1.0)]),
            SimpleNamespace(vertices=[(2.0, 2.0, 2.0)]),
        ]
    )

    assert reference_vertices_for_appended_part(mesh, target_index=2, original_index=1) == [(2.0, 2.0, 2.0)]
    assert reference_vertices_for_appended_part(mesh, target_index=0, original_index=1) == [(1.0, 1.0, 1.0)]
    assert reference_vertices_for_appended_part(mesh, target_index=-1, original_index=-1) == [
        (1.0, 1.0, 1.0),
        (2.0, 2.0, 2.0),
    ]
    assert reference_vertices_for_appended_part(None, target_index=0, original_index=0) == []


def test_appended_part_work_area_fit_recenters_and_scales_outlier_sources() -> None:
    source_vertices = ((100.0, 0.0, 0.0), (200.0, 0.0, 0.0))
    reference_vertices = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))

    fit = appended_part_work_area_fit(source_vertices, reference_vertices)

    assert fit is not None
    assert fit.source_center == (150.0, 0.0, 0.0)
    assert fit.target_center == (5.0, 0.0, 0.0)
    assert round(fit.scale, 3) == 0.115
    assert fit.notes == (
        "centered in the current asset work area",
        "scaled 0.115x for preview control",
    )


def test_appended_part_work_area_fit_skips_already_fitted_sources() -> None:
    vertices = ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))

    assert appended_part_work_area_fit(vertices, vertices) is None
    assert appended_part_work_area_fit((), vertices) is None


def test_transformed_vertices_for_work_area_applies_fit_center_and_scale() -> None:
    fit = appended_part_work_area_fit(
        ((100.0, 0.0, 0.0), (200.0, 0.0, 0.0)),
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
    )

    assert fit is not None
    assert transformed_vertices_for_work_area(((100.0, 2.0, 0.0), (200.0, 2.0, 0.0)), fit) == [
        (-0.75, 0.23, 0.0),
        (10.75, 0.23, 0.0),
    ]


def test_source_mirror_plane_x_prefers_original_mesh_center_then_source_center() -> None:
    original_mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(vertices=[(-2.0, 0.0, 0.0), (4.0, 0.0, 0.0)]),
        ]
    )

    assert source_mirror_plane_x(original_mesh, ((100.0, 0.0, 0.0), (200.0, 0.0, 0.0))) == 1.0
    assert source_mirror_plane_x(None, ((100.0, 0.0, 0.0), (200.0, 0.0, 0.0))) == 150.0
    assert source_mirror_plane_x(None, ()) == 0.0


def test_mirror_submesh_x_flips_vertices_normals_faces_and_counts() -> None:
    source = SimpleNamespace(
        vertices=[(2.0, 1.0, 0.0), (4.0, 1.0, 0.0)],
        normals=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2), (3, 4)],
    )

    mirrored = mirror_submesh_x(source, 3.0, normalize_vector=lambda vector: vector)

    assert mirrored is not source
    assert mirrored.vertices == [(4.0, 1.0, 0.0), (2.0, 1.0, 0.0)]
    assert mirrored.normals == [(-1.0, 0.0, 0.0), (-0.0, 1.0, 0.0)]
    assert mirrored.faces == [(0, 2, 1)]
    assert mirrored.vertex_count == 2
    assert mirrored.face_count == 1


def test_copy_source_part_with_adjustment_scales_offsets_rotates_normals_and_counts() -> None:
    source = SimpleNamespace(
        vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        normals=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2), (0, 2, 3)],
    )
    adjustment = SimpleNamespace(
        scale_xyz=(2.0, 1.0, 1.0),
        uniform_scale=1.0,
        offset_xyz=(1.0, 0.0, 0.0),
        rotate_xyz_degrees=(0.0, 0.0, 0.0),
    )

    copied = copy_source_part_with_adjustment(
        source,
        adjustment,
        rotate_vector=lambda vector, _rotation: vector,
        normalize_vector=lambda vector: vector,
    )

    assert copied is not source
    assert copied.vertices == [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    assert copied.normals == [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    assert copied.vertex_count == 2
    assert copied.face_count == 2
