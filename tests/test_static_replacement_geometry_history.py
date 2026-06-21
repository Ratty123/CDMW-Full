from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_geometry_history import (
    geometry_history_capture_state,
    geometry_history_guard_initial_state,
    geometry_history_push_state,
    geometry_history_restore_state,
    geometry_mapping_text_by_target,
    geometry_original_copy_text_by_index,
    geometry_reset_status_text,
    geometry_undo_status_text,
)


def test_geometry_history_guard_initial_state_preserves_default() -> None:
    assert geometry_history_guard_initial_state() == {"active": False}


def test_geometry_mapping_text_by_target_prefers_edit_text_then_mapping_fallbacks_and_empty_targets() -> None:
    mapping_edits = [
        (0, SimpleNamespace(text=lambda: "1, 2")),
        (2, SimpleNamespace(text=lambda: "")),
    ]
    mappings_by_target = {
        0: SimpleNamespace(source_submesh_indices=(9,)),
        1: SimpleNamespace(source_submesh_indices=(3, 4)),
    }
    original_mesh = SimpleNamespace(submeshes=[SimpleNamespace(), SimpleNamespace(), SimpleNamespace(), SimpleNamespace()])

    assert geometry_mapping_text_by_target(
        mapping_edits,
        mappings_by_target=mappings_by_target,
        original_mesh=original_mesh,
    ) == {
        0: "1, 2",
        1: "3, 4",
        2: "",
        3: "",
    }


def test_geometry_original_copy_text_by_index_reads_original_copy_column() -> None:
    items = {
        2: SimpleNamespace(text=lambda column: f"two:{column}"),
        "4": SimpleNamespace(text=lambda column: f"four:{column}"),
    }

    assert geometry_original_copy_text_by_index(items) == {2: "two:4", 4: "four:4"}


def test_geometry_history_status_text_preserves_dialog_copy() -> None:
    assert geometry_undo_status_text("Apply advanced mapping") == "Undid Geometry change: Apply advanced mapping."
    assert geometry_undo_status_text("") == "Undid Geometry change: ."
    assert geometry_reset_status_text() == "Reset Geometry changes back to the initial alignment state."


def test_geometry_history_capture_and_restore_state_normalize_snapshot_fields() -> None:
    snapshot = geometry_history_capture_state(
        reason="Delete source part",
        replacement_mesh="mesh",
        replacement_base_mesh="base",
        mapping_text_by_target={0: "1, 2"},
        source_part_adjustments={"2": SimpleNamespace(source_submesh_index=2)},
        source_role_overrides={"2": " body "},
        source_display_overrides={"2": "Cape"},
        original_part_copies=[SimpleNamespace(name="copy")],
        original_copy_text_by_index={1: "src 2"},
        appended_source_indices=("2", "bad"),
        independent_output_source_indices=(3,),
        preview_only_source_indices=(4,),
        dialog_added_supplemental_files=("file.bin",),
        texture_files_for_mapping=("texture.dds",),
        texture_override_assignments={("a",): "b"},
        source_material_texture_override_assignments={("mat",): "tex"},
        copied_original_texture_intents_by_source={"2": ["base"]},
        copied_original_texture_disabled_sources=("2",),
        copied_original_source_indices=("2",),
        copied_original_source_to_original_index={"2": "7"},
        copied_original_physics_sensitive_sources=("2",),
        texture_uv_transform_state={"part": {"scale": 1}},
        texture_uv_global_transform_state={"global": {"scale": 2}},
        mesh_edit_revision="5",
        source_geometry_revision="6",
        morph_slider_values={"jaw": "0.25"},
        morph_slider_post_edit_deltas=[{"jaw": 0.25}],
        morph_slider_topology_blocked={"blocked": True, "reason": "topology"},
        selected_source_index="2",
        selected_source_indices=("2", "bad"),
        selected_target_index="1",
        selected_original_index="0",
        selected_source_highlights=("2",),
        selected_target_source_highlights=("2", "3"),
        transform_source_indices=("2",),
        selected_original_highlights=("0",),
        selected_target_original_highlights=("1",),
    )

    assert snapshot["reason"] == "Delete source part"
    assert snapshot["appended_source_indices"] == {2}
    assert snapshot["mesh_edit_revision"] == 5
    assert snapshot["morph_slider_values"] == {"jaw": 0.25}

    restore = geometry_history_restore_state(
        snapshot,
        default_texture_uv_global_transform_state={"default": {"scale": 1}},
    )
    assert restore.replacement_mesh == "mesh"
    assert restore.replacement_base_mesh == "base"
    assert restore.source_role_overrides == {2: " body "}
    assert restore.source_display_overrides == {2: "Cape"}
    assert restore.copied_original_source_to_original_index == {2: 7}
    assert restore.selected_source_indices == (2,)
    assert restore.selected_target_source_highlights == {2, 3}
    assert restore.original_copy_text_by_index == {1: "src 2"}
    assert restore.mapping_text_by_target == {0: "1, 2"}


def test_geometry_history_push_state_respects_guard_and_limit() -> None:
    ignored = geometry_history_push_state(
        ({"reason": "old"},),
        {"reason": "new"},
        guard_active=True,
        limit=2,
    )
    assert ignored.pushed is False
    assert ignored.snapshots == ({"reason": "old"},)

    pushed = geometry_history_push_state(
        ({"reason": "old"}, {"reason": "middle"}),
        {"reason": "new"},
        guard_active=False,
        limit=2,
    )
    assert pushed.pushed is True
    assert pushed.dropped_oldest is True
    assert pushed.snapshots == ({"reason": "middle"}, {"reason": "new"})
