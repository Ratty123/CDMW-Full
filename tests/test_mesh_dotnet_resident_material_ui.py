from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    mesh_dotnet_material_input_signature,
)
from cdmw.ui.mesh_editor import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder, _FakeProcess


def test_mesh_editor_reactivation_syncs_changed_materials_without_restart_v2() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedDotNetResidentMaterialRefresh"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    mesh = builder.controller.working_mesh(clone=False)
    original_signature = mesh_dotnet_material_input_signature(mesh)
    process = _FakeProcess(tab)
    process._state = process.Running
    package = MeshDotNetExperimentPackage(
        package_dir=Path("package"),
        mesh_path=Path("package/mesh.obj"),
        obj_sidecar_path=Path("package/mesh.obj.meta.json"),
        cdmeta_path=Path("package/mesh.cdmeta.json"),
        original_asset_hash_path=Path("package/original_asset_hash.txt"),
        status_path=Path("package/dotnet_status.json"),
        output_dir=Path("package/output"),
        edit_operations_path=Path("package/output/edit_operations.json"),
        launch_manifest_path=Path("package/dotnet_launch.json"),
        material_signature=original_signature,
    )
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_editor_process = process
    tab.standalone_dotnet_experiment_package = package
    tab.standalone_dotnet_material_signature = original_signature
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
    mesh.submeshes[0].texture = "changed_material.dds"

    tab._start_dotnet_editor_requested(builder.controller, embedded=True)

    assert not process.terminated
    assert process is tab.standalone_dotnet_editor_process
    assert any(b'"event":"activate_request"' in write for write in process.stdin_writes)
    process.emit_stdout('{"event":"material_sync_required"}\n')
    material_writes = [
        json.loads(write.decode("utf-8"))
        for write in process.stdin_writes
        if b'"event":"material_state_update"' in write
    ]
    assert len(material_writes) == 1
    material_state = material_writes[0]
    assert material_state["schema"] == "cdmw_mesh_material_state_v2"
    assert material_state["session_id"] == builder.controller.session_view().session_id
    assert material_state["generation"] == 1
    assert tab.standalone_dotnet_lifecycle_counts["material_state_update_count"] == 1
    assert tab.standalone_dotnet_lifecycle_counts["full_reload_count"] == 0
    assert tab.standalone_dotnet_lifecycle_counts["process_restart_count"] == 0

    process.emit_stdout(json.dumps({
        "event": "material_state_applied",
        "generation": material_state["generation"],
        "material_signature": material_state["material_signature"],
    }) + "\n")
    process.emit_stdout('{"event":"activated"}\n')
    assert tab.standalone_dotnet_material_signature == material_state["material_signature"]
    assert tab.standalone_dotnet_lifecycle_counts["material_state_applied_count"] == 1
    assert tab.standalone_dotnet_embedded_state == "ready"
    assert not process.terminated
    app.processEvents()
    tab.deleteLater()


def test_generated_material_resource_commits_only_after_matching_renderer_ack(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorMaterialResourceAck"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
    source = tmp_path / "generated-base.dds"
    source.write_bytes(b"generated")
    binding = {
        "resource_id": "authority/base",
        "channel": "base",
        "source_dds_path": source,
        "affected_submeshes": [0],
    }
    completions: list[tuple[int, bool, tuple[dict[str, object], ...]]] = []
    setattr(
        builder,
        "_mesh_editor_embedded_material_resources_finished",
        lambda generation, committed, bindings: completions.append((generation, committed, bindings)),
    )
    hook = getattr(builder, "_mesh_editor_embedded_apply_material_resources")

    assert hook(builder.controller.working_mesh(clone=False), (binding,), affected_submeshes=(0,))
    payload = next(
        json.loads(raw.decode("utf-8"))
        for raw in process.stdin_writes
        if b'"event":"material_state_update"' in raw
    )
    session_id = builder.controller.session_view().session_id
    assert builder.controller.mesh_service.capture_export_snapshot(session_id).texture_resources == ()
    applied = {
        "event": "material_state_applied",
        "generation": payload["generation"],
        "material_signature": payload["material_signature"],
    }
    assert tab._handle_dotnet_protocol_event(applied)
    committed = builder.controller.mesh_service.capture_export_snapshot(session_id)
    assert committed.texture_revisions == (("authority/base", "base", 1),)
    assert committed.texture_resources[0].dds_data == b"generated"
    assert completions == [(payload["generation"], True, (binding,))]
    assert not tab._handle_dotnet_protocol_event(applied)

    assert hook(
        builder.controller.working_mesh(clone=False),
        ({"resource_id": "authority/base", "channel": "base", "remove": True},),
        affected_submeshes=(0,),
    )
    failed_payload = [
        json.loads(raw.decode("utf-8"))
        for raw in process.stdin_writes
        if b'"event":"material_state_update"' in raw
    ][-1]
    assert not tab._handle_dotnet_protocol_event({
        "event": "material_state_failed",
        "generation": failed_payload["generation"],
        "reason": "decode_failed",
    })
    assert builder.controller.mesh_service.capture_export_snapshot(session_id).texture_revisions == (
        ("authority/base", "base", 1),
    )
    assert completions[-1][0:2] == (failed_payload["generation"], False)
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()
