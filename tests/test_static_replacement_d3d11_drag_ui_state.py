from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_d3d11_drag_ui_state import (
    alignment_d3d11_active_transform_preview_key,
    alignment_d3d11_base_global_transform,
    alignment_d3d11_base_part_transform,
    alignment_d3d11_begin_drag_generation,
    alignment_d3d11_commit_drag_generation,
    alignment_d3d11_drag_generation_initial_state,
    alignment_d3d11_drag_part_source_indices,
    alignment_d3d11_drag_transform_update_state,
    alignment_d3d11_drag_total_values,
    alignment_d3d11_drag_total_update_state,
    alignment_d3d11_drag_transaction_initial_state,
    alignment_d3d11_drag_ui_flush_state,
    alignment_d3d11_drag_ui_initial_state,
    alignment_d3d11_finish_drag_preview_state,
    alignment_d3d11_finish_drag_transaction,
    alignment_d3d11_finish_drag_update_state,
    alignment_d3d11_fast_transform_payload,
    alignment_d3d11_global_control_state,
    alignment_d3d11_global_fast_preview_edit_range,
    alignment_d3d11_part_fast_preview_edit_indices,
    alignment_d3d11_preview_scale,
    alignment_d3d11_selected_part_control_state,
    alignment_d3d11_drag_ui_queue_global,
    alignment_d3d11_drag_ui_queue_part,
    alignment_d3d11_drag_ui_take,
    alignment_d3d11_drag_ui_timer_state,
    alignment_d3d11_translation_to_transform_units,
)


def test_alignment_d3d11_drag_ui_queue_global_and_take_resets_state() -> None:
    state = alignment_d3d11_drag_ui_initial_state()

    alignment_d3d11_drag_ui_queue_global(state, offset=(1, 2, 3), rotation=(4, 5, 6))
    global_offset, global_rotation, part_controls = alignment_d3d11_drag_ui_take(state)

    assert global_offset == (1.0, 2.0, 3.0)
    assert global_rotation == (4.0, 5.0, 6.0)
    assert part_controls == {}
    assert state == {"global_offset": None, "global_rotation": None, "part_controls": {}}


def test_alignment_d3d11_drag_ui_queue_part_merges_offset_and_rotation() -> None:
    state = alignment_d3d11_drag_ui_initial_state()

    alignment_d3d11_drag_ui_queue_part(state, 4, offset=(1, 2, 3))
    alignment_d3d11_drag_ui_queue_part(state, 4, rotation=(7, 8, 9))
    _global_offset, _global_rotation, part_controls = alignment_d3d11_drag_ui_take(state)

    assert part_controls == {4: {"offset": (1.0, 2.0, 3.0), "rotation": (7.0, 8.0, 9.0)}}


def test_alignment_d3d11_drag_ui_flush_state_normalizes_global_and_part_updates() -> None:
    assert alignment_d3d11_drag_ui_flush_state(
        (1, 2),
        (3, 4, 5),
        {
            "4": {"offset": (6, 7), "rotation": (8, 9, 10)},
            "bad": {"offset": (1, 2, 3)},
            5: "not-a-mapping",
        },
    ) == {
        "global": {
            "apply": True,
            "offset": (1.0, 2.0, 0.0),
            "rotation": (3.0, 4.0, 5.0),
        },
        "parts": (
            {
                "source_index": 4,
                "offset": (6.0, 7.0, 0.0),
                "rotation": (8.0, 9.0, 10.0),
            },
        ),
    }
    assert alignment_d3d11_drag_ui_flush_state(None, None, None) == {
        "global": {"apply": False, "offset": None, "rotation": None},
        "parts": (),
    }


def test_alignment_d3d11_begin_drag_generation_records_transaction_snapshot() -> None:
    generation = alignment_d3d11_drag_generation_initial_state()
    transaction = alignment_d3d11_drag_transaction_initial_state()

    result = alignment_d3d11_begin_drag_generation(
        generation,
        transaction,
        part_source_indices=(2, 4),
        global_values="global-values",
        part_values_by_source_index={2: "part-two", 4: "part-four"},
    )

    assert result == 1
    assert generation == {"value": 1, "active": 1, "committed": 0}
    assert transaction == {
        "active": True,
        "generation": 1,
        "part_source_indices": (2, 4),
        "global": "global-values",
        "parts": {2: "part-two", 4: "part-four"},
    }


def test_alignment_d3d11_commit_drag_generation_uses_active_fallback() -> None:
    generation = {"value": 3, "active": 3, "committed": 2}
    transaction = alignment_d3d11_drag_transaction_initial_state()

    committed = alignment_d3d11_commit_drag_generation(generation, transaction)

    assert committed == 3
    assert generation == {"value": 3, "active": 0, "committed": 3}
    assert transaction["generation"] == 0


def test_alignment_d3d11_commit_drag_generation_prefers_transaction_generation() -> None:
    generation = {"value": 5, "active": 4, "committed": 3}
    transaction = alignment_d3d11_drag_transaction_initial_state()
    transaction["generation"] = 5

    committed = alignment_d3d11_commit_drag_generation(generation, transaction)

    assert committed == 5
    assert generation == {"value": 5, "active": 0, "committed": 5}
    assert transaction["generation"] == 0


def test_alignment_d3d11_finish_drag_transaction_commits_and_returns_part_indices() -> None:
    generation = {"value": 7, "active": 7, "committed": 3}
    transaction = {
        "active": True,
        "generation": 7,
        "part_source_indices": ("2", 4),
        "global": None,
        "parts": {},
    }

    part_indices = alignment_d3d11_finish_drag_transaction(generation, transaction)

    assert part_indices == (2, 4)
    assert generation == {"value": 7, "active": 0, "committed": 7}
    assert transaction["active"] is False
    assert transaction["generation"] == 0


def test_alignment_d3d11_finish_drag_preview_state_routes_part_or_global_refresh() -> None:
    assert alignment_d3d11_finish_drag_preview_state(("2", 4)) == {
        "part_source_indices": (2, 4),
        "refresh_source_columns": True,
        "queue_part_preview": True,
        "queue_global_preview": False,
    }
    assert alignment_d3d11_finish_drag_preview_state(()) == {
        "part_source_indices": (),
        "refresh_source_columns": False,
        "queue_part_preview": False,
        "queue_global_preview": True,
    }


def test_alignment_d3d11_finish_drag_update_state_commits_and_routes_refresh() -> None:
    generation = {"value": 9, "active": 9, "committed": 2}
    transaction = {
        "active": True,
        "generation": 9,
        "part_source_indices": ("3", 5),
        "global": None,
        "parts": {},
    }

    assert alignment_d3d11_finish_drag_update_state(generation, transaction) == {
        "part_source_indices": (3, 5),
        "refresh_source_columns": True,
        "queue_part_preview": True,
        "queue_global_preview": False,
    }
    assert generation == {"value": 9, "active": 0, "committed": 9}
    assert transaction["active"] is False
    assert transaction["generation"] == 0


def test_alignment_d3d11_base_global_transform_uses_transaction_snapshot_or_fallback() -> None:
    fallback = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (1.0, 1.0, 1.0))
    snapshot = ((7.0, 8.0, 9.0), (10.0, 11.0, 12.0), (2.0, 2.0, 2.0))

    assert alignment_d3d11_base_global_transform({"global": snapshot}, fallback) == snapshot
    assert alignment_d3d11_base_global_transform({"global": ("bad",)}, fallback) == fallback
    assert alignment_d3d11_base_global_transform({}, fallback) == fallback


def test_alignment_d3d11_base_part_transform_uses_transaction_snapshot_or_fallback() -> None:
    fallback = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (1.0, 1.0, 1.0), 1.0)
    snapshot = ((7.0, 8.0, 9.0), (10.0, 11.0, 12.0), (2.0, 2.0, 2.0), 3.0)

    assert alignment_d3d11_base_part_transform({"parts": {4: snapshot}}, 4, fallback) == snapshot
    assert alignment_d3d11_base_part_transform({"parts": {4: ("bad",)}}, 4, fallback) == fallback
    assert alignment_d3d11_base_part_transform({}, 4, fallback) == fallback


def test_alignment_d3d11_drag_part_source_indices_normalizes_transaction() -> None:
    assert alignment_d3d11_drag_part_source_indices({"part_source_indices": ("2", 4)}) == (2, 4)
    assert alignment_d3d11_drag_part_source_indices({}) == ()


def test_alignment_d3d11_preview_scale_reads_valid_normalization_scale() -> None:
    class PreviewModel:
        normalization_scale = 2.5

    class BadPreviewModel:
        normalization_scale = "bad"

    assert alignment_d3d11_preview_scale(PreviewModel()) == 2.5
    assert alignment_d3d11_preview_scale(BadPreviewModel()) == 1.0
    assert alignment_d3d11_preview_scale(None) == 1.0


def test_alignment_d3d11_translation_to_transform_units_divides_by_preview_scale() -> None:
    assert alignment_d3d11_translation_to_transform_units((2, 4, 6), preview_scale=2.0) == (1.0, 2.0, 3.0)
    assert alignment_d3d11_translation_to_transform_units((2, 4), preview_scale=0.0) == (2.0, 4.0, 0.0)
    assert alignment_d3d11_translation_to_transform_units((2, 4, 6), preview_scale="bad") == (2.0, 4.0, 6.0)


def test_alignment_d3d11_drag_total_values_adds_delta() -> None:
    assert alignment_d3d11_drag_total_values((1, 2, 3), (4, 5, 6)) == (5.0, 7.0, 9.0)
    assert alignment_d3d11_drag_total_values((1, 2), (4,)) == (5.0, 2.0, 0.0)


def test_alignment_d3d11_drag_total_update_state_routes_global_or_part_values() -> None:
    global_state = alignment_d3d11_drag_total_update_state(
        part_source_indices=(),
        delta_xyz=(4, 5, 6),
        global_base_values=(1, 2, 3),
    )

    assert global_state == {
        "scope": "global",
        "global_value": (5.0, 7.0, 9.0),
        "part_values": {},
    }

    part_state = alignment_d3d11_drag_total_update_state(
        part_source_indices=("2", 4),
        delta_xyz=(1, 1, 1),
        part_base_values={2: (10, 20, 30), 4: (40, 50, 60)},
    )

    assert part_state == {
        "scope": "parts",
        "global_value": None,
        "part_values": {2: (11.0, 21.0, 31.0), 4: (41.0, 51.0, 61.0)},
    }


def test_alignment_d3d11_drag_transform_update_state_extracts_part_transform_component() -> None:
    state = alignment_d3d11_drag_transform_update_state(
        part_source_indices=("2", 4),
        delta_xyz=(1, 1, 1),
        value_index=1,
        part_transform_values={
            2: ((10, 20, 30), (40, 50, 60), (1, 1, 1), 1.0),
            4: ((1, 2, 3), (4, 5, 6), (1, 1, 1), 1.0),
        },
    )

    assert state == {
        "scope": "parts",
        "global_value": None,
        "part_values": {2: (41.0, 51.0, 61.0), 4: (5.0, 6.0, 7.0)},
    }


def test_alignment_d3d11_drag_transform_update_state_routes_global_component() -> None:
    assert alignment_d3d11_drag_transform_update_state(
        part_source_indices=(),
        delta_xyz=(1, 2, 3),
        value_index=0,
        global_base_values=(10, 20, 30),
    ) == {
        "scope": "global",
        "global_value": (11.0, 22.0, 33.0),
        "part_values": {},
    }


def test_alignment_d3d11_selected_part_control_state_matches_and_normalizes_vectors() -> None:
    assert alignment_d3d11_selected_part_control_state(
        "4",
        4,
        offset=(1, 2),
        rotation=(3, 4, 5, 6),
    ) == {
        "apply": True,
        "offset": (1.0, 2.0, 0.0),
        "rotation": (3.0, 4.0, 5.0),
    }
    assert alignment_d3d11_selected_part_control_state(3, 4, offset=(1, 2, 3)) == {
        "apply": False,
        "offset": None,
        "rotation": None,
    }
    assert alignment_d3d11_selected_part_control_state("bad", 4, offset=(1, 2, 3)) == {
        "apply": False,
        "offset": None,
        "rotation": None,
    }


def test_alignment_d3d11_global_control_state_normalizes_vectors() -> None:
    assert alignment_d3d11_global_control_state(offset=(1, 2), rotation=(3, 4, 5, 6)) == {
        "apply": True,
        "offset": (1.0, 2.0, 0.0),
        "rotation": (3.0, 4.0, 5.0),
    }
    assert alignment_d3d11_global_control_state() == {
        "apply": False,
        "offset": None,
        "rotation": None,
    }


def test_alignment_d3d11_drag_ui_timer_state_starts_only_when_inactive() -> None:
    assert alignment_d3d11_drag_ui_timer_state(active=False) == {"start_timer": True}
    assert alignment_d3d11_drag_ui_timer_state(active=True) == {"start_timer": False}


def test_alignment_d3d11_active_transform_preview_key_selects_host() -> None:
    assert alignment_d3d11_active_transform_preview_key("replacement_only") == "replacement_only"
    assert alignment_d3d11_active_transform_preview_key("overlay") == "overlay"
    assert alignment_d3d11_active_transform_preview_key("side_by_side") == "static"
    assert alignment_d3d11_active_transform_preview_key(None) == "static"


def test_alignment_d3d11_global_fast_preview_edit_range_scopes_overlay_replacement_meshes() -> None:
    assert alignment_d3d11_global_fast_preview_edit_range(
        "overlay",
        original_mesh_count=4,
        current_mesh_count=11,
    ) == (4, 7)
    assert alignment_d3d11_global_fast_preview_edit_range(
        "overlay",
        original_mesh_count=6,
        current_mesh_count=2,
    ) == (6, 0)
    assert alignment_d3d11_global_fast_preview_edit_range(
        "side_by_side",
        original_mesh_count=4,
        current_mesh_count=11,
    ) == (0, -1)
    assert alignment_d3d11_global_fast_preview_edit_range(
        "overlay",
        original_mesh_count=None,
        current_mesh_count=11,
    ) == (0, -1)


def test_alignment_d3d11_part_fast_preview_edit_indices_offset_overlay_selection() -> None:
    assert alignment_d3d11_part_fast_preview_edit_indices(
        (0, 2, 5),
        "overlay",
        original_mesh_count=4,
    ) == (4, 6, 9)
    assert alignment_d3d11_part_fast_preview_edit_indices(
        (0, 2, 5),
        "side_by_side",
        original_mesh_count=4,
    ) == (0, 2, 5)
    assert alignment_d3d11_part_fast_preview_edit_indices(
        (),
        "overlay",
        original_mesh_count=4,
    ) == ()
    assert alignment_d3d11_part_fast_preview_edit_indices(
        None,
        "overlay",
        original_mesh_count=4,
    ) is None


def test_alignment_d3d11_fast_transform_payload_normalizes_values() -> None:
    payload = alignment_d3d11_fast_transform_payload(
        source_submesh_indices=(3, -1, 2, 3),
        translation=(1, 2),
        rotation_degrees=(4, 5, 6, 7),
        scale_xyz=(2,),
        transform_generation=9,
    )

    assert payload == {
        "source_submesh_indices": (2, 3),
        "translation": (1.0, 2.0, 0.0),
        "rotation_degrees": (4.0, 5.0, 6.0),
        "scale_xyz": (2.0, 1.0, 1.0),
        "transform_generation": 9,
    }
