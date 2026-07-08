from __future__ import annotations

from dataclasses import dataclass

from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.ui.archive_browser.static_replacement_preview_models import (
    apply_missing_texture_overlay_color,
    apply_source_selection_overlay_model_state,
    apply_source_selection_overlay_mesh_state,
    clear_preview_mesh_textures,
    clear_preview_model_overlays,
    clone_preview_model,
    combine_alignment_preview_models,
    combine_optional_preview_models,
    combine_preview_with_overlay,
    combine_preview_models,
    disabled_source_indices_from_adjustments,
    direct_source_preview_indices,
    parsed_preview_mesh_from_submeshes,
    preview_overlay_offset,
    preview_submesh_bounds,
    selected_source_overlay_indices,
    should_use_direct_source_preview,
    source_index_groups_for_overlay,
    source_indices_in_range,
    source_indices_from_pairs,
    source_mesh_pairs_for_indices,
    source_overlay_preview_index_state,
    source_preview_geometry_cache_key,
    source_selection_overlay_adjustments,
    source_selection_overlay_editor_id,
    source_selection_overlay_index_state,
    submeshes_from_source_pairs,
    tint_preview_model,
    visible_direct_source_pairs,
)
from cdmw.ui.archive_browser.static_replacement_original_preview_models import (
    original_overlay_preview_model_state,
    original_reference_preview_model_state,
    overlay_editable_mesh_state,
)


def _model(*meshes: ModelPreviewMesh, summary: str = "") -> ModelPreviewData:
    return ModelPreviewData(meshes=list(meshes), summary=summary)


@dataclass(frozen=True)
class Adjustment:
    source_submesh_index: int
    enabled: bool = True


def test_clone_preview_model_clones_model_and_mesh_records() -> None:
    mesh = ModelPreviewMesh(positions=[(1.0, 2.0, 3.0)], indices=[0, 0, 0])
    model = _model(mesh, summary="source")
    plain = object()

    cloned = clone_preview_model(model)

    assert isinstance(cloned, ModelPreviewData)
    assert cloned is not model
    assert cloned.meshes[0] is not mesh
    assert cloned.meshes[0].positions == [(1.0, 2.0, 3.0)]
    assert clone_preview_model(plain) is plain


def test_tint_preview_model_can_clear_preview_textures() -> None:
    model = _model(
        ModelPreviewMesh(
            preview_texture_path="base.dds",
            preview_normal_texture_path="normal.dds",
            preview_material_texture_path="material.dds",
            preview_height_texture_path="height.dds",
        )
    )

    tinted = tint_preview_model(model, (0.1, 0.2, 0.3), clear_textures=True)

    assert isinstance(tinted, ModelPreviewData)
    assert tinted.meshes[0].preview_color == (0.1, 0.2, 0.3)
    assert tinted.meshes[0].preview_texture_path == ""
    assert tinted.meshes[0].preview_normal_texture_path == ""
    assert tinted.meshes[0].preview_material_texture_path == ""
    assert tinted.meshes[0].preview_height_texture_path == ""
    assert model.meshes[0].preview_texture_path == "base.dds"


def test_clear_preview_mesh_textures_resets_known_preview_slots() -> None:
    mesh = ModelPreviewMesh(
        preview_texture_path="base.dds",
        preview_normal_texture_path="normal.dds",
        preview_material_texture_path="material.dds",
        preview_height_texture_path="height.dds",
    )

    clear_preview_mesh_textures(mesh)

    assert mesh.preview_texture_path == ""
    assert mesh.preview_normal_texture_path == ""
    assert mesh.preview_material_texture_path == ""
    assert mesh.preview_height_texture_path == ""


def test_combine_preview_models_clones_meshes_and_updates_counts() -> None:
    first = _model(
        ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0]),
        summary="first",
    )
    second = _model(
        ModelPreviewMesh(
            positions=[(1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
            indices=[0, 1, 1, 0, 0, 1],
        ),
        summary="second",
    )

    combined = combine_preview_models(object(), first, second)

    assert isinstance(combined, ModelPreviewData)
    assert combined.summary == "Overlay alignment preview"
    assert combined.mesh_count == 2
    assert combined.vertex_count == 3
    assert combined.face_count == 3
    assert combined.meshes[0] is not first.meshes[0]
    assert combined.meshes[1] is not second.meshes[0]
    assert combine_preview_models(object()) is None


def test_combine_preview_models_clears_physics_and_skeleton_overlays_by_default() -> None:
    original = ModelPreviewData(
        physics_overlay=object(),
        cloth_preview=object(),
        meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
    )
    replacement = ModelPreviewData(
        meshes=[ModelPreviewMesh(positions=[(1.0, 0.0, 0.0)], indices=[0, 0, 0])]
    )

    combined = combine_alignment_preview_models(original, replacement)

    assert isinstance(combined, ModelPreviewData)
    assert combined.physics_overlay is None
    assert combined.cloth_preview is None


def test_combine_alignment_preview_models_can_preserve_explicit_overlays() -> None:
    overlay = object()
    original = ModelPreviewData(
        physics_overlay=overlay,
        meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
    )
    replacement = ModelPreviewData(
        meshes=[ModelPreviewMesh(positions=[(1.0, 0.0, 0.0)], indices=[0, 0, 0])]
    )

    combined = combine_alignment_preview_models(original, replacement, preserve_overlays=True)

    assert isinstance(combined, ModelPreviewData)
    assert combined.physics_overlay is overlay


def test_clear_preview_model_overlays_does_not_mutate_source_model() -> None:
    overlay = object()
    model = ModelPreviewData(physics_overlay=overlay, cloth_preview=object())

    cleared = clear_preview_model_overlays(model)

    assert isinstance(cleared, ModelPreviewData)
    assert cleared.physics_overlay is None
    assert cleared.cloth_preview is None
    assert model.physics_overlay is overlay


def test_combine_alignment_preview_models_uses_original_frame_authority() -> None:
    original = ModelPreviewData(
        path="original.pac",
        normalization_center=(0.0, 2.0, 0.0),
        normalization_scale=0.5,
        meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
    )
    replacement = ModelPreviewData(
        path="replacement.obj",
        normalization_center=(9.0, 9.0, 9.0),
        normalization_scale=3.0,
        meshes=[ModelPreviewMesh(positions=[(1.0, 0.0, 0.0)], indices=[0, 0, 0])],
    )

    combined = combine_alignment_preview_models(original, replacement)

    assert isinstance(combined, ModelPreviewData)
    assert combined.normalization_center == (0.0, 2.0, 0.0)
    assert combined.normalization_scale == 0.5
    assert combined.preview_frame_kind == "original_pac_frame"
    assert combined.preview_frame_source_path == "original.pac"
    assert combined.preview_grid_mode == "original_frame"
    assert combined.preview_grid_y == -1.0
    assert combined.preview_material_parity_mode == "archive_preview"
    assert combined.preview_original_materials_preserved is True
    assert combined.preview_reference_tint_mode == "overlay_only"
    assert combined.mesh_count == 2


def test_combine_optional_preview_models_preserves_single_model_or_combines_many() -> None:
    first = _model(ModelPreviewMesh(material_name="first"))
    second = _model(ModelPreviewMesh(material_name="second"))

    assert combine_optional_preview_models((None,)) is None
    assert combine_optional_preview_models((None, first)) is first
    combined = combine_optional_preview_models((None, first, second))

    assert isinstance(combined, ModelPreviewData)
    assert [mesh.material_name for mesh in combined.meshes] == ["first", "second"]


def test_preview_overlay_offset_requires_base_model_and_nonempty_overlay() -> None:
    base = _model(ModelPreviewMesh(), ModelPreviewMesh())
    overlay = _model(ModelPreviewMesh())

    assert preview_overlay_offset(base, overlay) == 2
    assert preview_overlay_offset(object(), overlay) is None
    assert preview_overlay_offset(base, None) is None
    assert preview_overlay_offset(base, _model()) is None


def test_combine_preview_with_overlay_keeps_invalid_base_or_empty_overlay() -> None:
    base = _model(ModelPreviewMesh(material_name="base"))
    overlay = _model(ModelPreviewMesh(material_name="overlay"))
    plain = object()

    combined = combine_preview_with_overlay(base, overlay)

    assert isinstance(combined, ModelPreviewData)
    assert [mesh.material_name for mesh in combined.meshes] == ["base", "overlay"]
    assert combine_preview_with_overlay(base, None) is base
    assert combine_preview_with_overlay(plain, overlay) is plain


def test_original_reference_preview_model_state_highlights_without_mutating_source() -> None:
    original = _model(
        ModelPreviewMesh(),
        ModelPreviewMesh(
            material_name="steel",
            texture_name="steel_base",
            preview_texture_path="base.dds",
            preview_normal_texture_path="normal.dds",
            preview_material_texture_path="material.dds",
            preview_height_texture_path="height.dds",
            preview_native_material_overrides={"roughness": 0.42},
        ),
    )

    preview = original_reference_preview_model_state(
        original,
        highlighted_indices=(1,),
        preserve_material_preview=False,
    )

    assert isinstance(preview, ModelPreviewData)
    assert preview is not original
    assert preview.meshes[0].preview_color == (0.22, 0.30, 0.38)
    assert preview.meshes[1].preview_color == (1.0, 0.05, 0.95)
    assert preview.meshes[1].preview_double_sided is True
    assert preview.meshes[1].preview_role == "original_reference_selection_overlay"
    assert preview.meshes[1].material_name == "steel"
    assert preview.meshes[1].texture_name == "steel_base"
    assert preview.meshes[1].preview_texture_path == "base.dds"
    assert preview.meshes[1].preview_normal_texture_path == "normal.dds"
    assert preview.meshes[1].preview_material_texture_path == "material.dds"
    assert preview.meshes[1].preview_height_texture_path == "height.dds"
    assert preview.meshes[1].preview_native_material_overrides == {"roughness": 0.42}
    assert original.meshes[1].preview_color == ()
    preserved = original_reference_preview_model_state(
        original,
        highlighted_indices=(1,),
        preserve_material_preview=True,
    )
    assert preserved.meshes[1].preview_color == ()
    assert preserved.meshes[1].preview_role == "original_reference_selection_overlay"
    assert preserved.meshes[1].preview_texture_path == "base.dds"
    assert preserved.meshes[1].preview_native_material_overrides == {"roughness": 0.42}


def test_original_overlay_preview_model_state_marks_original_meshes_and_highlights() -> None:
    original = _model(
        ModelPreviewMesh(source_submesh_index=7, source_vertex_indices=[1], source_face_indices=[2]),
        ModelPreviewMesh(source_submesh_index=8),
    )

    overlay = original_overlay_preview_model_state(
        original,
        highlighted_indices=(0,),
        highlight_color=(1.0, 0.72, 0.22),
    )

    assert isinstance(overlay, ModelPreviewData)
    assert overlay.meshes[0].source_submesh_index == -1
    assert overlay.meshes[0].source_vertex_indices == []
    assert overlay.meshes[0].source_face_indices == []
    assert overlay.meshes[0].preview_color == (1.0, 0.72, 0.22)
    assert overlay.meshes[0].preview_double_sided is True
    assert overlay.meshes[0].preview_role == "original_reference_selection_overlay"
    assert overlay.meshes[1].preview_color == (0.30, 0.42, 0.54)
    assert original.meshes[0].source_submesh_index == 7


def test_overlay_editable_mesh_state_offsets_selected_or_uses_ranges() -> None:
    assert overlay_editable_mesh_state(
        3,
        5,
        selected_preview_indices=(0, 2),
        original_locked=True,
    ) == ("indices", (3, 5))
    assert overlay_editable_mesh_state(
        3,
        5,
        selected_preview_indices=None,
        original_locked=True,
    ) == ("range", (3, 5))
    assert overlay_editable_mesh_state(
        3,
        5,
        selected_preview_indices=None,
        original_locked=False,
    ) == ("range", (0, -1))


def test_direct_source_preview_indices_combines_candidates_and_filters_disabled() -> None:
    assert direct_source_preview_indices(
        (2, 7),
        force_direct_source_preview=True,
        replacement_submesh_count=4,
        mesh_edit_direct_source_preview=True,
        mesh_edit_source_indices=(5, 6),
        source_index_is_enabled_renderable=lambda index: index not in {1, 6},
    ) == {0, 2, 3, 5, 7}


def test_should_use_direct_source_preview_rejects_missing_or_conflicting_state() -> None:
    assert should_use_direct_source_preview(
        (2,),
        force_direct_source_preview=False,
        mesh_edit_direct_source_preview=False,
        appended_source_indices=(2,),
        mapped_source_indices=(),
        active_preview_mode="side_by_side",
        original_mesh_available=True,
        replacement_mesh_available=True,
    ) is False
    assert should_use_direct_source_preview(
        (3,),
        force_direct_source_preview=False,
        mesh_edit_direct_source_preview=False,
        appended_source_indices=(),
        mapped_source_indices=(3,),
        active_preview_mode="side_by_side",
        original_mesh_available=True,
        replacement_mesh_available=True,
    ) is False
    assert should_use_direct_source_preview(
        (3,),
        force_direct_source_preview=False,
        mesh_edit_direct_source_preview=False,
        appended_source_indices=(),
        mapped_source_indices=(),
        active_preview_mode="source_only",
        original_mesh_available=True,
        replacement_mesh_available=True,
    ) is False
    assert should_use_direct_source_preview(
        (3,),
        force_direct_source_preview=False,
        mesh_edit_direct_source_preview=False,
        appended_source_indices=(),
        mapped_source_indices=(),
        active_preview_mode="side_by_side",
        original_mesh_available=False,
        replacement_mesh_available=True,
    ) is False


def test_should_use_direct_source_preview_allows_clear_or_forced_state() -> None:
    assert should_use_direct_source_preview(
        (2,),
        force_direct_source_preview=False,
        mesh_edit_direct_source_preview=False,
        appended_source_indices=(),
        mapped_source_indices=(),
        active_preview_mode="overlay",
        original_mesh_available=True,
        replacement_mesh_available=True,
    ) is True
    assert should_use_direct_source_preview(
        (2,),
        force_direct_source_preview=True,
        mesh_edit_direct_source_preview=False,
        appended_source_indices=(2,),
        mapped_source_indices=(2,),
        active_preview_mode="replacement_only",
        original_mesh_available=True,
        replacement_mesh_available=True,
    ) is True
    assert should_use_direct_source_preview(
        (2,),
        force_direct_source_preview=False,
        mesh_edit_direct_source_preview=True,
        appended_source_indices=(2,),
        mapped_source_indices=(2,),
        active_preview_mode="side_by_side",
        original_mesh_available=True,
        replacement_mesh_available=True,
    ) is True


def test_source_preview_geometry_cache_key_records_direct_or_mapped_mode() -> None:
    assert source_preview_geometry_cache_key(
        "base",
        use_direct_source_preview=True,
        direct_source_preview_indices=(5, 2, 5),
    ) == "base|direct-source:2,5"
    assert source_preview_geometry_cache_key(
        "base",
        use_direct_source_preview=False,
        direct_source_preview_indices=(5, 2),
    ) == "base|mapped"


def test_source_indices_in_range_normalizes_unique_valid_indices() -> None:
    assert source_indices_in_range((-1, 0, 2, 2, "3", 5), 4) == {0, 2, 3}
    assert source_indices_in_range((0, 1), -1) == set()


def test_selected_source_overlay_indices_filters_markers_and_sorts() -> None:
    visible = type("Source", (), {"marker": False})()
    marker = type("Source", (), {"marker": True})()

    assert selected_source_overlay_indices(
        (2, 0, 1, 8, -1),
        (visible, marker, visible),
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
    ) == (0, 2)


def test_disabled_source_indices_from_adjustments_uses_disabled_adjustments() -> None:
    assert disabled_source_indices_from_adjustments(
        (
            Adjustment(source_submesh_index=3, enabled=False),
            Adjustment(source_submesh_index=1, enabled=True),
            Adjustment(source_submesh_index=5, enabled=False),
        )
    ) == {3, 5}


def test_source_index_groups_for_overlay_splits_selected_source() -> None:
    assert source_index_groups_for_overlay((1, 2, 1, 3), selected_source_index=1) == ((2, 3), (1, 1))


def test_source_mesh_pairs_for_indices_filters_out_of_range_sources() -> None:
    sources = ("a", "b", "c")

    assert source_mesh_pairs_for_indices(sources, (2, -1, 5, 0)) == ((2, "c"), (0, "a"))


def test_source_pair_helpers_project_indices_and_submeshes() -> None:
    first = object()
    second = object()
    pairs = ((3, first), (1, second))

    assert source_indices_from_pairs(pairs) == (3, 1)
    assert submeshes_from_source_pairs(pairs) == [first, second]


def test_preview_submesh_bounds_uses_all_vertices_or_defaults() -> None:
    assert preview_submesh_bounds(
        (
            type("Mesh", (), {"vertices": [(-1.0, 2.0, 3.0), (4.0, -2.0, 0.5)]})(),
            type("Mesh", (), {"vertices": [(2.0, 8.0, -6.0)]})(),
        )
    ) == ((-1.0, -2.0, -6.0), (4.0, 8.0, 3.0))
    assert preview_submesh_bounds(()) == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def test_preview_submesh_bounds_prefers_native_metadata(monkeypatch) -> None:
    from cdmw.modding import mesh_native_core

    class FallbackExplodes:
        @property
        def vertices(self):  # noqa: ANN201
            raise AssertionError("Python vertex scan fallback")

    monkeypatch.setattr(
        mesh_native_core,
        "summarize_native_mesh_submesh_metadata",
        lambda submeshes: {
            "total_vertices": 2,
            "bbox_min": (-2.0, -1.0, 0.5),
            "bbox_max": (3.0, 4.0, 5.0),
        },
    )

    assert preview_submesh_bounds((FallbackExplodes(),)) == ((-2.0, -1.0, 0.5), (3.0, 4.0, 5.0))


def test_parsed_preview_mesh_from_submeshes_summarizes_source_and_parts() -> None:
    source_mesh = type("SourceMesh", (), {"path": "source.pam", "format": "pam"})()
    first = type(
        "Submesh",
        (),
        {
            "vertices": [(1.0, 2.0, 3.0), (-1.0, 0.0, 5.0)],
            "faces": [(0, 1, 2)],
            "uvs": [],
        },
    )()
    second = type(
        "Submesh",
        (),
        {
            "vertices": [(2.0, -3.0, 1.0)],
            "faces": [(0, 0, 0), (0, 0, 0)],
            "uvs": [(0.0, 0.0)],
        },
    )()

    parsed = parsed_preview_mesh_from_submeshes(source_mesh, (first, second))

    assert isinstance(parsed, ParsedMesh)
    assert parsed.path == "source.pam"
    assert parsed.format == "pam"
    assert parsed.bbox_min == (-1.0, -3.0, 1.0)
    assert parsed.bbox_max == (2.0, 2.0, 5.0)
    assert parsed.submeshes == [first, second]
    assert parsed.total_vertices == 3
    assert parsed.total_faces == 3
    assert parsed.has_uvs is True
    assert parsed.has_bones is False


def test_parsed_preview_mesh_from_submeshes_prefers_native_metadata(monkeypatch) -> None:
    from cdmw.modding import mesh_native_core

    class FallbackExplodes:
        @property
        def vertices(self):  # noqa: ANN201
            raise AssertionError("Python vertex-count fallback")

        @property
        def faces(self):  # noqa: ANN201
            raise AssertionError("Python face-count fallback")

        @property
        def uvs(self):  # noqa: ANN201
            raise AssertionError("Python UV fallback")

    monkeypatch.setattr(
        mesh_native_core,
        "summarize_native_mesh_submesh_metadata",
        lambda submeshes: {
            "total_vertices": 123,
            "total_faces": 45,
            "has_uvs": True,
            "bbox_min": (-1.0, -2.0, -3.0),
            "bbox_max": (4.0, 5.0, 6.0),
        },
    )

    parsed = parsed_preview_mesh_from_submeshes(
        type("SourceMesh", (), {"path": "source.pam", "format": "pam"})(),
        (FallbackExplodes(),),
    )

    assert parsed.total_vertices == 123
    assert parsed.total_faces == 45
    assert parsed.has_uvs is True
    assert parsed.bbox_min == (-1.0, -2.0, -3.0)
    assert parsed.bbox_max == (4.0, 5.0, 6.0)


def test_apply_missing_texture_overlay_color_only_colors_untextured_meshes() -> None:
    untextured = ModelPreviewMesh()
    textured = ModelPreviewMesh(preview_texture_path="base.dds")
    model = _model(untextured, textured)

    apply_missing_texture_overlay_color(model, color=(0.4, 0.5, 0.6))

    assert untextured.preview_color == (0.4, 0.5, 0.6)
    assert textured.preview_color == ()


def test_source_overlay_preview_index_state_offsets_source_preview_indices() -> None:
    model = _model(
        ModelPreviewMesh(source_submesh_index=2),
        ModelPreviewMesh(source_submesh_index=-1),
        ModelPreviewMesh(source_submesh_index=4),
    )

    assert source_overlay_preview_index_state(model, overlay_offset=10) == {2: 10, 4: 12}


def test_source_selection_overlay_editor_id_uses_reserved_positive_range() -> None:
    assert source_selection_overlay_editor_id(3) == 2_000_003
    assert source_selection_overlay_editor_id(-5) == 2_000_000


def test_source_selection_overlay_index_state_offsets_and_restores_source_ids() -> None:
    model = _model(
        ModelPreviewMesh(source_submesh_index=2_000_003),
        ModelPreviewMesh(source_submesh_index=2_000_010),
        ModelPreviewMesh(source_submesh_index=-1),
    )

    preview_indices, editor_ids = source_selection_overlay_index_state(model, overlay_offset=5)

    assert preview_indices == {3: 5, 10: 6}
    assert editor_ids == {3: 2_000_003, 10: 2_000_010}


def test_source_selection_overlay_adjustments_reenables_and_adds_selected_sources() -> None:
    adjustments = source_selection_overlay_adjustments(
        (3, 1),
        (
            Adjustment(source_submesh_index=1, enabled=False),
            Adjustment(source_submesh_index=2, enabled=True),
        ),
        Adjustment,
    )

    assert adjustments == [
        Adjustment(source_submesh_index=1, enabled=True),
        Adjustment(source_submesh_index=2, enabled=True),
        Adjustment(source_submesh_index=3, enabled=True),
    ]


def test_apply_source_selection_overlay_mesh_state_preserves_textures_and_marks_overlay() -> None:
    mesh = ModelPreviewMesh(
        texture_name="base",
        preview_texture_path="base.dds",
        preview_normal_texture_path="normal.dds",
        preview_material_texture_path="material.dds",
        preview_height_texture_path="height.dds",
        preview_texture_tint=(1.0, 1.0, 1.0),
        preview_double_sided=False,
    )
    texture_image = object()
    normal_image = object()
    material_image = object()
    height_image = object()
    material_input = object()
    mesh.preview_texture_image = texture_image
    mesh.preview_normal_texture_image = normal_image
    mesh.preview_material_texture_image = material_image
    mesh.preview_height_texture_image = height_image
    mesh.preview_material_texture_inputs = (material_input,)

    apply_source_selection_overlay_mesh_state(mesh, 7)

    assert mesh.texture_name == "base"
    assert mesh.preview_texture_path == "base.dds"
    assert mesh.preview_normal_texture_path == "normal.dds"
    assert mesh.preview_material_texture_path == "material.dds"
    assert mesh.preview_height_texture_path == "height.dds"
    assert mesh.preview_texture_image is texture_image
    assert mesh.preview_normal_texture_image is normal_image
    assert mesh.preview_material_texture_image is material_image
    assert mesh.preview_height_texture_image is height_image
    assert mesh.preview_material_texture_inputs == (material_input,)
    assert mesh.preview_texture_tint == (1.0, 1.0, 1.0)
    assert mesh.preview_color == (1.0, 0.05, 0.95)
    assert mesh.preview_double_sided is True
    assert mesh.preview_role == "replacement_source_selection_overlay"
    assert mesh.preview_native_material_overrides["material_shader_family"] == "gltf_unlit"
    assert mesh.material_name == "selected source overlay 7"


def test_apply_source_selection_overlay_model_state_marks_valid_overlay_meshes() -> None:
    selected = ModelPreviewMesh(
        source_submesh_index=4,
        preview_texture_path="base.dds",
        preview_double_sided=False,
    )
    ignored = ModelPreviewMesh(source_submesh_index=-1)
    model = _model(selected, ignored)

    apply_source_selection_overlay_model_state(model)

    assert selected.source_submesh_index == 2_000_004
    assert selected.preview_texture_path == "base.dds"
    assert selected.preview_role == "replacement_source_selection_overlay"
    assert selected.preview_double_sided is True
    assert ignored.source_submesh_index == -1
    assert ignored.preview_role == ""


def test_visible_direct_source_pairs_filters_requested_disabled_and_marker_sources() -> None:
    visible = type("Source", (), {"marker": False})()
    marker = type("Source", (), {"marker": True})()
    hidden = type("Source", (), {"marker": False})()

    assert visible_direct_source_pairs(
        (visible, marker, hidden),
        requested_source_indices={0, 1, 2},
        disabled_source_indices={2},
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
    ) == ((0, visible),)
