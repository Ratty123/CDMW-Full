from __future__ import annotations

from types import SimpleNamespace

from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.ui.archive_browser.static_replacement_d3d11_mapping import (
    alignment_default_d3d11_editor_ids,
    alignment_d3d11_display_model,
    alignment_d3d11_editor_ids_for_source_indices,
    alignment_d3d11_preview_source_editor_id_map_state,
    alignment_d3d11_record_direct_source_preview_flags,
    alignment_d3d11_record_source_editor_id_maps,
    alignment_d3d11_source_indices_for_editor_id,
)


def _clone_namespace(model: object) -> object:
    if isinstance(model, SimpleNamespace):
        return SimpleNamespace(**vars(model))
    return model


def test_alignment_d3d11_editor_ids_use_regular_and_overlay_maps() -> None:
    state = {
        "source_to_d3d11_ids": {2: (8, "9", -1), 4: ("bad",)},
        "source_selection_overlay_to_d3d11_ids": {2: (20,), 3: (30,)},
    }

    assert alignment_d3d11_editor_ids_for_source_indices((2, 4, "bad"), state) == (8, 9)
    assert alignment_d3d11_editor_ids_for_source_indices((2, 3), state, selection_overlay=True) == (20, 30)
    assert alignment_d3d11_editor_ids_for_source_indices((5,), {}, selection_overlay=False) == (5,)
    assert alignment_d3d11_editor_ids_for_source_indices((5,), {}, selection_overlay=True) == ()


def test_alignment_d3d11_source_indices_prefer_package_map_then_overlay_then_identity() -> None:
    state = {
        "d3d11_id_to_source_indices": {8: (2, "4", -1), 9: ("bad",)},
        "selection_overlay_d3d11_id_to_source_indices": {9: (12, 13)},
    }

    assert alignment_d3d11_source_indices_for_editor_id(8, state) == (2, 4)
    assert alignment_d3d11_source_indices_for_editor_id(9, state) == (12, 13)
    assert alignment_d3d11_source_indices_for_editor_id(7, {}) == (7,)
    assert alignment_d3d11_source_indices_for_editor_id("bad", {}) == ()


def test_alignment_d3d11_record_source_editor_id_maps_normalizes_state() -> None:
    state: dict[str, object] = {}

    alignment_d3d11_record_source_editor_id_maps(
        state,
        source_to_editor={2: {9, 8}, "bad": {1}},
        selection_overlay_to_editor={3: {7}},
        editor_to_source={9: {4, 2}},
        selection_editor_to_source={7: {3}},
    )

    assert state["source_to_d3d11_ids"] == {2: (8, 9)}
    assert state["source_selection_overlay_to_d3d11_ids"] == {3: (7,)}
    assert state["d3d11_id_to_source_indices"] == {9: (2, 4)}
    assert state["selection_overlay_d3d11_id_to_source_indices"] == {7: (3,)}


def test_alignment_d3d11_preview_source_editor_id_map_state_handles_mapped_preview() -> None:
    model = SimpleNamespace(
        meshes=(
            SimpleNamespace(source_submesh_index=100),
            SimpleNamespace(source_submesh_index=101),
            SimpleNamespace(source_submesh_index=102),
            SimpleNamespace(source_submesh_index=2_000_005),
        )
    )
    mappings = (
        SimpleNamespace(target_submesh_index=9, target_submesh_name="Body", source_submesh_indices=(3, 4)),
    )

    state = alignment_d3d11_preview_source_editor_id_map_state(
        model,
        mapped_preview=True,
        current_mappings=mappings,
        source_overlay_preview_index_map={7: 1},
        source_selection_overlay_preview_index_map={5: 3},
        direct_source_preview_index_map={},
        preview_submesh_index_map={9: 0},
        preview_target_mesh_indices=lambda *_args: (),
    )

    assert state["source_to_editor"] == {7: {101}, 3: {100}, 4: {100}}
    assert state["editor_to_source"] == {101: {7}, 100: {3, 4}}
    assert state["selection_overlay_to_editor"] == {5: {2_000_005}}
    assert state["selection_editor_to_source"] == {2_000_005: {5}}


def test_alignment_d3d11_preview_source_editor_id_map_state_uses_direct_preview_map() -> None:
    model = SimpleNamespace(
        meshes=(
            SimpleNamespace(source_submesh_index=12),
            SimpleNamespace(source_submesh_index=14),
        )
    )

    state = alignment_d3d11_preview_source_editor_id_map_state(
        model,
        mapped_preview=False,
        current_mappings=(),
        source_overlay_preview_index_map={},
        source_selection_overlay_preview_index_map={},
        direct_source_preview_index_map={3: 1},
        preview_submesh_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    )

    assert state["source_to_editor"] == {3: {14}}
    assert state["editor_to_source"] == {14: {3}}


def test_alignment_d3d11_preview_source_editor_id_map_state_falls_back_to_identity() -> None:
    model = SimpleNamespace(
        meshes=(
            SimpleNamespace(source_submesh_index=8),
            SimpleNamespace(source_submesh_index=-1),
        )
    )

    state = alignment_d3d11_preview_source_editor_id_map_state(
        model,
        mapped_preview=False,
        current_mappings=(),
        source_overlay_preview_index_map={},
        source_selection_overlay_preview_index_map={},
        direct_source_preview_index_map={},
        preview_submesh_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    )

    assert state["source_to_editor"] == {8: {8}}
    assert state["editor_to_source"] == {8: {8}}


def test_alignment_d3d11_record_direct_source_preview_flags_returns_force_flag() -> None:
    state: dict[str, object] = {}

    assert alignment_d3d11_record_direct_source_preview_flags(
        state,
        replacement_only_direct_source_preview=False,
        source_owned_direct_source_preview=True,
    ) is True

    assert state["replacement_only_direct_source_preview"] is False
    assert state["source_owned_direct_source_preview"] is True
    assert state["force_direct_source_preview"] is True


def test_alignment_d3d11_display_model_tags_replacement_and_original_workspaces() -> None:
    calls: list[tuple[str, bool]] = []

    def tag_workspace(model: object, role: str, *, editable: bool, clone_model) -> object | None:
        if getattr(model, "invalid", False):
            return None
        tagged = clone_model(model)
        tagged.role = role
        tagged.editable = editable
        calls.append((role, editable))
        return tagged

    def combine_models(*models: object) -> object:
        return SimpleNamespace(roles=tuple(getattr(model, "role", "") for model in models))

    display = alignment_d3d11_display_model(
        SimpleNamespace(name="replacement"),
        SimpleNamespace(name="original"),
        active_preview_mode="side_by_side",
        tag_workspace_model=tag_workspace,
        combine_preview_models=combine_models,
        clone_model=_clone_namespace,
    )

    assert getattr(display, "roles") == ("original_reference", "replacement_preview")
    assert calls == [("replacement_preview", True), ("original_reference", False)]


def test_alignment_d3d11_display_model_falls_back_to_replacement_workspace() -> None:
    def tag_workspace(model: object, role: str, *, editable: bool, clone_model) -> object | None:
        if getattr(model, "invalid", False):
            return None
        tagged = clone_model(model)
        tagged.role = role
        tagged.editable = editable
        return tagged

    replacement_only = alignment_d3d11_display_model(
        SimpleNamespace(name="replacement"),
        SimpleNamespace(name="original"),
        active_preview_mode="replacement_only",
        tag_workspace_model=tag_workspace,
        combine_preview_models=lambda *_models: SimpleNamespace(role="combined"),
        clone_model=_clone_namespace,
    )
    invalid_replacement = alignment_d3d11_display_model(
        SimpleNamespace(invalid=True),
        SimpleNamespace(name="original"),
        active_preview_mode="side_by_side",
        tag_workspace_model=tag_workspace,
        combine_preview_models=lambda *_models: SimpleNamespace(role="combined"),
        clone_model=_clone_namespace,
    )

    assert getattr(replacement_only, "role") == "replacement_preview"
    assert invalid_replacement is None


def test_alignment_d3d11_display_model_clears_external_import_overlays_by_default() -> None:
    original = ModelPreviewData(
        physics_overlay=object(),
        meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
    )
    replacement = ModelPreviewData(
        meshes=[ModelPreviewMesh(positions=[(1.0, 0.0, 0.0)], indices=[0, 0, 0])]
    )

    display = alignment_d3d11_display_model(
        replacement,
        original,
        active_preview_mode="side_by_side",
        tag_workspace_model=lambda model, _role, **_kwargs: model,
        combine_preview_models=lambda *models, **kwargs: SimpleNamespace(models=models, kwargs=kwargs),
        clone_model=lambda model: model,
        external_import=True,
        preserve_overlays=True,
        show_physics_overlay=True,
    )

    assert isinstance(display, ModelPreviewData)
    assert display.physics_overlay is None


def test_alignment_d3d11_display_model_preserves_explicit_non_external_overlays() -> None:
    overlay = object()
    original = ModelPreviewData(
        physics_overlay=overlay,
        meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
    )
    replacement = ModelPreviewData(
        meshes=[ModelPreviewMesh(positions=[(1.0, 0.0, 0.0)], indices=[0, 0, 0])]
    )

    display = alignment_d3d11_display_model(
        replacement,
        original,
        active_preview_mode="side_by_side",
        tag_workspace_model=lambda model, _role, **_kwargs: model,
        combine_preview_models=lambda *models, **kwargs: SimpleNamespace(models=models, kwargs=kwargs),
        clone_model=lambda model: model,
        external_import=False,
        preserve_overlays=True,
        show_physics_overlay=True,
    )

    assert isinstance(display, ModelPreviewData)
    assert display.physics_overlay is overlay


def test_alignment_default_d3d11_editor_ids_prefer_transform_selection() -> None:
    assert alignment_default_d3d11_editor_ids(
        (2, 4),
        3,
        source_index_is_enabled_renderable=lambda _source_index: True,
        editor_ids_for_source_indices=lambda source_indices: tuple(source_index + 10 for source_index in source_indices),
    ) == (12, 14)


def test_alignment_default_d3d11_editor_ids_fallback_to_enabled_renderable_sources() -> None:
    calls: list[tuple[int, ...]] = []

    def editor_ids(source_indices) -> tuple[int, ...]:
        captured = tuple(source_indices)
        calls.append(captured)
        if len(calls) == 1:
            return ()
        return tuple(source_index + 20 for source_index in captured)

    assert alignment_default_d3d11_editor_ids(
        (),
        4,
        source_index_is_enabled_renderable=lambda source_index: source_index in {1, 3},
        editor_ids_for_source_indices=editor_ids,
    ) == (21, 23)
    assert calls == [(), (1, 3)]


def test_alignment_default_d3d11_editor_ids_handles_missing_replacement_mesh() -> None:
    assert alignment_default_d3d11_editor_ids(
        (),
        0,
        source_index_is_enabled_renderable=lambda _source_index: True,
        editor_ids_for_source_indices=lambda _source_indices: (),
    ) == ()
