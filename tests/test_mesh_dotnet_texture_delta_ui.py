from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.models import TextureEditorSourceBinding
from cdmw.modding.mesh_exporter import export_obj
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.texture_workflow.editor_resident_texture import build_texture_editor_resident_patch
from tests.test_mesh_editor_action_bar import _FakeProcess, _install_shared_dotnet_test_process
from tools.mesh_harness.fixtures import build_synthetic_mesh


def _wait_for(app: QApplication, predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def test_texture_editor_dds_updates_resident_dotnet_resource_without_legacy_package(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "source.dds"
    preview_path = tmp_path / "preview.dds"
    source_path.write_bytes(b"dds source")
    preview_path.write_bytes(b"dds preview")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source_path)
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshDotNetTextureDelta"))
    try:
        tab.open_mesh_session(mesh, session_id="texture-delta", mode="edit")
        process = _FakeProcess(tab)
        process._state = process.Running
        tab._connect_dotnet_protocol(process)
        _install_shared_dotnet_test_process(
            tab,
            process,
            capabilities=("resident_material_updates_v2",),
        )
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            source_identity_path=f"texture-delta:0:{source_path}",
            texture_type="mesh_material",
        )

        with patch.object(tab, "start_standalone_native_preview_async") as legacy_preview:
            assert tab.apply_texture_editor_dds_preview(str(preview_path), binding)

        legacy_preview.assert_not_called()
        assert _wait_for(
            app,
            lambda: any(b'"event":"material_state_update"' in raw for raw in process.stdin_writes),
        )
        payload = next(
            json.loads(raw.decode("utf-8"))
            for raw in process.stdin_writes
            if b'"event":"material_state_update"' in raw
        )
        assert payload["affected_submeshes"] == [0]
        assert payload["reason"] == "texture_editor_preview"
        resources = {item["resource_id"]: item for item in payload["resources"]}
        base_resource = payload["submeshes"][0]["channels"]["base"]
        assert Path(resources[base_resource]["path"]).is_file()
        assert Path(resources[base_resource]["source_reference"]) == preview_path.resolve()
    finally:
        tab.deleteLater()
        app.processEvents()


def test_texture_editor_export_assigns_undoable_resident_texture_and_obj_export(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "source.dds"
    assigned_path = tmp_path / "assigned.dds"
    preview_path = tmp_path / "preview.dds"
    source_path.write_bytes(b"dds source")
    assigned_path.write_bytes(b"dds assigned")
    preview_path.write_bytes(b"dds preview")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source_path)
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshDotNetTextureAssignment"))
    try:
        tab.open_mesh_session(mesh, session_id="texture-assignment", mode="edit")
        process = _FakeProcess(tab)
        process._state = process.Running
        tab._connect_dotnet_protocol(process)
        _install_shared_dotnet_test_process(
            tab,
            process,
            capabilities=("resident_material_updates_v2",),
        )
        tab.standalone_texture_preview_overrides[0] = str(preview_path)
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            source_identity_path=f"texture-assignment:0:{source_path}",
            texture_type="mesh_material",
            mesh_session_id="texture-assignment",
            mesh_resource_id=str(source_path),
            mesh_submesh_indices=(0,),
            mesh_channel="base",
            mesh_commit_mode="assign",
        )

        with patch.object(tab, "start_standalone_native_preview_async") as legacy_preview:
            assert tab.apply_texture_editor_dds_result(str(assigned_path), binding)

        legacy_preview.assert_not_called()
        assert tab.standalone_texture_preview_overrides == {}
        assert tab.standalone_controller is not None
        controller = tab.standalone_controller
        assert controller.working_mesh().submeshes[0].texture == str(assigned_path.resolve())
        assert controller.session_view().revision == 1
        assert _wait_for(
            app,
            lambda: any(b'"event":"material_state_update"' in raw for raw in process.stdin_writes),
        )
        payload = next(
            json.loads(raw.decode("utf-8"))
            for raw in process.stdin_writes
            if b'"event":"material_state_update"' in raw
        )
        assert payload["reason"] == "texture_editor_assign"
        assert payload["edit_revision"] == 1
        protocol_payloads = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
        session_index = next(
            index
            for index, item in enumerate(protocol_payloads)
            if item.get("event") == "session_state" and item.get("revision") == 1
        )
        material_index = next(
            index
            for index, item in enumerate(protocol_payloads)
            if item.get("event") == "material_state_update" and item.get("reason") == "texture_editor_assign"
        )
        assert session_index < material_index
        resources = {item["resource_id"]: item for item in payload["resources"]}
        base_resource = payload["submeshes"][0]["channels"]["base"]
        assert Path(resources[base_resource]["path"]).is_file()
        assert Path(resources[base_resource]["source_reference"]) == assigned_path.resolve()
        assigned_snapshot = controller.mesh_service.capture_export_snapshot(controller.active_session_id)
        assert assigned_snapshot.texture_revisions == ((base_resource, "base", 1),)
        assert assigned_snapshot.texture_resources[0].dds_data == b"dds assigned"

        export_dir = tmp_path / "export"
        export_obj(controller.working_mesh(clone=True), str(export_dir), "assigned")
        assert f"map_Kd {str(assigned_path.resolve()).replace(chr(92), '/')}" in (
            export_dir / "assigned.mtl"
        ).read_text(encoding="utf-8")

        assert controller.undo().ok
        assert controller.working_mesh().submeshes[0].texture == str(source_path)
        assert controller.mesh_service.capture_export_snapshot(controller.active_session_id).texture_resources == ()
        assert controller.redo().ok
        assert controller.working_mesh().submeshes[0].texture == str(assigned_path.resolve())
        assert controller.mesh_service.capture_export_snapshot(controller.active_session_id).texture_resources[0].dds_data == b"dds assigned"
    finally:
        tab.deleteLater()
        app.processEvents()


def test_texture_editor_assignment_uses_embedded_dotnet_target_controller(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "source.dds"
    assigned_path = tmp_path / "assigned.dds"
    source_path.write_bytes(b"dds source")
    assigned_path.write_bytes(b"dds assigned")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source_path)
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshDotNetEmbeddedTextureAssignment"))
    controller = None
    try:
        tab.open_mesh_session(mesh, session_id="embedded-texture-assignment", mode="edit")
        controller = tab.standalone_controller
        assert controller is not None
        tab.standalone_dotnet_target_controller = controller
        tab.standalone_controller = None
        process = _FakeProcess(tab)
        process._state = process.Running
        tab._connect_dotnet_protocol(process)
        _install_shared_dotnet_test_process(
            tab,
            process,
            capabilities=("resident_material_updates_v2",),
        )
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            texture_type="mesh_material",
            mesh_session_id="embedded-texture-assignment",
            mesh_submesh_indices=(0,),
            mesh_channel="base",
            mesh_commit_mode="assign",
        )

        assert tab.apply_texture_editor_dds_result(str(assigned_path), binding)
        assert controller.working_mesh().submeshes[0].texture == str(assigned_path.resolve())
        assert _wait_for(
            app,
            lambda: any(b'"reason":"texture_editor_assign"' in raw for raw in process.stdin_writes),
        )
        assert any(b'"reason":"texture_editor_assign"' in raw for raw in process.stdin_writes)
    finally:
        if controller is not None:
            controller.close_active_session()
        tab.deleteLater()
        app.processEvents()


def test_texture_editor_patch_uses_material_resource_and_cleans_payload_after_ack(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "source.dds"
    source_path.write_bytes(b"dds source")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source_path)
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshDotNetTextureRegion"))
    try:
        tab.open_mesh_session(mesh, session_id="texture-region", mode="edit")
        process = _FakeProcess(tab)
        process._state = process.Running
        tab._connect_dotnet_protocol(process)
        _install_shared_dotnet_test_process(
            tab,
            process,
            capabilities=("resident_texture_region_updates_v1",),
        )
        tab.standalone_texture_region_queue._output_root = tmp_path / "patches"
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            source_identity_path=f"texture-region:0:{source_path}",
            source_path=str(source_path),
            texture_type="mesh_material",
            mesh_session_id="texture-region",
            mesh_resource_id="not-authoritative",
            mesh_submesh_indices=(0,),
            mesh_channel="base",
        )
        original = np.zeros((4, 4, 4), dtype=np.uint8)
        original[..., 3] = 255
        edited = original.copy()
        edited[1:3, 1:3] = [10, 20, 30, 255]
        patch = build_texture_editor_resident_patch(
            binding,
            edited,
            texture_revision=3,
            dirty_bounds=(1, 1, 2, 2),
        )

        assert tab.apply_texture_editor_region_patch(patch)
        assert _wait_for(
            app,
            lambda: any(b'"event":"texture_region_update"' in raw for raw in process.stdin_writes),
        )
        payload = next(
            json.loads(raw.decode("utf-8"))
            for raw in process.stdin_writes
            if b'"event":"texture_region_update"' in raw
        )
        assert payload["resource_id"].startswith("texture:")
        assert payload["resource_id"] != binding.mesh_resource_id
        assert payload["affected_submeshes"] == [0]
        assert payload["rect"] == {"x": 0, "y": 0, "width": 4, "height": 4}
        assert payload["pixel_format"] == "bgra8_unorm"
        binary_path = Path(payload["binary"]["path"])
        assert binary_path.is_file()

        process.emit_stdout(
            json.dumps(
                {
                    "event": "texture_region_applied",
                    "session_id": "texture-region",
                    "resource_id": payload["resource_id"],
                    "generation": payload["generation"],
                    "texture_revision": payload["texture_revision"],
                    "edit_revision": payload["edit_revision"],
                }
            )
            + "\n"
        )
        assert _wait_for(app, tab._dotnet_texture_updates_idle)
        assert not binary_path.exists()
        assert tab.standalone_dotnet_lifecycle_counts["texture_region_applied_count"] == 1
        assert any(
            event.get("event") == "texture_region_applied"
            and event.get("resource_id") == payload["resource_id"]
            for event in tab.standalone_dotnet_protocol_events
        )
    finally:
        tab.request_shutdown()
        tab.deleteLater()
        app.processEvents()


def test_rejected_texture_patch_releases_composite_lease(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "source.dds"
    source_path.write_bytes(b"dds source")
    mesh = build_synthetic_mesh()
    mesh.submeshes[0].texture = str(source_path)
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshTextureRegionRejectedLease"))
    try:
        tab.open_mesh_session(mesh, session_id="texture-rejected", mode="edit")
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            source_identity_path=f"texture-rejected:0:{source_path}",
            texture_type="mesh_material",
            mesh_session_id="texture-rejected",
            mesh_submesh_indices=(0,),
            mesh_channel="base",
        )
        rgba = np.zeros((2, 2, 4), dtype=np.uint8)
        patch = build_texture_editor_resident_patch(
            binding,
            rgba,
            texture_revision=1,
            dirty_bounds=(0, 0, 1, 1),
        )
        assert not rgba.flags.writeable

        assert not tab.apply_texture_editor_region_patch(patch)

        assert patch.composite_lease.released
        assert rgba.flags.writeable
    finally:
        tab.request_shutdown()
        tab.deleteLater()
        app.processEvents()
