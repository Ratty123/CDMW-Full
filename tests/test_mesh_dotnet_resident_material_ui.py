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


def _material_writes(
    app: QApplication,
    process: _FakeProcess,
    *,
    minimum: int = 1,
    timeout: float = 3.0,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    writes: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        app.processEvents()
        writes = [
            json.loads(raw.decode("utf-8"))
            for raw in process.stdin_writes
            if b'"event":"material_state_update"' in raw
        ]
        if len(writes) >= minimum:
            break
        time.sleep(0.005)
    return writes


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


def _wait_for_material_compile_idle(
    app: QApplication,
    tab: MeshEditorTab,
    *,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while tab._dotnet_material_compile_active() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def _acknowledge_editable_materials(tab: MeshEditorTab, process: _FakeProcess) -> None:
    tab.standalone_dotnet_material_generation = 1
    tab.standalone_dotnet_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_material_role_by_generation[1] = "editable_imported"
    process.emit_stdout(
        json.dumps(
            {
                "event": "material_state_applied",
                "generation": 1,
                "role": "replacement",
                "material_signature": "editable-materials",
                "texture_resources_ready": True,
            }
        )
        + "\n"
    )


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


def test_late_exact_clone_materials_compile_once_for_editable_and_reference_resources(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorLateExactCloneMaterials"))
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
    editable_mesh = builder.controller.working_mesh(clone=False)
    texture_path = tmp_path / "resolved-body.dds"
    texture_path.write_bytes(b"resolved-body")
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(
                source_submesh_index=index,
                material_name=f"resolved-{index}",
                preview_texture_path=str(texture_path),
                preview_texture_dds_path=str(texture_path),
                preview_texture_flip_vertical=False,
                preview_material_texture_inputs=(),
            )
            for index, _submesh in enumerate(editable_mesh.submeshes)
        ]
    )

    paired_hook = getattr(
        builder,
        "_mesh_editor_embedded_apply_clone_and_reference_material_resources",
    )
    assert paired_hook(preview_model)
    assert tab.standalone_dotnet_pending_reference_material_model is None
    assert all(submesh.preview_texture_path == str(texture_path) for submesh in editable_mesh.submeshes)

    material_writes = _material_writes(app, process)
    assert len(material_writes) == 1
    assert material_writes[0]["reason"] == "late_exact_clone_and_reference_resources"
    assert material_writes[0]["roles"] == ["replacement", "original_reference"]
    assert len(material_writes[0]["submeshes"]) == len(editable_mesh.submeshes) * 2
    assert all(resource["role"] == "replacement" for resource in material_writes[0]["resources"])

    editable_input_signature = material_writes[0]["material_signature"]
    resident_combined_signature = "resident-editable-material-state"
    assert tab._handle_dotnet_protocol_event({
        "event": "material_state_applied",
        "generation": material_writes[0]["generation"],
        "material_signature": resident_combined_signature,
        "texture_resources_ready": True,
    })
    assert (
        tab.standalone_dotnet_material_input_signature_by_role["editable_imported"]
        == editable_input_signature
    )
    assert (
        tab.standalone_dotnet_material_signature_by_role["editable_imported"]
        == resident_combined_signature
    )
    assert (
        tab.standalone_dotnet_material_signature_by_role["original_reference"]
        == resident_combined_signature
    )
    assert tab._dotnet_material_roles_ready()
    app.processEvents()
    assert len(_material_writes(app, process)) == 1

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_late_paired_materials_wait_for_the_desired_resident_package(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPairedMaterialsWaitForPackage"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    controller = _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2",),
    )
    pending_package = SimpleNamespace(package_dir=tmp_path / "desired-package")
    controller._desired_package = pending_package
    controller._desired_package_identity = ("desired",)
    controller._applied_package = None
    controller._applied_package_path = ""
    controller._applied_package_generation = 0
    texture_path = tmp_path / "resolved-body.dds"
    texture_path.write_bytes(b"resolved-body")
    editable_mesh = builder.controller.working_mesh(clone=False)
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(
                source_submesh_index=index,
                material_name=f"resolved-{index}",
                preview_texture_path=str(texture_path),
                preview_texture_dds_path=str(texture_path),
                preview_texture_flip_vertical=False,
                preview_material_texture_inputs=(),
            )
            for index, _submesh in enumerate(editable_mesh.submeshes)
        ]
    )

    assert tab.apply_resident_clone_and_reference_material_resources(preview_model)
    app.processEvents()

    assert _material_writes(app, process) == []
    assert tab.standalone_dotnet_pending_paired_material_model is preview_model

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_late_exact_clone_materials_publish_direct_textures_before_graph_upgrade(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(
        settings=QSettings("CDMWTests", "MeshEditorDirectTexturesBeforeGraphUpgrade")
    )
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    controller = _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2",),
    )
    editable_mesh = builder.controller.working_mesh(clone=False)
    base_path = tmp_path / "resolved-body.png"
    detail_path = tmp_path / "resolved-body-detail.png"
    material_path = tmp_path / "resolved-body-mask.png"
    normal_path = tmp_path / "resolved-body-normal.png"
    Image.new("RGBA", (8, 8), (92, 64, 48, 255)).save(base_path)
    Image.new("RGBA", (8, 8), (190, 132, 72, 255)).save(detail_path)
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(material_path)
    Image.new("RGBA", (8, 8), (128, 128, 255, 255)).save(normal_path)
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(
                source_submesh_index=index,
                material_name=f"resolved-{index}",
                preview_texture_path=str(base_path),
                preview_texture_dds_path=str(base_path),
                preview_normal_texture_path=str(normal_path),
                preview_normal_texture_dds_path=str(normal_path),
                preview_material_texture_path=str(material_path),
                preview_material_texture_dds_path=str(material_path),
                preview_texture_flip_vertical=False,
                preview_sidecar_shader_family="MultiTextured",
                preview_material_texture_inputs=(
                    PreviewMaterialTextureInput(
                        slot_kind="base",
                        parameter_name="_overlayColorTexture",
                        semantic_type="base",
                        source_dds_path=str(base_path),
                        preview_texture_path=str(base_path),
                        shader_family="MultiTextured",
                        sidecar_kind="pac_xml",
                        owner_slot_index=index,
                        binding_authority="authoritative",
                        binding_disposition="promoted",
                        source_kind="crimson_overlay_color",
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_colorTextureG",
                        semantic_type="color",
                        layer_channel="g",
                        source_dds_path=str(detail_path),
                        preview_texture_path=str(detail_path),
                        shader_family="MultiTextured",
                        sidecar_kind="pac_xml",
                        owner_slot_index=index,
                        binding_authority="authoritative",
                        binding_disposition="layer_only",
                        source_kind="crimson_layer_color",
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="material",
                        parameter_name="_rgbTexture",
                        semantic_type="mask",
                        layer_role="mask",
                        layer_channel="r",
                        source_dds_path=str(material_path),
                        preview_texture_path=str(material_path),
                        shader_family="MultiTextured",
                        sidecar_kind="pac_xml",
                        owner_slot_index=index,
                        binding_authority="authoritative",
                        binding_disposition="layer_only",
                        source_kind="crimson_detail_mask",
                    ),
                    PreviewMaterialTextureInput(
                        slot_kind="normal",
                        parameter_name="normalTexture",
                        semantic_type="normal",
                        semantic_subtype="normal",
                        source_dds_path=str(normal_path),
                        preview_texture_path=str(normal_path),
                        confidence="gltf",
                        visualized=True,
                    ),
                ),
            )
            for index, _submesh in enumerate(editable_mesh.submeshes)
        ]
    )

    assert tab.apply_resident_clone_and_reference_material_resources(preview_model)
    first = _material_writes(app, process)[0]
    assert first["reason"] == "late_exact_clone_and_reference_direct_resources"
    assert first["roles"] == ["replacement", "original_reference"]
    assert any(resource["semantic"] == "base" for resource in first["resources"])
    pending_upgrade = tab.standalone_dotnet_pending_paired_material_upgrade
    assert isinstance(pending_upgrade, tuple)
    assert pending_upgrade[:2] == (
        first["generation"],
        (
            tab.standalone_dotnet_process_generation,
            tab._dotnet_material_package_generation(),
        ),
    )
    assert len(_material_writes(app, process)) == 1

    tab.standalone_dotnet_pending_textured_view = True
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "material_state_applied",
            "generation": first["generation"],
            "material_signature": first["material_signature"],
            "texture_resources_ready": True,
        }
    )
    assert not tab.standalone_dotnet_pending_textured_view

    writes = _material_writes(app, process, minimum=2)
    assert len(writes) == 2
    upgrade = writes[1]
    assert upgrade["reason"] == "late_exact_clone_and_reference_material_upgrade"
    assert upgrade["material_signature"] != first["material_signature"]
    assert tab.standalone_dotnet_pending_paired_material_upgrade is None
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "material_state_applied",
            "generation": upgrade["generation"],
            "material_signature": upgrade["material_signature"],
            "texture_resources_ready": True,
        }
    )
    _wait_for_material_compile_idle(app, tab)
    assert len(_material_writes(app, process)) == 2

    # A newer material request must supersede a direct-texture generation and
    # prevent its deferred full graph from being published after the newer ack.
    assert tab.apply_resident_clone_and_reference_material_resources(preview_model)
    superseded_direct = _material_writes(app, process, minimum=3)[-1]
    pending_upgrade = tab.standalone_dotnet_pending_paired_material_upgrade
    assert isinstance(pending_upgrade, tuple)
    assert pending_upgrade[0] == superseded_direct["generation"]
    assert tab._send_dotnet_material_state(
        reason="newer_user_material_request",
        mesh_snapshot=editable_mesh,
        mirror_reference_submesh_offset=len(editable_mesh.submeshes),
    )
    assert tab.standalone_dotnet_pending_paired_material_upgrade is None
    newer = _material_writes(app, process, minimum=4)[-1]
    assert newer["generation"] > superseded_direct["generation"]
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "material_state_applied",
            "generation": newer["generation"],
            "material_signature": newer["material_signature"],
            "texture_resources_ready": True,
        }
    )
    _wait_for_material_compile_idle(app, tab)
    app.processEvents()
    assert len(_material_writes(app, process)) == 4

    assert tab.apply_resident_clone_and_reference_material_resources(preview_model)
    package_superseded_direct = _material_writes(app, process, minimum=5)[-1]
    pending_upgrade = tab.standalone_dotnet_pending_paired_material_upgrade
    assert isinstance(pending_upgrade, tuple)
    assert pending_upgrade[0] == package_superseded_direct["generation"]
    controller._applied_package_generation = 2
    tab._flush_pending_dotnet_reference_material_resources()
    assert tab.standalone_dotnet_pending_paired_material_upgrade is None
    app.processEvents()
    assert len(_material_writes(app, process)) == 5

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_late_unindexed_clone_materials_survive_original_only_supplemental_parts(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorLateUnindexedCloneMaterials"))
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
    editable_mesh = builder.controller.working_mesh(clone=False)
    texture_path = tmp_path / "resolved-unindexed.dds"
    texture_path.write_bytes(b"resolved-unindexed")
    preview_model = SimpleNamespace(
        path="archive/original-with-supplements.pac",
        meshes=[
            SimpleNamespace(
                source_submesh_index=-1,
                material_name=submesh.material,
                preview_texture_path=str(texture_path),
                preview_texture_dds_path=str(texture_path),
                preview_texture_flip_vertical=False,
                preview_material_texture_inputs=(),
            )
            for submesh in editable_mesh.submeshes
        ]
        + [
            SimpleNamespace(source_submesh_index=-1, material_name="supplemental-a"),
            SimpleNamespace(source_submesh_index=-1, material_name="supplemental-b"),
        ],
    )

    clone_hook = getattr(builder, "_mesh_editor_embedded_apply_clone_material_resources")
    assert clone_hook(preview_model)
    assert all(
        submesh.preview_texture_dds_path == str(texture_path)
        for submesh in editable_mesh.submeshes
    )
    material_writes = _material_writes(app, process)
    assert len(material_writes) == 1
    assert material_writes[0]["reason"] == "late_exact_clone_resources"
    assert len(material_writes[0]["submeshes"]) == len(editable_mesh.submeshes)

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_pre_ready_clone_materials_replay_and_stale_pending_models_clear(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPreReadyCloneMaterials"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_embedded_state = "launching"
    texture_path = tmp_path / "pre-ready.dds"
    texture_path.write_bytes(b"pre-ready")
    editable_mesh = builder.controller.working_mesh(clone=False)
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(
                source_submesh_index=index,
                material_name=f"pre-ready-{index}",
                preview_texture_path=str(texture_path),
                preview_texture_dds_path=str(texture_path),
                preview_material_texture_inputs=(),
            )
            for index, _submesh in enumerate(editable_mesh.submeshes)
        ]
    )

    assert tab.apply_resident_clone_and_reference_material_resources(preview_model)
    assert tab.standalone_dotnet_pending_paired_material_model is preview_model

    process = _FakeProcess(tab)
    process._state = process.Running
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(tab, process)
    assert tab.standalone_dotnet_pending_paired_material_model is preview_model
    assert not process.stdin_writes

    tab._observe_dotnet_capabilities({"capabilities": ["resident_material_updates_v2"]})
    app.processEvents()
    material_writes = _material_writes(app, process)
    assert len(material_writes) == 1
    assert material_writes[0]["reason"] == "late_exact_clone_and_reference_resources"
    assert tab.standalone_dotnet_pending_paired_material_model is None

    tab.standalone_dotnet_pending_paired_material_upgrade = preview_model
    tab._stop_standalone_dotnet_editor_process()
    assert tab.standalone_dotnet_pending_clone_material_model is None
    assert tab.standalone_dotnet_pending_reference_material_model is None
    assert tab.standalone_dotnet_pending_paired_material_model is None
    assert tab.standalone_dotnet_pending_paired_material_upgrade is None

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_package_swap_fails_sent_material_resources_and_rejects_their_late_ack(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorMaterialPackageSwap"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    controller = _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2",),
    )
    controller._applied_package_generation = 1
    tab.standalone_dotnet_material_package_token = (
        tab.standalone_dotnet_process_generation,
        1,
    )
    session_id = builder.controller.session_view().session_id
    completions: list[tuple[int, bool]] = []

    def material_resources_finished(
        generation: int,
        committed: bool,
        _resources: object,
        *_authority: object,
    ) -> None:
        completions.append((int(generation), bool(committed)))

    setattr(
        builder,
        "_mesh_editor_embedded_material_resources_finished",
        material_resources_finished,
    )
    hook = getattr(builder, "_mesh_editor_embedded_apply_material_resources")

    def binding(name: str, data: bytes) -> dict[str, object]:
        source = tmp_path / f"{name}.dds"
        source.write_bytes(data)
        return {
            "resource_id": f"authority/{name}",
            "channel": "base",
            "source_dds_path": source,
            "affected_submeshes": [0],
        }

    try:
        old_binding = binding("old-package", b"old")
        assert hook(
            builder.controller.working_mesh(clone=False),
            (old_binding,),
            affected_submeshes=(0,),
        )
        old_payload = _material_writes(app, process)[-1]
        _wait_for_material_compile_idle(app, tab)
        assert old_payload["package_generation"] == 1
        assert not tab._wait_for_dotnet_export_updates(0.0)

        controller._applied_package_generation = 2
        assert tab._rehydrate_shared_dotnet_controller(controller)
        boundary_generation = tab.standalone_dotnet_material_generation
        assert boundary_generation > old_payload["generation"]
        assert tab.standalone_dotnet_sent_material_resource_payload is None
        assert tab._wait_for_dotnet_export_updates(0.0)
        assert completions == [(old_payload["generation"], False)]

        assert not tab._handle_dotnet_protocol_event({
            "event": "material_state_applied",
            "session_id": session_id,
            "generation": old_payload["generation"],
            "package_generation": 1,
            "material_signature": old_payload["material_signature"],
            "texture_resources_ready": True,
        })
        assert (
            builder.controller.mesh_service.capture_export_snapshot(
                session_id
            ).texture_resources
            == ()
        )

        new_binding = binding("new-package", b"new")
        assert hook(
            builder.controller.working_mesh(clone=False),
            (new_binding,),
            affected_submeshes=(0,),
        )
        new_payload = _material_writes(app, process, minimum=2)[-1]
        assert new_payload["generation"] > boundary_generation
        assert new_payload["package_generation"] == 2
        assert tab._handle_dotnet_protocol_event({
            "event": "material_state_applied",
            "session_id": session_id,
            "generation": new_payload["generation"],
            "package_generation": 2,
            "material_signature": new_payload["material_signature"],
            "texture_resources_ready": True,
        })
        snapshot = builder.controller.mesh_service.capture_export_snapshot(session_id)
        assert snapshot.texture_resources[0].dds_data == b"new"
        assert completions[-1] == (new_payload["generation"], True)
    finally:
        tab.deleteLater()
        builder.deleteLater()
        app.processEvents()


def test_failed_new_material_attempt_preserves_inflight_generation_and_commit(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorMaterialGenerationFailure"))
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
    hook = getattr(builder, "_mesh_editor_embedded_apply_material_resources")
    session_id = builder.controller.session_view().session_id

    def binding(name: str, data: bytes) -> dict[str, object]:
        source = tmp_path / f"{name}.dds"
        source.write_bytes(data)
        return {
            "resource_id": f"authority/{name}",
            "channel": "base",
            "source_dds_path": source,
            "affected_submeshes": [0],
        }

    def acknowledge(generation: int) -> bool:
        return tab._handle_dotnet_protocol_event({
            "event": "material_state_applied",
            "session_id": session_id,
            "generation": generation,
            "material_signature": f"generation-{generation}",
        })

    try:
        first = binding("first", b"first")
        assert hook(builder.controller.working_mesh(clone=False), (first,), affected_submeshes=(0,))
        first_generation = tab.standalone_dotnet_material_generation
        assert first_generation == 1
        assert not tab._wait_for_dotnet_export_updates(0.0)

        with patch(
            "cdmw.ui.mesh_editor.tab_dotnet_resources.snapshot_mesh_dotnet_material_inputs",
            side_effect=RuntimeError("injected snapshot failure"),
        ):
            assert not tab._send_dotnet_material_state(reason="injected_snapshot_failure")

        assert tab.standalone_dotnet_material_generation == first_generation
        _material_writes(app, process)
        assert tab.standalone_dotnet_sent_material_resource_payload["generation"] == first_generation
        assert acknowledge(first_generation)
        _wait_for_material_compile_idle(app, tab)
        assert tab._wait_for_dotnet_export_updates(0.0)
        assert builder.controller.mesh_service.capture_export_snapshot(session_id).texture_resources[0].dds_data == b"first"

        second = binding("second", b"second")
        assert hook(builder.controller.working_mesh(clone=False), (second,), affected_submeshes=(0,))
        second_generation = tab.standalone_dotnet_material_generation
        assert second_generation == 2
        with patch(
            "cdmw.ui.mesh_editor.tab_dotnet_resources.snapshot_mesh_dotnet_material_inputs",
            side_effect=RuntimeError("injected second snapshot failure"),
        ):
            assert not tab._send_dotnet_material_state(reason="injected_snapshot_failure_2")

        assert tab.standalone_dotnet_material_generation == second_generation
        _material_writes(app, process, minimum=2)
        assert tab.standalone_dotnet_sent_material_resource_payload["generation"] == second_generation
        assert acknowledge(second_generation)
        resources = {
            resource.resource_id: resource.dds_data
            for resource in builder.controller.mesh_service.capture_export_snapshot(session_id).texture_resources
        }
        assert resources["authority/second"] == b"second"
    finally:
        tab.deleteLater()
        builder.deleteLater()
        app.processEvents()
