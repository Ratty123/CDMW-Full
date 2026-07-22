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

from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    mesh_dotnet_material_input_signature,
)
from cdmw.modding.static_mesh_scene_frame import static_scene_source_identity
from cdmw.ui.mesh_editor import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder, _FakeProcess


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
    payload = _material_writes(app, process)[0]
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
        "reason": "decode_failed",
    })
    assert builder.controller.mesh_service.capture_export_snapshot(session_id).texture_revisions == (
        ("authority/base", "base", 1),
    )
    assert completions[-1][0:2] == (failed_payload["generation"], False)
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_late_exact_clone_materials_update_editable_then_reference_resources(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorLateExactCloneMaterials"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
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

    clone_hook = getattr(builder, "_mesh_editor_embedded_apply_clone_material_resources")
    reference_hook = getattr(builder, "_mesh_editor_embedded_apply_reference_material_resources")
    assert clone_hook(preview_model)
    assert reference_hook(preview_model)
    assert tab.standalone_dotnet_pending_reference_material_model is preview_model
    assert all(submesh.preview_texture_path == str(texture_path) for submesh in editable_mesh.submeshes)

    material_writes = _material_writes(app, process)
    assert len(material_writes) == 1
    assert material_writes[0]["reason"] == "late_exact_clone_resources"
    assert all(resource["role"] == "replacement" for resource in material_writes[0]["resources"])

    assert tab._handle_dotnet_protocol_event({
        "event": "material_state_applied",
        "generation": material_writes[0]["generation"],
        "material_signature": material_writes[0]["material_signature"],
    })
    app.processEvents()
    material_writes = _material_writes(app, process, minimum=2)
    assert len(material_writes) == 2
    assert material_writes[1]["reason"] == "late_original_reference_resources"
    assert all(resource["role"] == "original_reference" for resource in material_writes[1]["resources"])

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
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
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

    assert tab.apply_resident_clone_material_resources(preview_model)
    assert tab.apply_resident_reference_material_resources(preview_model)
    assert tab.standalone_dotnet_pending_clone_material_model is preview_model
    assert tab.standalone_dotnet_pending_reference_material_model is preview_model

    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    assert tab.standalone_dotnet_pending_clone_material_model is preview_model
    assert tab.standalone_dotnet_pending_reference_material_model is preview_model
    assert not process.stdin_writes

    tab._observe_dotnet_capabilities({"capabilities": ["resident_material_updates_v2"]})
    app.processEvents()
    material_writes = _material_writes(app, process)
    assert len(material_writes) == 1
    assert material_writes[0]["reason"] == "late_exact_clone_resources"
    assert tab.standalone_dotnet_pending_reference_material_model is preview_model

    tab._stop_standalone_dotnet_editor_process()
    assert tab.standalone_dotnet_pending_clone_material_model is None
    assert tab.standalone_dotnet_pending_reference_material_model is None

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
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
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
