from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QPushButton

from cdmw.services.mesh_rust_contract import RUST_MESH_EDIT_BACKEND, RUST_MESH_RENDERER
from cdmw.ui.mesh_editor.rust_host import RustMeshEditorHostFrame
from cdmw.ui.mesh_editor.tab import MeshEditorTab


class _FakeUser32:
    def __init__(self, *, owner_pid: int, parent_hwnd: int) -> None:
        self.owner_pid = owner_pid
        self.parent_hwnd = parent_hwnd
        self.visible: list[int] = []
        self.positions: list[tuple[int, int, int]] = []
        self.focused: list[int] = []

    def IsWindow(self, _hwnd: object) -> bool:  # noqa: N802
        return True

    def GetWindowThreadProcessId(self, _hwnd: object, owner: object) -> int:  # noqa: N802
        owner._obj.value = self.owner_pid
        return 1

    def SetParent(self, _child: object, parent: object) -> int:  # noqa: N802
        self.parent_hwnd = int(parent.value or 0)
        return self.parent_hwnd

    def GetParent(self, _child: object) -> int:  # noqa: N802
        return self.parent_hwnd

    def GetWindowLongPtrW(self, _hwnd: object, _index: int) -> int:  # noqa: N802
        return 0

    def SetWindowLongPtrW(self, _hwnd: object, _index: int, _value: object) -> int:  # noqa: N802
        return 0

    def GetClientRect(self, _hwnd: object, rect: object) -> bool:  # noqa: N802
        rect._obj.left = 0
        rect._obj.top = 0
        rect._obj.right = 800
        rect._obj.bottom = 600
        return True

    def SetWindowPos(self, _child: object, _after: object, _x: int, _y: int, width: int, height: int, flags: int) -> bool:  # noqa: N802
        self.positions.append((int(width), int(height), int(flags)))
        return True

    def ShowWindow(self, _hwnd: object, state: int) -> bool:  # noqa: N802
        self.visible.append(state)
        return True

    def SetFocus(self, hwnd: object) -> int:  # noqa: N802
        self.focused.append(int(hwnd.value or 0))
        return 1


def _tab(tmp_path: Path) -> MeshEditorTab:
    application = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    application.processEvents()
    return tab


def test_direct_workspace_constructs_only_the_rust_native_host(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    assert isinstance(tab.standalone_native_host_frame, RustMeshEditorHostFrame)
    assert tab.standalone_native_host_frame.controller is None
    assert tab.mesh_editor_backend_combo is None
    assert tab.findChild(RustMeshEditorHostFrame, "MeshEditorEmbeddedRustHost") is not None
    assert tab.findChild(RustMeshEditorHostFrame, "MeshEditorStandaloneDotNetVorticeHost") is None


def test_rust_theme_payload_carries_exact_app_palette_type_scale_and_density(
    tmp_path: Path,
) -> None:
    tab = _tab(tmp_path)
    application = QApplication.instance()
    assert application is not None
    original_font = QFont(application.font())
    try:
        application.setFont(QFont("Verdana", 12))
        tab.settings.setValue("appearance/data_font_size", 11)
        tab.settings.setValue("appearance/ui_density", "comfortable")
        tab.theme_key = "light"
        payload = tab._rust_theme_payload()
    finally:
        application.setFont(original_font)

    assert payload["schema"] == "cdmw_ui_theme_v1"
    assert payload["theme"] == "light"
    assert payload["variant"] == "light"
    assert payload["palette"]["window"] == "#f4f6f8"
    assert payload["palette"]["accent"] == "#2563eb"
    assert payload["font_family"] == "Verdana"
    assert payload["font_point_size"] == 12.0
    assert payload["data_font_point_size"] == 11.0
    assert payload["density"] == "comfortable"


def test_live_theme_change_is_sent_to_the_ready_embedded_child(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    sent: list[dict[str, object]] = []
    tab.standalone_rust_ready = True
    tab._send_rust_message = lambda payload: sent.append(dict(payload)) or True  # type: ignore[method-assign]

    tab.set_theme("nord")

    assert sent[-1]["event"] == "theme_update"
    assert sent[-1]["payload"]["theme"] == "nord"
    assert sent[-1]["payload"]["variant"] == "dark"


def test_host_rejects_child_window_owned_by_another_process() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    launch_parent = host.prepare_launch()
    api = _FakeUser32(owner_pid=999, parent_hwnd=launch_parent)
    with patch("cdmw.ui.mesh_editor.rust_host._windows_api", return_value=api):
        attached, reason = host.attach_child_window(123, 77, launch_parent)
    assert attached is False
    assert "not owned" in reason
    assert host.child_hwnd == 0
    host.deleteLater()
    application.processEvents()


def test_host_attaches_owned_child_and_sizes_it_to_current_qt_hwnd() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    launch_parent = host.prepare_launch()
    api = _FakeUser32(owner_pid=77, parent_hwnd=launch_parent)
    with patch("cdmw.ui.mesh_editor.rust_host._windows_api", return_value=api):
        attached, reason = host.attach_child_window(123, 77, launch_parent)
    assert (attached, reason) == (True, "")
    assert host.child_hwnd == 123
    assert api.parent_hwnd == host.host_hwnd()
    host.deleteLater()
    application.processEvents()


def test_host_rejects_a_stale_reported_parent_before_reparenting() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    launch_parent = host.prepare_launch()
    api = _FakeUser32(owner_pid=77, parent_hwnd=launch_parent)
    with patch("cdmw.ui.mesh_editor.rust_host._windows_api", return_value=api):
        attached, reason = host.attach_child_window(123, 77, launch_parent + 1)
    assert attached is False
    assert "stale or mismatched" in reason
    assert host.child_hwnd == 0
    host.deleteLater()
    application.processEvents()


def test_host_resizes_hides_focuses_and_reparents_the_owned_child() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    host.show()
    application.processEvents()
    launch_parent = host.prepare_launch()
    api = _FakeUser32(owner_pid=77, parent_hwnd=launch_parent)
    with patch("cdmw.ui.mesh_editor.rust_host._windows_api", return_value=api):
        attached, reason = host.attach_child_window(123, 77, launch_parent)
        assert (attached, reason) == (True, "")
        host.event(QEvent(QEvent.Type.Resize))
        host.event(QEvent(QEvent.Type.Hide))
        host.event(QEvent(QEvent.Type.Show))
        host.event(QEvent(QEvent.Type.FocusIn))
        host.host_hwnd = lambda: launch_parent + 10  # type: ignore[method-assign]
        host.event(QEvent(QEvent.Type.WinIdChange))

    assert api.positions
    assert api.positions[-1][:2] == (800, 600)
    assert 0 in api.visible
    assert 5 in api.visible
    assert api.focused[-1] == 123
    assert api.parent_hwnd == launch_parent + 10
    host.deleteLater()
    application.processEvents()


def test_result_page_actions_and_retry_are_explicit_signals() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    emitted: list[str] = []
    host.retry_requested.connect(lambda: emitted.append("retry"))
    host.run_validation_requested.connect(lambda: emitted.append("validate"))
    host.build_mod_requested.connect(lambda: emitted.append("build"))
    host.install_overlay_requested.connect(lambda: emitted.append("install"))
    host.restore_overlay_requested.connect(lambda: emitted.append("restore"))
    host.reopen_edit_requested.connect(lambda: emitted.append("reopen"))
    host.close_session_requested.connect(lambda: emitted.append("close"))

    host.show_error("failed")
    host.findChild(QPushButton, "MeshEditorRustHostRetry").click()
    host.show_result("accepted")
    for object_name in (
        "MeshEditorRustResultRunValidation",
        "MeshEditorRustResultBuildMod",
        "MeshEditorRustResultInstallasOverlay",
        "MeshEditorRustResultRestoreLastOverlayInstall",
        "MeshEditorRustResultReopenEdit",
        "MeshEditorRustResultCloseSession",
    ):
        host.findChild(QPushButton, object_name).click()

    assert emitted == ["retry", "validate", "build", "install", "restore", "reopen", "close"]
    host.deleteLater()
    application.processEvents()


def test_hello_requires_embedded_capability_and_passes_pid_to_host(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    tab.standalone_rust_process = SimpleNamespace(processId=lambda: 77)  # type: ignore[assignment]
    attached: list[tuple[int, int, int]] = []
    tab.standalone_native_host_frame.attach_child_window = (  # type: ignore[method-assign]
        lambda child, pid, parent: attached.append((child, pid, parent)) or (True, "")
    )
    sent: list[object] = []
    tab._send_rust_message = lambda payload: sent.append(payload) or True  # type: ignore[method-assign]
    payload = {
        "renderer": RUST_MESH_RENDERER,
        "edit_backend": RUST_MESH_EDIT_BACKEND,
        "capabilities": ["embedded_child_window_v1"],
        "child_hwnd": 123,
        "embedded_parent_hwnd": 456,
    }
    tab._handle_rust_hello(payload)
    assert attached == [(123, 77, 456)]
    assert tab.standalone_rust_hello_received is True
    assert sent
