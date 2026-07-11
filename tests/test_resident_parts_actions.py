import copy
from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.static_mesh_types import StaticSourcePartAdjustment
from cdmw.ui.archive_browser.static_replacement_mesh_edit_actions import create_actions_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_controls_history import create_controls_history_callbacks
from cdmw.ui.archive_browser.static_replacement_dialog_remaining_callbacks import (
    create_alignment_selected_part_adjustment_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_source_role_tree_callbacks import (
    _SourcePartMenuDispatcher,
)
from cdmw.ui.archive_browser.static_replacement_source_parts_state import (
    dispatch_source_part_context_action,
    source_part_adjustment_apply_state,
    source_part_context_action_specs,
    source_part_edit_undo_label,
    source_part_include_exclude_pending_reason,
)
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from cdmw.ui.mesh_editor.tab_state import MeshEditorStateMixin
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh


def test_multi_part_duplicate_reports_each_resident_part_and_undo() -> None:
    session = StaticReplacementMeshEditSession(session_id="static-multi-duplicate")
    session.open(_build_two_part_synthetic_mesh())
    try:
        duplicated = session.apply("duplicate", source_indices=(0, 1))

        assert duplicated.new_submesh_source_indices == ((2, 0), (3, 1))
        assert duplicated.edit_result.submesh_count_delta == 2
        assert session.view().undo_count == 1
        assert session.view().submesh_count == 4

        assert session.undo().edit_result.ok
        assert session.view().submesh_count == 2
        assert session.view().session_id == "static-multi-duplicate"
    finally:
        session.close()


def test_whole_part_delete_stays_resident_and_shrinks_affected_draw_batches() -> None:
    session = StaticReplacementMeshEditSession(session_id="static-part-delete")
    session.open(_build_two_part_synthetic_mesh())
    try:
        deleted = session.apply("delete", source_indices=(0,), delete_parts=True)

        assert deleted.edit_result.ok
        assert (deleted.native_update.replace_all_triangles, deleted.native_update.final_submesh_count, tuple(deleted.native_update.triangle_source_submesh_indices)) == (False, 1, (0, 1))
        assert deleted.edit_result.submesh_count_delta == -1
        assert session.view().session_id == "static-part-delete"
        assert session.view().undo_count == 1

        session.undo()
        assert session.view().submesh_count == 2
        assert session.view().session_id == "static-part-delete"
    finally:
        session.close()


def test_embedded_delete_action_uses_resident_service_instead_of_legacy_delete() -> None:
    mesh = _build_two_part_synthetic_mesh()
    session = StaticReplacementMeshEditSession(session_id="embedded-delete-action")
    session.open(mesh)
    committed: list[object] = []
    state = SimpleNamespace(
        _mesh_edit_state=SimpleNamespace(replacement_mesh_for_mapping=mesh),
        self=SimpleNamespace(set_status_message=lambda *_args, **_kwargs: None),
        _delete_selected_source_parts=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy delete path")
        ),
    )
    callbacks = SimpleNamespace(
        _mesh_edit_record_snapshot=lambda: None,
        _mesh_editor_apply_static_replacement_edit=lambda _mesh, action, **params: session.apply(action, **params),
        _mesh_editor_commit_action_bar_service_result=lambda result, **_kwargs: committed.append(result) or True,
    )
    actions = create_actions_callbacks(state, callbacks)
    try:
        assert actions._mesh_editor_embedded_run_part_action("delete", (0,))
        assert len(committed) == 1
        assert session.view().submesh_count == 1
        assert session.view().undo_count == 1
        assert session.view().session_id == "embedded-delete-action"
    finally:
        session.close()


def test_canonical_parts_dispatcher_uses_resident_actions_and_shared_metadata_handlers() -> None:
    resident_actions: list[tuple[str, tuple[int, ...]]] = []
    roles: list[tuple[int, str]] = []
    routes: list[tuple[int, int]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_run_part_action=lambda action, indices: resident_actions.append(
            (str(action), tuple(indices))
        ) or True,
    )
    dispatcher = _SourcePartMenuDispatcher(
        {
            "dialog": dialog,
            "_alignment_mesh_edit_tab_active": lambda: True,
            "_delete_selected_source_parts": lambda *_args: (_ for _ in ()).throw(
                AssertionError("legacy delete path")
            ),
            "_apply_parts_outliner_source_target": lambda source, target: routes.append((source, target)),
            "selected_target_slot": {"index": 4},
        }
    )

    assert dispatcher.dispatch(
        "delete",
        clicked_source_index=1,
        source_indices=[0, 1],
        all_visible=True,
        apply_role=lambda source, role, _label: roles.append((source, role)),
    )
    assert dispatcher.dispatch(
        "set_role_glow",
        clicked_source_index=1,
        source_indices=[0, 1],
        all_visible=True,
        apply_role=lambda source, role, _label: roles.append((source, role)),
    )
    assert dispatcher.dispatch(
        "route_selected_target",
        clicked_source_index=1,
        source_indices=[0, 1],
        all_visible=True,
        apply_role=None,
    )
    assert dispatcher.dispatch(
        "undo",
        clicked_source_index=1,
        source_indices=[0, 1],
        all_visible=True,
        apply_role=None,
    )

    assert resident_actions == [("delete", (0, 1)), ("undo", (0, 1))]
    assert roles == [(0, "glow"), (1, "glow")]
    assert routes == [(0, 4), (1, 4)]


def test_canonical_parts_specs_cover_parity_and_keep_reset_disabled() -> None:
    specs = source_part_context_action_specs(
        has_selection=True,
        all_visible=False,
        can_route=True,
        can_undo=True,
        can_redo=False,
    )
    by_key = {spec.key: spec for spec in specs}

    assert set(by_key) == {
        "select_only", "toggle_selection", "duplicate", "delete", "set_role_glow",
        "set_role_auto", "toggle_visibility", "route_selected_target", "undo", "redo", "reset",
    }
    assert by_key["toggle_visibility"].label == "Show Selected Part(s)"
    assert by_key["redo"].enabled is False
    assert by_key["reset"].enabled is False
    assert "native reset command" in by_key["reset"].unavailable_reason

    called: list[str] = []
    assert dispatch_source_part_context_action("delete", {"delete": lambda: called.append("delete")})
    assert called == ["delete"]
    assert dispatch_source_part_context_action("reset", {}) is False


def test_resident_visibility_change_is_not_blocked_as_geometry() -> None:
    class _Control:
        def __init__(self, value: object) -> None:
            self._value = value

        def value(self) -> object:
            return self._value

        def isChecked(self) -> bool:
            return bool(self._value)

    class _Item:
        def __init__(self) -> None:
            self.check_state = 1

        def setCheckState(self, _column: int, state: int) -> None:
            self.check_state = int(state)

    adjustments = {0: StaticSourcePartAdjustment(source_submesh_index=0)}
    item = _Item()
    sent_groups: list[tuple[dict[str, object], ...]] = []
    undo: list[tuple[str, dict[str, object]]] = []
    transform_updates: list[object] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: sent_groups.append(tuple(groups)) or True,
    )
    context = {
        "Qt": SimpleNamespace(Checked=1, Unchecked=0),
        "StaticSourcePartAdjustment": StaticSourcePartAdjustment,
        "dialog": dialog,
        "self": SimpleNamespace(set_status_message=lambda *_args, **_kwargs: None),
        "part_inspector_loading": {"active": False},
        "selected_source_part": {"index": 0},
        "source_part_adjustments": adjustments,
        "source_items_by_index": {0: item},
        "source_tree_item_update_guard": {"active": False},
        "part_enabled_checkbox": _Control(False),
        "part_offset_x_spin": _Control(0.0),
        "part_offset_y_spin": _Control(0.0),
        "part_offset_z_spin": _Control(0.0),
        "part_rotate_x_spin": _Control(0.0),
        "part_rotate_y_spin": _Control(0.0),
        "part_rotate_z_spin": _Control(0.0),
        "part_scale_x_spin": _Control(1.0),
        "part_scale_y_spin": _Control(1.0),
        "part_scale_z_spin": _Control(1.0),
        "part_uniform_spin": _Control(1.0),
        "_source_part_adjustment_apply_state_helper": source_part_adjustment_apply_state,
        "_selected_source_indices_from_tree": lambda: (0,),
        "_alignment_mesh_edit_tab_active": lambda: True,
        "_alignment_d3d11_preview_active": lambda: False,
        "_ensure_source_part_adjustment": lambda index: adjustments.setdefault(
            index, StaticSourcePartAdjustment(source_submesh_index=index)
        ),
        "_push_geometry_undo_snapshot": lambda label, **kwargs: undo.append((label, kwargs)),
        "_source_part_edit_undo_label_helper": source_part_edit_undo_label,
        "_source_part_include_exclude_pending_reason_helper": source_part_include_exclude_pending_reason,
        "_refresh_source_assignment_columns": lambda **_kwargs: None,
        "_sync_highlight_sets": lambda: None,
        "_clear_source_parts_apply_pending": lambda: None,
        "_set_source_parts_apply_pending": lambda _reason: None,
        "_set_source_parts_preview_rebuild_pending": lambda _reason: None,
        "_queue_part_transform_preview_update": transform_updates.append,
        "_queue_static_preview_rebuild": lambda: None,
    }
    visibility_state = source_part_adjustment_apply_state(
        adjustments,
        source_index=0,
        selected_source_indices=(),
        enabled=False,
        offset_xyz=(0.0, 0.0, 0.0),
        rotate_xyz_degrees=(0.0, 0.0, 0.0),
        scale_xyz=(1.0, 1.0, 1.0),
        uniform_scale=1.0,
        default_adjustment=StaticSourcePartAdjustment,
    )
    assert visibility_state.enabled_changed is True
    assert visibility_state.geometry_changed is False
    callbacks = create_alignment_selected_part_adjustment_callbacks(context)

    assert callbacks._update_selected_part_adjustment()

    assert adjustments[0].enabled is False
    assert item.check_state == 0
    assert sent_groups == [({"source_submesh_indices": [0], "editor_role": "replacement_preview", "visible": False},)]
    assert undo == [("Toggle source output", {"metadata_only": True})]
    assert transform_updates == []


def test_multi_duplicate_sync_preserves_part_metadata_routes_and_selection() -> None:
    mesh = _build_two_part_synthetic_mesh()
    mesh.submeshes.extend(copy.deepcopy(mesh.submeshes))
    adjustments = {
        0: StaticSourcePartAdjustment(source_submesh_index=0, emissive_strength=2.5),
        1: StaticSourcePartAdjustment(source_submesh_index=1, enabled=False),
    }
    role_overrides = {0: "glow", 1: "cloth"}
    display_overrides = {0: "Glow trim", 1: "Cape"}
    independent = {0}
    preview_only = {1}
    mapping_edits = [(5, [0, 1])]
    mapping_updates: list[tuple[int, list[int]]] = []
    rebuilt: list[tuple[tuple[int, ...], int]] = []
    highlights: set[int] = set()
    transforms: set[int] = set()
    resident_groups: list[tuple[dict[str, object], ...]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_apply_material_parameters=lambda groups: resident_groups.append(tuple(groups)) or True,
    )
    state = SimpleNamespace(
        context={
            "source_part_adjustments": adjustments,
            "source_role_overrides": role_overrides,
            "source_display_overrides": display_overrides,
            "independent_output_source_indices": independent,
            "preview_only_source_indices": preview_only,
            "mapping_edits": mapping_edits,
            "_parse_mapping_edit": lambda edit: list(edit),
            "_set_mapping_indices": lambda target, values, **_kwargs: mapping_updates.append((target, list(values))),
            "selected_source_highlight_indices": highlights,
            "transform_source_indices": transforms,
            "_invalidate_source_display_cache": lambda: None,
        },
        appended_source_indices=set(),
        dialog=dialog,
        _mesh_edit_state=SimpleNamespace(replacement_mesh_for_mapping=mesh),
        selected_source_part={"index": -1},
        copy=copy,
        StaticSourcePartAdjustment=StaticSourcePartAdjustment,
        _rebuild_source_part_widgets=lambda indices, current_index=-1: rebuilt.append((tuple(indices), current_index)),
    )
    actions = create_actions_callbacks(state, SimpleNamespace())

    actions._mesh_editor_sync_new_source_part(
        SimpleNamespace(new_submesh_source_indices=((2, 0), (3, 1)))
    )

    assert state.appended_source_indices == {2, 3}
    assert adjustments[2].emissive_strength == 2.5
    assert adjustments[3].enabled is True
    assert role_overrides[2] == "glow"
    assert role_overrides[3] == "cloth"
    assert display_overrides[2] == "Glow trim Copy"
    assert display_overrides[3] == "Cape Copy"
    assert independent == {0, 2}
    assert preview_only == {1, 3}
    assert mapping_updates == [(5, [0, 1, 2, 3])]
    assert highlights == transforms == {2, 3}
    assert rebuilt == [((2, 3), 2)]
    assert len(resident_groups) == 1
    assert [group["source_submesh_indices"] for group in resident_groups[0]] == [[2], [3]]
    assert resident_groups[0][0]["material_role"] == "glow"
    assert resident_groups[0][0]["emissive_intensity"] == 2.5
    assert resident_groups[0][1]["material_role"] == "cloth"
    assert resident_groups[0][1]["emissive_intensity"] is None
    assert resident_groups[0][1]["visible"] is True


def test_embedded_list_selection_replaces_resident_viewport_selection_exactly() -> None:
    controller = MeshEditorController()
    controller.open_mesh(_build_two_part_synthetic_mesh(), session_id="embedded-list-sync", mode="edit")
    updates: list[object] = []
    refreshes: list[bool] = []
    owner = SimpleNamespace(
        _embedded_builder_controller=lambda: controller,
        _apply_embedded_native_update=lambda update: updates.append(update) or True,
        _send_embedded_dotnet_native_update=lambda update: updates.append(update) or True,
        _refresh_embedded_workspace_from_builder=lambda: refreshes.append(True),
    )
    try:
        assert MeshEditorStateMixin._set_embedded_part_selection(owner, (1, 0, 1))
        assert controller.session_view().selection.source_indices == (0, 1)
        assert len(updates) == 2
        assert all(update.refresh_selection for update in updates)
        assert refreshes == [True]
    finally:
        controller.close_active_session()


def test_mesh_edit_metadata_snapshot_restores_without_legacy_enable_fallback() -> None:
    restored: list[dict[str, object]] = []
    blocked: list[object] = []
    state = SimpleNamespace(
        Mapping=dict,
        _restore_geometry_history_state=lambda snapshot: restored.append(dict(snapshot)),
        mesh_edit_revision={"value": 7},
        source_geometry_revision={"value": 9},
        _mesh_edit_enabled_snapshot_items_helper=lambda snapshot: tuple(snapshot.items()),
        self=SimpleNamespace(set_status_message=lambda *args, **kwargs: blocked.append((args, kwargs))),
    )
    callbacks = SimpleNamespace(_record_mesh_edit_event=lambda *args, **kwargs: blocked.append((args, kwargs)))
    history = create_controls_history_callbacks(state, callbacks)

    history._mesh_edit_restore_enabled_snapshot(
        {
            "metadata_only": True,
            "mesh_edit_revision": 2,
            "source_geometry_revision": 3,
            "source_role_overrides": {0: "glow"},
            "mapping_text_by_target": {0: "0"},
        }
    )

    assert restored[0]["mesh_edit_revision"] == 7
    assert restored[0]["source_geometry_revision"] == 9
    assert restored[0]["source_role_overrides"] == {0: "glow"}
    assert restored[0]["mapping_text_by_target"] == {0: "0"}
    assert blocked == []


def test_resident_part_paths_keep_metadata_snapshots_and_exact_selection_bridge() -> None:
    root = Path(__file__).resolve().parents[1]
    history_source = (root / "cdmw/ui/archive_browser/static_replacement_mesh_edit_controls_history.py").read_text(encoding="utf-8")
    selection_source = (root / "cdmw/ui/archive_browser/static_replacement_dialog_callbacks_source_tree_selection_part_01.py").read_text(encoding="utf-8")

    assert "_mesh_edit_part_state_snapshot()" in history_source
    assert "_mesh_editor_embedded_set_part_selection" in selection_source
    assert "_mesh_editor_embedded_apply_part_selection_from_viewport" in selection_source


def test_all_parts_surfaces_share_menu_and_routing_waits_for_confirmation() -> None:
    root = Path(__file__).resolve().parents[1]
    outliner = (root / "cdmw/ui/archive_browser/static_replacement_dialog_callbacks_parts_outliner_mapping_part_01.py").read_text(encoding="utf-8")
    mapping = (root / "cdmw/ui/archive_browser/static_replacement_dialog_callbacks_parts_outliner_mapping_part_02.py").read_text(encoding="utf-8")
    viewport = (root / "cdmw/ui/archive_browser/static_replacement_dialog_callbacks_source_tree_selection_part_01.py").read_text(encoding="utf-8")
    part_pick = (root / "cdmw/ui/mesh_editor/tab_state.py").read_text(encoding="utf-8")
    controls = (root / "cdmw/ui/archive_browser/static_replacement_dialog_callbacks_selected_part_control_part_01.py").read_text(encoding="utf-8")

    assert "_show_replacement_sources_context_menu_for_viewport" in outliner
    assert "_show_replacement_sources_context_menu_for_viewport(source_index, global_pos)" in viewport
    assert 'getattr(self.active_builder(), "_show_replacement_sources_context_menu_for_viewport", None)' in part_pick
    assert "resident source routing change awaits renderer/service confirmation" in outliner
    assert "resident source routing change awaits renderer/service confirmation" in mapping
    assert "if _state._resident_parts_session_active():\n            _state._clear_source_parts_apply_pending()" not in outliner
    assert "if _state._resident_parts_session_active():\n            _state._clear_source_parts_apply_pending()" not in mapping
    assert "control_state.has_source and not mesh_edit_active" in controls
    assert "Resident part reset is disabled until a native reset command is supported." in controls
