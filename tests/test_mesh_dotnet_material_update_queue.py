from __future__ import annotations

import json
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.ui.mesh_editor import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder, _FakeProcess


def _wait_for(app: QApplication, predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def _slow_payload(request, *, cancelled=None):
    for _index in range(60):
        if cancelled is not None and cancelled():
            raise RunCancelled("replaced")
        time.sleep(0.002)
    return {
        "schema": "cdmw_mesh_material_state_v3",
        "version": 3,
        "event": "material_state_update",
        "session_id": request.session_id,
        "edit_revision": request.edit_revision,
        "generation": request.generation,
        "material_signature": f"generation-{request.generation}",
        "affected_submeshes": [0],
        "resources": [],
        "submeshes": [],
        "compiler": {"cache_hit": False},
    }


def _material_updates(process: _FakeProcess) -> list[dict[str, object]]:
    return [
        payload
        for raw in process.stdin_writes
        if (payload := json.loads(raw.decode("utf-8"))).get("event")
        == "material_state_update"
    ]


def test_material_compiler_keeps_one_active_and_only_latest_pending_generation() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MaterialCompileLatestWins"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
    try:
        with patch(
            "cdmw.workers.mesh_dotnet_material_update_worker.compile_mesh_dotnet_material_update",
            side_effect=_slow_payload,
        ):
            assert tab._send_dotnet_material_state(reason="first")
            assert tab._send_dotnet_material_state(reason="second")
            assert tab._send_dotnet_material_state(reason="latest")
            assert tab.standalone_dotnet_material_generation == 3
            assert tab.standalone_dotnet_material_update_pending is not None
            assert tab.standalone_dotnet_material_update_pending[0].generation == 3
            assert _wait_for(app, lambda: len(_material_updates(process)) == 1)

        updates = _material_updates(process)
        assert [payload["generation"] for payload in updates] == [3]
        assert updates[0]["reason"] == "latest"
        assert tab.standalone_dotnet_lifecycle_counts["material_compile_replaced_count"] == 2
    finally:
        tab._stop_standalone_dotnet_editor_process()
        _wait_for(app, lambda: not tab._dotnet_material_compile_active())
        tab.deleteLater()
        builder.deleteLater()
        app.processEvents()


def test_editor_close_cancels_active_and_pending_material_compilation() -> None:
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MaterialCompileClose"))
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab.standalone_dotnet_editor_process = process
    tab._connect_dotnet_protocol(process)
    tab.standalone_dotnet_capabilities.add("resident_material_updates_v2")
    with patch(
        "cdmw.workers.mesh_dotnet_material_update_worker.compile_mesh_dotnet_material_update",
        side_effect=_slow_payload,
    ):
        assert tab._send_dotnet_material_state(reason="active")
        assert tab._send_dotnet_material_state(reason="pending")
        worker = tab.standalone_dotnet_material_update_worker
        assert worker is not None
        tab._stop_standalone_dotnet_editor_process()
        assert worker.stop_event.is_set()
        assert tab.standalone_dotnet_material_update_pending is None
        assert _wait_for(app, lambda: not tab._dotnet_material_compile_active())

    assert _material_updates(process) == []
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()
