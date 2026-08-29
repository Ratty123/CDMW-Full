from __future__ import annotations

from pathlib import Path
import hashlib
import json
import threading

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh.authoring_capability import (
    AuthoringSupport,
    MeshOutputPolicy,
    action_authoring_capability,
    output_policy_state,
)
from cdmw.domain.mesh import MeshEditSelection
from cdmw.models import RunCancelled
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.action_bar import MeshEditorActionBar
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from cdmw.workers.mesh_free_edit_output_worker import MeshFreeEditOutputWorker
from cdmw.ui.mesh_editor.actions import (
    MESH_EDITOR_VISIBLE_ACTIONS,
    mesh_editor_action_authoring_blocker,
    mesh_editor_actions_by_key,
    visible_actions_for_session,
)
from tools.mesh_harness.fixtures import build_synthetic_mesh


def _keys(actions: object) -> set[str]:
    return {action.key for action in actions}  # type: ignore[union-attr]


def test_pac_lod0_defaults_to_exact_game_asset_actions() -> None:
    state = output_policy_state("pac", lod_index=0)

    assert state.policy is MeshOutputPolicy.EXACT_GAME_ASSET
    assert state.authoring_enabled
    assert state.exact_write_status is AuthoringSupport.EXACT
    assert _keys(
        visible_actions_for_session("pac", 0, state.policy)
    ) == _keys(MESH_EDITOR_VISIBLE_ACTIONS)
    assert "extrude" not in _keys(MESH_EDITOR_VISIBLE_ACTIONS)


def test_higher_lod_exact_session_is_explicitly_unproven() -> None:
    state = output_policy_state("pac", lod_index=2)

    assert state.policy is MeshOutputPolicy.EXACT_GAME_ASSET
    assert not state.authoring_enabled
    assert state.exact_write_status is AuthoringSupport.UNPROVEN
    assert "LOD1 and above" in state.reason


@pytest.mark.parametrize(
    ("mesh_format", "expected_support"),
    (("meshinfo", AuthoringSupport.READ_ONLY), ("unknown", AuthoringSupport.BLOCKED)),
)
def test_non_authorable_formats_are_read_only_with_a_reason(
    mesh_format: str,
    expected_support: AuthoringSupport,
) -> None:
    state = output_policy_state(mesh_format)

    assert state.policy is MeshOutputPolicy.READ_ONLY
    assert not state.authoring_enabled
    assert state.output_capability.support is expected_support
    assert state.reason
    assert _keys(visible_actions_for_session(mesh_format, 0, state.policy)) == {"select_parts"}
    assert mesh_editor_action_authoring_blocker(
        "toggle_visibility",
        mesh_format=mesh_format,
        output_policy=state.policy,
    ) == ""


def test_imported_working_mesh_enters_free_edit_but_waits_for_destination() -> None:
    state = output_policy_state("obj")

    assert state.policy is MeshOutputPolicy.FREE_EDIT
    assert not state.authoring_enabled
    assert "output folder" in state.reason
    visible = _keys(visible_actions_for_session("obj", 0, state.policy))
    assert {"extrude", "loop_cut", "copy", "paste", "layer_delete"} <= visible
    assert "output folder" in mesh_editor_action_authoring_blocker(
        "extrude",
        mesh_format="obj",
        output_policy=state.policy,
    )


def test_free_edit_exposes_only_native_advertised_proven_actions(tmp_path: Path) -> None:
    native = {"select_parts", "mode_edit", "extrude", "undo", "redo"}
    visible = _keys(
        visible_actions_for_session(
            "obj",
            0,
            MeshOutputPolicy.FREE_EDIT,
            native_capabilities=native,
            free_edit_destination_ready=True,
        )
    )

    assert "extrude" in visible
    assert "inset" not in visible
    assert action_authoring_capability(
        "extrude",
        mesh_format="obj",
        output_policy=MeshOutputPolicy.FREE_EDIT,
        free_edit_destination_ready=True,
        native_capabilities=native,
    ).support is AuthoringSupport.REBUILD


def test_exact_action_visibility_respects_advertised_writer_capabilities() -> None:
    visible = _keys(
        visible_actions_for_session(
            "pac",
            0,
            MeshOutputPolicy.EXACT_GAME_ASSET,
            writer_capabilities={"transform", "delete"},
        )
    )

    assert {"select_parts", "mode_edit", "transform_move", "delete"} <= visible
    assert "dissolve" not in visible


def test_switching_policy_changes_no_mesh_selection_history_or_revision(tmp_path: Path) -> None:
    mesh = build_synthetic_mesh()
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="policy-no-mutation", mode="edit")
    destination = tmp_path / "free-edit-output"
    baseline_mesh = service.working_mesh(view.session_id)

    switched = service.configure_output_policy(
        view.session_id,
        MeshOutputPolicy.FREE_EDIT,
        output_destination=destination,
    )

    assert switched.output_policy == MeshOutputPolicy.FREE_EDIT.value
    assert switched.output_destination == str(destination.resolve())
    assert switched.output_destination_ready
    assert switched.revision == view.revision
    assert switched.selection == view.selection
    assert switched.undo_count == view.undo_count
    assert switched.redo_count == view.redo_count
    assert service.working_mesh(view.session_id) == baseline_mesh


@pytest.mark.parametrize("destination_kind", ("missing", "existing", "source"))
def test_invalid_free_edit_destination_prevents_activation(
    tmp_path: Path,
    destination_kind: str,
) -> None:
    mesh = build_synthetic_mesh()
    source = tmp_path / "source.pac"
    source.write_bytes(b"source")
    mesh.path = str(source)
    service = MeshService()
    view = service.open_edit_session(mesh, session_id=f"policy-invalid-{destination_kind}")
    if destination_kind == "missing":
        destination = tmp_path / "missing-parent" / "output"
    elif destination_kind == "existing":
        destination = tmp_path / "existing"
        destination.mkdir()
    else:
        destination = source

    with pytest.raises(ValueError):
        service.configure_output_policy(
            view.session_id,
            MeshOutputPolicy.FREE_EDIT,
            output_destination=destination,
        )

    current = service.session_view(view.session_id)
    assert current.output_policy == MeshOutputPolicy.EXACT_GAME_ASSET.value
    assert current.revision == view.revision


def test_meshinfo_cannot_be_switched_to_free_edit(tmp_path: Path) -> None:
    mesh = build_synthetic_mesh()
    mesh.path = str(tmp_path / "table.meshinfo")
    mesh.format = "meshinfo"
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="meshinfo-read-only")

    with pytest.raises(ValueError):
        service.configure_output_policy(
            view.session_id,
            MeshOutputPolicy.FREE_EDIT,
            output_destination=tmp_path / "free-edit",
        )

    assert service.session_view(view.session_id).output_policy == MeshOutputPolicy.READ_ONLY.value


def test_free_edit_topology_preview_history_and_non_exact_output_are_end_to_end(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source-remains-unchanged")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    mesh = build_synthetic_mesh()
    mesh.path = str(source)
    controller = MeshEditorController()
    view = controller.open_mesh(mesh, session_id="free-edit-e2e", mode="edit")
    output_dir = tmp_path / "free-edit-output"
    controller.configure_output_policy(
        MeshOutputPolicy.FREE_EDIT,
        output_destination=output_dir,
    )
    selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

    edited = controller.apply_editor_action(
        "extrude",
        selection=selection,
        mode="edit",
        offset=(0.0, 0.0, 0.25),
    )
    preview = controller.native_update_for_result(edited)

    assert edited.ok
    assert edited.topology_changed
    assert preview.triangle_groups
    edited_view = controller.session_view()
    assert edited_view.undo_count == 1
    assert controller.undo().ok
    assert controller.session_view().redo_count == 1
    assert controller.redo().ok
    result = controller.mesh_service.export_free_edit_output(controller.active_session_id)

    assert result.output_dir == output_dir.resolve()
    assert result.obj_path.is_file()
    assert result.manifest_path.is_file()
    assert result.exact_archive_writeback is False
    assert source.read_bytes() == b"source-remains-unchanged"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["output_policy"] == MeshOutputPolicy.FREE_EDIT.value
    assert manifest["exact_archive_writeback"] is False
    assert manifest["validation"] == "obj_reparse_passed"
    assert manifest["face_count"] > view.face_count
    published_view = controller.session_view()
    assert published_view.output_policy == MeshOutputPolicy.FREE_EDIT.value
    assert not published_view.output_destination_ready
    assert not published_view.authoring_enabled


def test_cancelled_free_edit_output_publishes_nothing(tmp_path: Path) -> None:
    mesh = build_synthetic_mesh()
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="free-edit-cancel")
    output_dir = tmp_path / "cancelled-output"
    service.configure_output_policy(
        view.session_id,
        MeshOutputPolicy.FREE_EDIT,
        output_destination=output_dir,
    )
    stop_event = threading.Event()
    stop_event.set()

    with pytest.raises(RunCancelled):
        service.export_free_edit_output(view.session_id, stop_event=stop_event)

    assert not output_dir.exists()


def test_qt_action_surfaces_switch_visibility_without_reconstruction() -> None:
    app = QApplication.instance() or QApplication([])
    action_bar = MeshEditorActionBar()
    workspace = MeshEditorWorkspace()
    free_keys = _keys(
        visible_actions_for_session("obj", 0, MeshOutputPolicy.FREE_EDIT)
    )

    assert action_bar.button_for_key("extrude") is not None
    assert action_bar.button_for_key("extrude").isHidden()
    assert workspace.button_for_key("extrude") is not None
    assert workspace.button_for_key("extrude").isHidden()

    action_bar.set_action_visibility(free_keys)
    workspace.set_action_visibility(free_keys)

    assert not action_bar.button_for_key("extrude").isHidden()
    assert not workspace.button_for_key("extrude").isHidden()
    action_bar.deleteLater()
    workspace.deleteLater()
    app.processEvents()


def test_session_state_payload_carries_policy_actions_and_reasons(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=_settings("PolicyPayload"))
    mesh = build_synthetic_mesh()
    view = tab.open_mesh_session(mesh, session_id="policy-payload", mode="edit")
    payloads: list[dict[str, object]] = []
    tab._send_dotnet_protocol_message = lambda payload: payloads.append(dict(payload)) or True  # type: ignore[method-assign]

    assert tab._send_dotnet_session_state(session_view=view)
    exact = payloads[-1]
    assert exact["output_policy"] == MeshOutputPolicy.EXACT_GAME_ASSET.value
    assert exact["exact_output_required"] is True
    assert "extrude" not in exact["actions"]
    assert "extrude" in exact["unavailable_action_reasons"]

    destination = tmp_path / "payload-free-edit"
    free_view = tab.standalone_controller.configure_output_policy(  # type: ignore[union-attr]
        MeshOutputPolicy.FREE_EDIT,
        output_destination=destination,
    )
    assert tab._send_dotnet_session_state(session_view=free_view)
    free = payloads[-1]
    assert free["output_policy"] == MeshOutputPolicy.FREE_EDIT.value
    assert free["exact_output_required"] is False
    assert free["output_destination_ready"] is True
    assert "extrude" in free["actions"]
    tab.update_editor_action_state(publish_native=False)
    assert "Free Edit publishes" in tab.standalone_run_validation_report_button.toolTip()

    exact_view = tab.standalone_controller.configure_output_policy(  # type: ignore[union-attr]
        MeshOutputPolicy.EXACT_GAME_ASSET,
    )
    tab.update_editor_session_state(exact_view)
    assert "Free Edit publishes" not in tab.standalone_run_validation_report_button.toolTip()
    tab.deleteLater()
    app.processEvents()


def test_configure_free_edit_ui_requires_explicit_folder_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=_settings("PolicyChoose"))
    tab.open_mesh_session(build_synthetic_mesh(), session_id="policy-choose", mode="edit")
    monkeypatch.setattr(
        "cdmw.ui.mesh_editor.tab_output_policy.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    assert tab._configure_free_edit_output_requested()

    view = tab.standalone_controller.session_view()  # type: ignore[union-attr]
    assert view.output_policy == MeshOutputPolicy.FREE_EDIT.value
    assert view.output_destination_ready
    assert Path(view.output_destination).parent == tmp_path
    assert not Path(view.output_destination).exists()
    tab.deleteLater()
    app.processEvents()


def test_free_edit_worker_emits_terminal_completion(tmp_path: Path) -> None:
    mesh = build_synthetic_mesh()
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="free-edit-worker")
    service.configure_output_policy(
        view.session_id,
        MeshOutputPolicy.FREE_EDIT,
        output_destination=tmp_path / "worker-output",
    )
    worker = MeshFreeEditOutputWorker(17, service, view.session_id)
    completed: list[tuple[int, object]] = []
    errors: list[tuple[int, str]] = []
    worker.completed.connect(lambda request_id, result: completed.append((request_id, result)))
    worker.error.connect(lambda request_id, message: errors.append((request_id, message)))

    worker.run()

    assert errors == []
    assert len(completed) == 1
    assert completed[0][0] == 17
    assert completed[0][1].output_dir.is_dir()


def test_free_edit_worker_reports_completion_when_cancel_arrives_after_publish() -> None:
    published = object()

    class LateCancelService:
        @staticmethod
        def export_free_edit_output(
            _session_id: str,
            *,
            stop_event: threading.Event,
        ) -> object:
            stop_event.set()
            return published

    worker = MeshFreeEditOutputWorker(18, LateCancelService(), "late-cancel")
    completed: list[tuple[int, object]] = []
    cancelled: list[tuple[int, str]] = []
    worker.completed.connect(lambda request_id, result: completed.append((request_id, result)))
    worker.cancelled.connect(lambda request_id, message: cancelled.append((request_id, message)))

    worker.run()

    assert completed == [(18, published)]
    assert cancelled == []


@pytest.mark.parametrize(
    ("mesh_format", "policy", "destination_ready"),
    (
        ("pac", MeshOutputPolicy.EXACT_GAME_ASSET, False),
        ("obj", MeshOutputPolicy.FREE_EDIT, False),
        ("meshinfo", MeshOutputPolicy.READ_ONLY, False),
    ),
)
def test_application_action_gate_blocks_before_mutation_with_policy_reason(
    tmp_path: Path,
    mesh_format: str,
    policy: MeshOutputPolicy,
    destination_ready: bool,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=_settings(f"PolicyGate-{mesh_format}"))
    mesh = build_synthetic_mesh()
    mesh.format = mesh_format
    mesh.path = str(tmp_path / f"mesh.{mesh_format}")
    view = tab.open_mesh_session(mesh, session_id=f"policy-gate-{mesh_format}", mode="edit")

    blocker = tab._standalone_action_authoring_blocker("extrude")

    assert blocker
    assert tab.standalone_controller.session_view().revision == view.revision  # type: ignore[union-attr]
    assert destination_ready is False
    assert tab.standalone_controller.session_view().output_policy == policy.value  # type: ignore[union-attr]
    tab.deleteLater()
    app.processEvents()


def test_exact_validator_remains_authoritative_after_explicit_free_edit_switch(
    tmp_path: Path,
) -> None:
    controller = MeshEditorController()
    view = controller.open_mesh(build_synthetic_mesh(), session_id="validator-wins", mode="edit")
    controller.configure_output_policy(
        MeshOutputPolicy.FREE_EDIT,
        output_destination=tmp_path / "validator-free-edit",
    )
    edited = controller.apply_editor_action(
        mesh_editor_actions_by_key()["extrude"],
        selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
        mode="edit",
        offset=(0.0, 0.0, 0.25),
    )

    validation = controller.export_validation_report()

    assert edited.ok and edited.topology_changed
    assert not validation.ok
    assert validation.blockers
    assert controller.session_view().output_policy == MeshOutputPolicy.FREE_EDIT.value
    output = controller.mesh_service.export_free_edit_output(controller.active_session_id)
    assert output.exact_archive_writeback is False
    assert output.output_dir.is_dir()


def _settings(name: str):
    from PySide6.QtCore import QSettings

    settings = QSettings("CDMWTests", name)
    settings.clear()
    return settings


@pytest.mark.parametrize(
    "action_key",
    (
        "extrude",
        "inset",
        "loop_cut",
        "edge_split",
        "bridge",
        "merge",
        "weld",
        "fill",
        "copy",
        "paste",
        "layer_delete",
    ),
)
def test_each_new_free_edit_action_has_service_preview_history_and_output_proof(
    tmp_path: Path,
    action_key: str,
) -> None:
    mesh, selection, params = _free_edit_action_case(action_key)
    controller = MeshEditorController()
    view = controller.open_mesh(mesh, session_id=f"free-edit-proof-{action_key}", mode="edit")
    controller.configure_output_policy(
        MeshOutputPolicy.FREE_EDIT,
        output_destination=tmp_path / f"output-{action_key}",
    )
    if action_key in {"paste", "layer_delete"}:
        copied = controller.apply_editor_action(
            "copy",
            selection=selection,
            mode="edit",
            target_mode="face",
        )
        assert copied.ok
        pasted = controller.apply_editor_action("paste", mode="edit")
        assert pasted.ok
        if action_key == "layer_delete":
            layer_state = controller.geometry_layer_state()
            active_layer = str(layer_state["active_layer_id"])
            result = controller.delete_geometry_layer(active_layer)
        else:
            result = pasted
    else:
        if action_key == "copy":
            params = {**params, "target_mode": "face"}
        result = controller.apply_editor_action(
            action_key,
            selection=selection,
            mode="edit",
            **params,
        )

    assert result.ok
    preview = controller.native_update_for_result(result)
    if action_key == "copy":
        assert result.revision == view.revision
        assert controller.session_view().undo_count == 0
        assert not preview.vertex_groups
        assert not preview.triangle_groups
    else:
        assert result.revision > view.revision
        assert controller.session_view().undo_count >= 1
        assert preview.vertex_groups or preview.triangle_groups
        assert controller.undo().ok
        assert controller.redo().ok

    output = controller.mesh_service.export_free_edit_output(controller.active_session_id)
    manifest = json.loads(output.manifest_path.read_text(encoding="utf-8"))
    assert output.obj_path.is_file()
    assert manifest["output_policy"] == MeshOutputPolicy.FREE_EDIT.value
    assert manifest["exact_archive_writeback"] is False
    assert manifest["validation"] == "obj_reparse_passed"


def _free_edit_action_case(
    action_key: str,
) -> tuple[ParsedMesh, MeshEditSelection, dict[str, object]]:
    if action_key in {"bridge", "fill"}:
        mesh = _loose_quad_mesh()
        edges = (
            ((0, 1), (2, 3))
            if action_key == "bridge"
            else ((0, 1), (1, 3), (2, 3), (0, 2))
        )
        return mesh, MeshEditSelection.from_maps(edges_by_submesh={0: edges}), {}
    if action_key in {"merge", "weld"}:
        mesh = _duplicate_vertex_mesh()
        params = {"threshold": 0.001} if action_key == "weld" else {}
        return (
            mesh,
            MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)}),
            params,
        )
    mesh = build_synthetic_mesh()
    if action_key in {"loop_cut", "edge_split"}:
        return (
            mesh,
            MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)}),
            {},
        )
    params = {
        "extrude": {"offset": (0.0, 0.0, 0.25)},
        "inset": {"amount": 0.2},
    }.get(action_key, {})
    return mesh, MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), params


def _loose_quad_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="loose",
        material="mat",
        texture="",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[],
        vertex_count=4,
        face_count=0,
    )
    return ParsedMesh(
        path="loose.obj",
        format="obj",
        submeshes=[submesh],
        total_vertices=4,
        total_faces=0,
        has_uvs=True,
    )


def _duplicate_vertex_mesh() -> ParsedMesh:
    submesh = SubMesh(
        name="duplicate",
        material="mat",
        texture="",
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
        ],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 5,
        faces=[(0, 1, 2), (1, 3, 2), (0, 4, 2)],
        vertex_count=5,
        face_count=3,
    )
    return ParsedMesh(
        path="duplicate.obj",
        format="obj",
        submeshes=[submesh],
        total_vertices=5,
        total_faces=3,
        has_uvs=True,
    )
