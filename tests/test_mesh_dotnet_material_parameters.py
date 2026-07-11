from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.mesh_editor.controller import MeshEditorNativeUpdate
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder, _FakeProcess


_CAPABILITY = "resident_material_parameter_updates_v1"


@pytest.fixture
def resident_parameter_tab(request: pytest.FixtureRequest) -> Iterator[tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess]]:
    app = QApplication.instance() or QApplication([])
    settings = QSettings("CDMWTests", f"MeshMaterialParameters-{request.node.name}")
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add(_CAPABILITY)
    yield app, tab, builder, process
    tab.standalone_dotnet_material_parameter_timer.stop()
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def _parameter_writes(process: _FakeProcess) -> list[dict[str, object]]:
    return [
        payload
        for raw in process.stdin_writes
        if (payload := json.loads(raw.decode("utf-8"))).get("event") == "material_parameter_update"
    ]


def _flush_parameter_update(tab: MeshEditorTab) -> bool:
    tab.standalone_dotnet_material_parameter_timer.stop()
    return tab._flush_dotnet_material_parameter_update()


def test_embedded_hook_coalesces_latest_unsent_parameter_groups(
    resident_parameter_tab: tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess],
) -> None:
    _app, tab, builder, process = resident_parameter_tab
    hook = getattr(builder, "_mesh_editor_embedded_apply_material_parameters")
    capability = getattr(builder, "_mesh_editor_embedded_resident_material_parameters_supported")
    revision = builder.controller.session_view().revision

    assert callable(hook)
    assert capability()
    assert hook.__self__ is tab
    assert hook(({"source_submesh_indices": [0], "roughness": 0.2},))
    assert hook(({
        "source_submesh_indices": [1, "0", 1, -1, True],
        "roughness": 0.8,
        "tint_color": [0.2, 0.4, 0.6],
    },))
    assert _flush_parameter_update(tab)

    writes = _parameter_writes(process)
    assert len(writes) == 1
    payload = writes[0]
    assert payload == {
        "schema": "cdmw_mesh_material_parameters_v1",
        "version": 1,
        "event": "material_parameter_update",
        "session_id": builder.controller.session_view().session_id,
        "edit_revision": revision,
        "parameter_generation": 2,
        "affected_submeshes": [0, 1],
        "groups": [{
            "source_submesh_indices": [0, 1],
            "roughness": 0.8,
            "tint_color": [0.2, 0.4, 0.6],
        }],
    }
    assert tab.standalone_dotnet_lifecycle_counts["material_parameter_update_count"] == 1

    assert hook(({"source_submesh_indices": [1], "metalness": 0.5},))
    assert _flush_parameter_update(tab)
    second = _parameter_writes(process)[-1]
    assert second["parameter_generation"] == 3
    assert second["edit_revision"] == revision


def test_parameter_ack_requires_current_session_revision_and_generation(
    resident_parameter_tab: tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess],
) -> None:
    _app, tab, builder, process = resident_parameter_tab
    group = ({"source_submesh_indices": [0], "texture_brightness": 1.2},)
    assert tab.apply_resident_material_parameters(group)
    assert _flush_parameter_update(tab)
    first = _parameter_writes(process)[-1]
    session_id = str(first["session_id"])
    revision = int(first["edit_revision"])
    assert builder.controller.mesh_service.capture_export_snapshot(session_id).material_parameter_groups == ()

    assert not tab._handle_dotnet_protocol_event({
        "event": "material_parameter_applied",
        "session_id": "stale-session",
        "edit_revision": revision,
        "parameter_generation": 1,
    })
    assert not tab._handle_dotnet_protocol_event({
        "event": "material_parameter_applied",
        "session_id": session_id,
        "edit_revision": revision + 1,
        "parameter_generation": 1,
    })

    assert tab.apply_resident_material_parameters(group)
    assert _flush_parameter_update(tab)
    assert not tab._handle_dotnet_protocol_event({
        "event": "material_parameter_applied",
        "session_id": session_id,
        "edit_revision": revision,
        "parameter_generation": 1,
    })
    applied = {
        "event": "material_parameter_applied",
        "session_id": session_id,
        "edit_revision": revision,
        "parameter_generation": 2,
    }
    assert tab._handle_dotnet_protocol_event(applied)
    assert not tab._handle_dotnet_protocol_event(applied)
    assert tab.standalone_dotnet_applied_material_parameter_generation == 2
    assert tab.standalone_dotnet_lifecycle_counts["material_parameter_applied_count"] == 1
    committed = builder.controller.mesh_service.capture_export_snapshot(session_id)
    assert committed.material_parameter_groups == ({
        "source_submesh_indices": [0],
        "texture_brightness": 1.2,
    },)

    assert tab.apply_resident_material_parameters(group)
    assert _flush_parameter_update(tab)
    failed = {
        "event": "material_parameter_failed",
        "session_id": session_id,
        "edit_revision": revision,
        "parameter_generation": 3,
        "reason": "invalid_parameter",
    }
    assert not tab._handle_dotnet_protocol_event(failed)
    assert not tab._handle_dotnet_protocol_event(failed)
    assert tab.standalone_dotnet_lifecycle_counts["material_parameter_failed_count"] == 1
    assert (
        builder.controller.mesh_service.capture_export_snapshot(session_id).material_parameter_groups
        == committed.material_parameter_groups
    )


def test_native_material_override_update_uses_separate_parameter_event(
    resident_parameter_tab: tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess],
) -> None:
    _app, tab, _builder, process = resident_parameter_tab
    update = MeshEditorNativeUpdate(material_override_groups=({
        "source_submesh_indices": [0],
        "emissive_intensity": 2.0,
        "emissive_color": [0.1, 0.3, 0.8],
    },))

    tab._send_dotnet_native_update(update)
    assert _flush_parameter_update(tab)

    writes = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
    assert [payload["event"] for payload in writes if payload["event"] == "material_parameter_update"] == [
        "material_parameter_update"
    ]
    assert not any(payload["event"] == "preview_triangle_update" for payload in writes)


def test_material_state_can_target_affected_submeshes_and_snapshot(
    resident_parameter_tab: tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess],
) -> None:
    _app, tab, builder, process = resident_parameter_tab
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
    mesh = builder.controller.working_mesh(clone=True)

    assert tab._send_dotnet_material_state(
        reason="texture_replaced",
        affected_submeshes=(1,),
        mesh_snapshot=mesh,
    )

    payload = next(
        json.loads(raw.decode("utf-8"))
        for raw in process.stdin_writes
        if b'"event":"material_state_update"' in raw
    )
    assert payload["affected_submeshes"] == [1]
    assert payload["reason"] == "texture_replaced"


def test_parameter_sender_rejects_missing_capability_and_empty_groups(
    resident_parameter_tab: tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess],
) -> None:
    _app, tab, _builder, process = resident_parameter_tab
    tab.standalone_dotnet_capabilities.discard(_CAPABILITY)
    assert not tab.apply_resident_material_parameters(({
        "source_submesh_indices": [0],
        "roughness": 0.4,
    },))
    tab.standalone_dotnet_capabilities.add(_CAPABILITY)
    assert not tab.apply_resident_material_parameters(({"source_submesh_indices": []},))
    assert _parameter_writes(process) == []


def test_empty_source_scope_with_parameters_targets_all_batches(
    resident_parameter_tab: tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess],
) -> None:
    _app, tab, _builder, process = resident_parameter_tab

    assert tab.apply_resident_material_parameters(({
        "source_submesh_indices": [],
        "texture_brightness": 1.1,
    },))
    assert _flush_parameter_update(tab)

    payload = _parameter_writes(process)[-1]
    assert payload["affected_submeshes"] == []
    assert payload["groups"][0]["source_submesh_indices"] == []


def test_parameter_dispatch_stays_queued_and_under_ui_budget(
    resident_parameter_tab: tuple[QApplication, MeshEditorTab, _EmbeddedMeshBuilder, _FakeProcess],
) -> None:
    _app, tab, _builder, process = resident_parameter_tab
    process.write = lambda _data: (_ for _ in ()).throw(AssertionError("synchronous protocol write"))  # type: ignore[method-assign]
    timings = []
    for value in range(100):
        started = time.perf_counter()
        assert tab.apply_resident_material_parameters(({
            "source_submesh_indices": [0],
            "roughness": value / 100.0,
        },))
        timings.append((time.perf_counter() - started) * 1000.0)
    tab.standalone_dotnet_material_parameter_timer.stop()
    assert sorted(timings)[94] < 50.0
