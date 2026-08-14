from __future__ import annotations

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PIL import Image

from cdmw.models import PreviewMaterialTextureInput
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    mesh_dotnet_material_input_signature,
)
from cdmw.modding.static_mesh_scene_frame import static_scene_source_identity
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.mesh_editor.tab_dotnet_protocol import _dotnet_event_requires_correlation
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _install_shared_dotnet_test_process,
)


from tests.mesh_dotnet_resident_material_support import (
    _acknowledge_editable_materials,
    _material_writes,
    _wait_for_material_compile_idle,
)


def test_shared_package_lifecycle_is_correlated_by_the_resident_controller() -> None:
    assert not _dotnet_event_requires_correlation(
        "package_load_applied",
        {"request_id": 7, "generation": 3},
    )
    assert _dotnet_event_requires_correlation(
        "material_state_applied",
        {"session_id": "mesh-a", "request_id": 9, "process_generation": 2},
    )


def test_full_renderer_status_survives_compact_metrics() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorRendererStatus"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    controller = _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("renderer_status_request_v1", "resident_mutation_envelope_v2"),
    )
    session_id = builder.controller.session_view().session_id
    full_renderer = {
        "backend": "d3d11_vortice_shader",
        "gpu_backed": True,
        "renderer_blocked": False,
        "geometry_resources": {"live_texture_srvs": 7},
    }

    assert tab._handle_dotnet_protocol_event(
        {
            "event": "renderer_status",
            "request_id": 1,
            "session_id": session_id,
            "process_generation": 1,
            "renderer": full_renderer,
        }
    )
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "metrics",
            "metrics": {
                "renderer": {
                    "backend": "d3d11_vortice_shader",
                    "gpu_backed": True,
                    "renderer_blocked": False,
                    "geometry_resources": {"textured_solid_batch_draws": 11},
                }
            },
        }
    )

    assert tab.standalone_dotnet_status_payload["renderer"] == full_renderer
    assert tab.standalone_dotnet_status_payload["renderer_status_response"] == {
        "request_id": 1,
        "session_id": session_id,
        "process_generation": 1,
    }
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()






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
        scene_frame=SimpleNamespace(
            source_identity=static_scene_source_identity(mesh, None),
        ),
    )
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_experiment_package = package
    tab.standalone_dotnet_material_signature = original_signature
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2",),
    )
    mesh.submeshes[0].texture = "changed_material.dds"

    tab._start_dotnet_editor_requested(builder.controller, embedded=True)

    assert not process.terminated
    assert process is tab.standalone_dotnet_editor_process
    assert any(b'"event":"activate_request"' in write for write in process.stdin_writes)
    process.emit_stdout('{"event":"material_sync_required"}\n')
    material_writes = _material_writes(app, process)
    assert len(material_writes) == 1
    material_state = material_writes[0]
    assert material_state["schema"] == "cdmw_mesh_material_state_v3"
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


def test_mesh_editor_reactivation_uses_the_applied_resident_material_signature() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorResidentAppliedSignature"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    mesh = builder.controller.working_mesh(clone=False)
    input_signature = mesh_dotnet_material_input_signature(mesh)
    resident_signature = "resident-combined-material-state"
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
        material_signature=input_signature,
        scene_frame=SimpleNamespace(
            source_identity=static_scene_source_identity(mesh, None),
        ),
    )
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_experiment_package = package
    tab.standalone_dotnet_material_signature = resident_signature
    tab.standalone_dotnet_material_generation = 1
    tab.standalone_dotnet_completed_material_generation = 1
    tab.standalone_dotnet_applied_material_generation = 1
    tab.standalone_dotnet_material_input_signature_by_role["editable_imported"] = input_signature
    tab.standalone_dotnet_material_signature_by_role["editable_imported"] = resident_signature
    tab.standalone_dotnet_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_completed_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_applied_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_texture_resources_ready_by_role["editable_imported"] = True
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2",),
    )

    tab._start_dotnet_editor_requested(builder.controller, embedded=True)

    activation = next(
        json.loads(raw.decode("utf-8"))
        for raw in reversed(process.stdin_writes)
        if b'"event":"activate_request"' in raw
    )
    assert activation["material_signature"] == resident_signature
    assert activation["activation_request_id"] > 0
    assert activation["process_generation"] == 1
    assert activation["package_generation"] == 1
    assert not process.terminated
    app.processEvents()
    tab.deleteLater()


def test_helper_material_sync_request_forces_publish_past_local_dedup() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorForcedResidentMaterialSync"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    mesh = builder.controller.working_mesh(clone=False)
    input_signature = mesh_dotnet_material_input_signature(mesh)
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
        material_signature=input_signature,
        scene_frame=SimpleNamespace(source_identity=static_scene_source_identity(mesh, None)),
    )
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_experiment_package = package
    tab.standalone_dotnet_material_generation = 1
    tab.standalone_dotnet_completed_material_generation = 1
    tab.standalone_dotnet_applied_material_generation = 1
    tab.standalone_dotnet_material_input_signature_by_role["editable_imported"] = input_signature
    tab.standalone_dotnet_material_signature_by_role["editable_imported"] = input_signature
    tab.standalone_dotnet_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_completed_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_applied_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_texture_resources_ready_by_role["editable_imported"] = True
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2",),
    )

    before = len(_material_writes(app, process))
    process.emit_stdout('{"event":"material_sync_required"}\n')
    after = _material_writes(app, process)

    assert len(after) == before + 1
    assert after[-1]["generation"] == 2
    assert tab.standalone_dotnet_lifecycle_counts["material_state_deduplicated_count"] == 0
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_textured_view_waits_for_resident_material_ack_without_reload() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorTexturedViewResidentAck"))
    builder = _EmbeddedMeshBuilder()
    texture_requests: list[str] = []
    setattr(
        builder,
        "_mesh_editor_embedded_request_material_resources",
        lambda: texture_requests.append("requested"),
    )
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2", "viewport_display_modes_v1"),
    )
    setattr(builder, "_mesh_editor_embedded_dotnet_active", True)

    assert tab._handle_embedded_viewport_display_mode("textured")
    writes = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
    display_modes = [
        payload.get("mode")
        for payload in writes
        if payload.get("event") == "viewport_display_update"
    ]
    pending_updates = [
        payload
        for payload in writes
        if payload.get("event") == "viewport_display_update"
        and payload.get("mode") == "untextured_faces"
    ]
    assert texture_requests == ["requested"]
    assert display_modes[-1] == "untextured_faces"
    assert pending_updates[-1]["texture_request_pending"] is True
    assert "textured" not in display_modes
    assert tab.standalone_dotnet_pending_textured_view is True

    _acknowledge_editable_materials(tab, process)
    writes = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
    display_modes = [
        payload.get("mode")
        for payload in writes
        if payload.get("event") == "viewport_display_update"
    ]
    assert display_modes[-1] == "textured"
    assert tab.standalone_dotnet_lifecycle_counts["full_reload_count"] == 0
    assert tab.standalone_dotnet_lifecycle_counts["process_restart_count"] == 0
    assert not process.terminated
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_textured_view_toggle_reuses_ready_reference_resources() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorTexturedViewReuse"))
    builder = _EmbeddedMeshBuilder()
    texture_requests: list[str] = []
    setattr(
        builder,
        "_mesh_editor_embedded_request_material_resources",
        lambda: texture_requests.append("requested"),
    )
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2", "viewport_display_modes_v1"),
    )
    tab.standalone_dotnet_experiment_package = SimpleNamespace(reference_submesh_count=1)
    setattr(builder, "_mesh_editor_embedded_dotnet_active", True)
    for role in ("editable_imported", "original_reference"):
        tab.standalone_dotnet_material_generation_by_role[role] = 4
        tab.standalone_dotnet_completed_material_generation_by_role[role] = 4
        tab.standalone_dotnet_applied_material_generation_by_role[role] = 4
        tab.standalone_dotnet_texture_resources_ready_by_role[role] = True

    assert tab._handle_embedded_viewport_display_mode("untextured_faces")
    assert tab._handle_embedded_viewport_display_mode("textured")

    display_modes = [
        payload.get("mode")
        for payload in (
            json.loads(raw.decode("utf-8")) for raw in process.stdin_writes
        )
        if payload.get("event") == "viewport_display_update"
    ]
    assert display_modes[-2:] == ["untextured_faces", "textured"]
    assert texture_requests == []
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_builder_textured_selector_resolves_materials_before_presentation_update() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorBuilderTexturedRequest"))
    builder = _EmbeddedMeshBuilder()
    texture_requests: list[str] = []
    setattr(
        builder,
        "_mesh_editor_embedded_request_material_resources",
        lambda: texture_requests.append("requested"),
    )
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=(
            "resident_material_updates_v2",
            "resident_presentation_state_v1",
            "viewport_display_modes_v1",
        ),
    )
    setattr(builder, "_mesh_editor_embedded_dotnet_active", True)

    request_display = getattr(
        builder,
        "_mesh_editor_embedded_request_viewport_display",
        None,
    )
    assert callable(request_display)
    assert request_display("textured")

    writes = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
    viewport_updates = [
        payload
        for payload in writes
        if payload.get("event") == "viewport_display_update"
    ]
    assert texture_requests == ["requested"]
    assert viewport_updates[-1]["mode"] == "untextured_faces"
    assert viewport_updates[-1]["texture_request_pending"] is True
    assert viewport_updates[-1]["requested_mode"] == "textured"
    assert tab.standalone_dotnet_presentation_desired["display"]["mode"] == "untextured_faces"
    assert tab.standalone_dotnet_pending_textured_view is True
    assert tab.standalone_dotnet_pending_textured_view_uses_presentation is True

    _acknowledge_editable_materials(tab, process)
    assert tab.standalone_dotnet_presentation_desired["display"]["mode"] == "textured"
    writes = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
    presentation_updates = [
        payload
        for payload in writes
        if payload.get("event") == "presentation_state_update"
    ]
    assert presentation_updates[-1]["display"]["mode"] == "textured"
    assert tab.standalone_dotnet_lifecycle_counts["full_reload_count"] == 0
    assert tab.standalone_dotnet_lifecycle_counts["process_restart_count"] == 0
    assert not process.terminated
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_native_textured_selector_routes_through_resident_material_request() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorNativeTexturedRequest"))
    builder = _EmbeddedMeshBuilder()
    texture_requests: list[str] = []
    setattr(
        builder,
        "_mesh_editor_embedded_request_material_resources",
        lambda: texture_requests.append("requested"),
    )
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        generation=3,
        capabilities=("resident_material_updates_v2", "viewport_display_modes_v1"),
    )
    setattr(builder, "_mesh_editor_embedded_dotnet_active", True)
    session_id = builder.controller.session_view().session_id
    tab.standalone_dotnet_lifecycle_session_id = session_id

    assert tab._handle_dotnet_protocol_event(
        {
            "event": "viewport_display_request",
            "session_id": session_id,
            "request_id": 41,
            "process_generation": 3,
            "mode": "textured",
        }
    )

    writes = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
    pending = [
        payload
        for payload in writes
        if payload.get("event") == "viewport_display_update"
    ][-1]
    assert texture_requests == ["requested"]
    assert {
        key: pending[key]
        for key in (
            "event",
            "session_id",
            "request_id",
            "process_generation",
            "mode",
            "texture_request_pending",
        )
    } == {
        "event": "viewport_display_update",
        "session_id": session_id,
        "request_id": 1,
        "process_generation": 3,
        "mode": "untextured_faces",
        "texture_request_pending": True,
    }
    assert tab.standalone_dotnet_pending_textured_view is True
    assert tab.standalone_dotnet_lifecycle_counts["process_restart_count"] == 0
    assert not process.terminated
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_generated_material_resource_commits_only_after_matching_renderer_ack(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorMaterialResourceAck"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2",),
    )
    recorded_events: list[tuple[str, dict[str, object]]] = []
    tab._record_mesh_dotnet_event = (
        lambda event, **fields: recorded_events.append((event, dict(fields)))
    )
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
    writes = _material_writes(app, process)
    assert writes, " | ".join(
        f"{event}: {fields}" for event, fields in recorded_events
    )
    payload = writes[0]
    update_event = next(
        fields
        for event, fields in recorded_events
        if event == "mesh_dotnet_material_state_update"
    )
    assert update_event["resource_count"] == 1
    assert update_event["resource_file_count"] == 1
    assert update_event["missing_resource_count"] == 0
    assert update_event["resource_bytes"] > 0
    assert Path(update_event["compiler_cache_dir"]).is_dir()
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
    failed_payload = _material_writes(app, process, minimum=2)[-1]
    assert not tab._handle_dotnet_protocol_event({
        "event": "material_state_failed",
        "generation": failed_payload["generation"],
        "reason": "texture_decode_failed",
        "message": "authority/base: texture_file_missing",
    })
    assert builder.controller.mesh_service.capture_export_snapshot(session_id).texture_revisions == (
        ("authority/base", "base", 1),
    )
    assert completions[-1][0:2] == (failed_payload["generation"], False)
    failure_event = next(
        fields
        for event, fields in recorded_events
        if event == "mesh_dotnet_material_state_failed"
    )
    assert failure_event["failure_reason"] == "texture_decode_failed"
    assert failure_event["failure_message"] == "authority/base: texture_file_missing"
    assert failure_event["generation"] == failed_payload["generation"]
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()
