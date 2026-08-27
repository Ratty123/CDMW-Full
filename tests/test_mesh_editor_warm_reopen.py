from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _dotnet_test_package,
    _install_shared_dotnet_test_process,
)


def test_mesh_editor_tab_starts_a_new_direct_package_in_a_released_warm_helper() -> None:
    """Close leaves the helper warm, so the next direct mesh must refill it."""

    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDirectWarmReopen"))
    first_builder = _EmbeddedMeshBuilder(session_id="direct-session-a")
    second_builder = _EmbeddedMeshBuilder(session_id="direct-session-b")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        executable = root / "cdmw-mesh-dotnet-editor.exe"
        executable.write_bytes(b"helper")
        first_package = _dotnet_test_package(root / "first")
        process = _FakeProcess(tab)
        process._state = process.Running
        tab.standalone_controller = first_builder.controller
        tab.standalone_dotnet_target_embedded = False
        tab.standalone_dotnet_target_controller = first_builder.controller
        tab.standalone_dotnet_experiment_package = first_package
        resident = _install_shared_dotnet_test_process(
            tab,
            process,
            capabilities=("authoring_session_handoff_v1",),
            session_id="direct-session-a",
        )
        starts: list[tuple[object, bool, Path]] = []
        statuses: list[str] = []
        tab.status_message_requested.connect(
            lambda text, _error: statuses.append(str(text))
        )
        with patch.object(
            tab,
            "_dotnet_editor_executable_path",
            return_value=executable,
        ), patch.object(
            tab,
            "_start_standalone_dotnet_package_worker",
            side_effect=lambda controller, *, embedded, executable: starts.append(
                (controller, bool(embedded), Path(executable))
            ),
        ):
            tab._start_dotnet_editor_requested(second_builder.controller, embedded=False)
            assert starts == []
            assert "Mesh .NET editor experiment is already running." in statuses

            statuses.clear()
            tab.close_standalone_session()
            assert resident.is_running
            assert resident.applied_package_path == ""
            assert tab.standalone_dotnet_target_controller is None
            tab._start_dotnet_editor_requested(second_builder.controller, embedded=False)

        assert len(starts) == 1
        assert starts[0] == (second_builder.controller, False, executable)
        assert "Mesh .NET editor experiment is already running." not in statuses

    second_builder.controller.close_active_session()
    first_builder.deleteLater()
    second_builder.deleteLater()
    tab.deleteLater()
    app.processEvents()
