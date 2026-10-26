from __future__ import annotations

import hashlib
import os
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QProcess, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton, QScrollArea, QToolButton

from cdmw.services.mesh_rust_contract import (
    RUST_MESH_EDIT_BACKEND,
    RUST_MESH_RENDERER,
    rust_mesh_editor_file_signature,
)
from cdmw.ui.mesh_editor.rust_host import RustMeshEditorHostFrame
from cdmw.ui.mesh_editor.tab import MeshEditorTab


class _FakeUser32:
    def __init__(self, *, owner_pid: int, parent_hwnd: int) -> None:
        self.owner_pid = owner_pid
        self.parent_hwnd = parent_hwnd
        self.visible: list[int] = []
        self.positions: list[tuple[int, int, int]] = []
        self.focused: list[int] = []
        self.paints: list[int] = []
        self.client_size = (800, 600)

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
        rect._obj.right, rect._obj.bottom = self.client_size
        return True

    def SetWindowPos(self, _child: object, _after: object, _x: int, _y: int, width: int, height: int, flags: int) -> bool:  # noqa: N802
        assert flags & 0x4000, "Resizing must not wait on the child window thread"
        self.positions.append((int(width), int(height), int(flags)))
        return True

    def ShowWindowAsync(self, _hwnd: object, state: int) -> bool:  # noqa: N802
        self.visible.append(state)
        return True

    def SetFocus(self, hwnd: object) -> int:  # noqa: N802
        self.focused.append(int(hwnd.value or 0))
        return 1

    def PostMessageW(self, hwnd, message, wparam, lparam):  # noqa: N802
        assert (message, wparam, lparam) == (0x000F, 0, 0)
        self.paints.append(int(hwnd.value))
        return True


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


def test_native_theme_palette_fixture_matches_the_application_themes() -> None:
    # The Rust editor's theme readability test runs on this copy of every palette.
    from cdmw.ui.theme_schemes import UI_THEME_SCHEMES

    fixture = Path(__file__).resolve().parents[1] / "tools/rust_mesh_lab/apps/cdmw_mesh_lab/tests/fixtures/ui-theme-palettes.json"
    expected = {
        key: {name: value for name, value in scheme.items() if name != "label"}
        for key, scheme in UI_THEME_SCHEMES.items()
    }
    assert json.loads(fixture.read_text(encoding="utf-8")) == expected


def _delivered_theme(messages: list[dict[str, object]]) -> dict[str, object]:
    """Rebuild the theme a helper applies from one update's control lines."""

    from cdmw.ui.mesh_editor.process_io import DOTNET_PROTOCOL_LINE_LIMIT
    from cdmw.ui.mesh_editor.rust_theme_transport import protocol_line

    *parts, update = messages
    assert update["event"] == "theme_update"
    assert all(len(protocol_line(message)) <= DOTNET_PROTOCOL_LINE_LIMIT for message in messages)
    theme = dict(update["payload"])
    transfer = update.get("translations_transfer")
    if transfer is None:
        assert parts == []
        return theme
    assert "translations" not in theme
    assert [part["event"] for part in parts] == ["theme_translations_part"] * len(parts)
    assert [part["part_index"] for part in parts] == list(range(len(parts)))
    identity = ("protocol", "session_id", "request_id", "base_revision", "process_generation")
    descriptor = {key: transfer[key] for key in ("part_count", "byte_length", "sha256")}
    for part in parts:
        assert {key: part[key] for key in identity} == {key: update[key] for key in identity}
        assert {key: part[key] for key in descriptor} == descriptor
    data = "".join(part["data"] for part in parts).encode("utf-8")
    assert descriptor == {
        "part_count": len(parts),
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
    }
    theme["translations"] = json.loads(data)
    assert len(theme["translations"]) == transfer["entry_count"]
    return theme


def _expected_native_translations(localizer: object) -> dict[str, object]:
    from cdmw.ui.localization_catalogs_v2 import native_ui_source_keys

    expected = localizer.translation_snapshot(native_ui_source_keys(), max_bytes=64 << 20)
    return {key: entry for key, entry in expected.items() if entry != key}


def _pad_native_catalog(
    localizer: object, *, minimum_bytes: int, repeat: int = 1,
) -> tuple[str, ...]:
    """Grow the native catalogue past ``minimum_bytes`` in the language's own script."""

    from cdmw.ui.localization_catalogs_v2 import native_ui_source_keys

    sample = " ".join(
        str(localizer.translate(key))
        for key in ("Mesh Editor", "Clear Selection", "Create / update guides")
    ) * repeat
    keys = list(native_ui_source_keys())
    size = len(json.dumps(_expected_native_translations(localizer), ensure_ascii=False).encode())
    index = 0
    while size < minimum_bytes:
        key = f"Synthetic native label {index} \"quoted\" \\ {{value_0}}"
        value = f"{sample} «{index}» \"{sample}\" \\ {{value_0}} {sample}"
        localizer.translations[key] = value
        keys.append(key)
        size += len(json.dumps({key: value}, ensure_ascii=False).encode())
        index += 1
    return tuple(keys)


def test_native_localization_payload_covers_every_language_and_live_updates(tmp_path: Path) -> None:
    from cdmw.domain.localization import BUILTIN_LANGUAGES
    from cdmw.ui.localization import UiLocalizer

    tab = _tab(tmp_path)
    app = QApplication.instance()
    previous = app.property("_cdmw_ui_localizer")
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="en")
    app.setProperty("_cdmw_ui_localizer", localizer)
    sent = []
    tab.standalone_rust_ready = True
    tab.standalone_rust_translation_parts_supported = True
    tab._send_rust_message = lambda payload: sent.append(payload) or True
    try:
        for language in BUILTIN_LANGUAGES:
            localizer.load_language(language.code)
            first = len(sent)
            tab.set_theme("graphite")
            payload = _delivered_theme(sent[first:])
            assert payload["language"] == language.code
            assert payload["translations"] == _expected_native_translations(localizer)
            for key in ("Clear Selection", "Mesh Editor", "Create / update guides"):
                assert payload["translations"].get(key, key) == localizer.translate(key)
        # A user-provided English overlay must work in the native editor too.
        localizer.load_language("en")
        localizer.translations["Mesh Editor"] = "Custom mesh tools"
        assert tab._rust_theme_payload()["translations"]["Mesh Editor"] == "Custom mesh tools"
    finally:
        app.setProperty("_cdmw_ui_localizer", previous)
        localizer.shutdown()
        tab.deleteLater()


def test_native_localization_delivers_a_mebibyte_catalog_at_start_and_live(tmp_path: Path) -> None:
    from cdmw.domain.localization import BUILTIN_LANGUAGES
    from cdmw.services.mesh_rust_contract import RUST_UI_TRANSLATION_PARTS_CAPABILITY
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.mesh_editor.rust_theme_transport import rust_theme_digest
    from tests.test_mesh_rust_editor_selection import _provenanced_resolution

    class _InertProcess(QProcess):
        def start(self, *_args: object) -> None:
            return None

    tab = _tab(tmp_path)
    app = QApplication.instance()
    previous = app.property("_cdmw_ui_localizer")
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="en")
    app.setProperty("_cdmw_ui_localizer", localizer)
    resolution = _provenanced_resolution(tmp_path / "helper")
    tab.standalone_rust_executable_path = Path(resolution.resolved_path)
    tab.standalone_rust_launch_executable_signature = rust_mesh_editor_file_signature(resolution)
    tab.standalone_native_host_frame.attach_child_window = (  # type: ignore[method-assign]
        lambda *_args: (True, "")
    )
    sent: list[dict[str, object]] = []
    tab._send_rust_message = lambda payload: sent.append(dict(payload)) or True  # type: ignore[method-assign]
    try:
        for language in BUILTIN_LANGUAGES:
            localizer.load_language(language.code)
            keys = _pad_native_catalog(localizer, minimum_bytes=1 << 20)
            with patch("cdmw.ui.localization_catalogs_v2.native_ui_source_keys", return_value=keys):
                expected = _expected_native_translations(localizer)
                assert len(json.dumps(expected, ensure_ascii=False).encode()) >= 1 << 20
                # Session start: the whole catalogue goes into the manifest theme.
                start_theme = tab._rust_theme_payload()
                assert start_theme["translations"] == expected
                tab._reset_rust_protocol_state()
                with (
                    patch(
                        "cdmw.ui.mesh_editor.tab_rust_editor.resolve_rust_mesh_editor",
                        return_value=resolution,
                    ),
                    patch("cdmw.ui.mesh_editor.tab_rust_process.QProcess", _InertProcess),
                ):
                    tab._launch_rust_editor_process(
                        SimpleNamespace(manifest_path=tmp_path / "manifest.json", theme=start_theme)
                    )
                assert tab.standalone_rust_theme_digest == rust_theme_digest(start_theme)
                tab._handle_rust_hello({
                    "renderer": RUST_MESH_RENDERER,
                    "edit_backend": RUST_MESH_EDIT_BACKEND,
                    "capabilities": ["embedded_child_window_v1", RUST_UI_TRANSLATION_PARTS_CAPABILITY],
                    "child_hwnd": 123,
                    "embedded_parent_hwnd": 456,
                })
                assert tab.standalone_rust_translation_parts_supported is True
                first = len(sent)
                tab._handle_rust_ready({})
                # The helper already holds this theme from its manifest.
                assert [message["event"] for message in sent[first:]] == []

                # Live update: a theme change resends the whole catalogue in parts.
                first = len(sent)
                tab.set_theme("nord")
                delivered = _delivered_theme(sent[first:])
                assert len(sent[first:]) > 4
                assert delivered["theme"] == "nord"
                assert delivered["language"] == language.code
                assert delivered["translations"] == expected
                first = len(sent)
                tab.set_theme("nord")
                assert sent[first:] == []
                tab.theme_key = "graphite"
            stop = getattr(tab.standalone_rust_process, "deleteLater", None)
            if callable(stop):
                stop()
            tab.standalone_rust_process = None
    finally:
        app.setProperty("_cdmw_ui_localizer", previous)
        localizer.shutdown()
        tab.deleteLater()
        QApplication.processEvents()


def test_theme_updates_are_contiguous_ordered_and_resent_whole_after_a_failed_line(
    tmp_path: Path,
) -> None:
    from cdmw.ui.localization import UiLocalizer

    tab = _tab(tmp_path)
    app = QApplication.instance()
    previous = app.property("_cdmw_ui_localizer")
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="ja")
    app.setProperty("_cdmw_ui_localizer", localizer)
    keys = _pad_native_catalog(localizer, minimum_bytes=600 * 1024)
    sent: list[dict[str, object]] = []
    accept = {"lines": 10_000}

    def send(payload: dict[str, object]) -> bool:
        if accept["lines"] <= 0:
            return False
        accept["lines"] -= 1
        sent.append(dict(payload))
        return True

    tab._send_rust_message = send  # type: ignore[method-assign]
    tab.standalone_rust_ready = True
    tab.standalone_rust_translation_parts_supported = True
    try:
        with patch("cdmw.ui.localization_catalogs_v2.native_ui_source_keys", return_value=keys):
            assert tab._send_rust_theme_update() is True
            first_update = list(sent)
            first_request = first_update[-1]["request_id"]
            assert {message["request_id"] for message in first_update} == {first_request}
            assert _delivered_theme(first_update)["translations"] == _expected_native_translations(localizer)

            # The process stops accepting lines partway through the next transfer.
            sent.clear()
            tab.theme_key = "nord"
            accept["lines"] = 1
            assert tab._send_rust_theme_update() is False
            assert [message["event"] for message in sent] == ["theme_translations_part"]
            assert tab.standalone_rust_theme_digest == ""

            # Nothing is assumed delivered: the retry is a new, complete transfer.
            sent.clear()
            accept["lines"] = 10_000
            assert tab._send_rust_theme_update() is True
            assert sent[0]["part_index"] == 0
            assert sent[-1]["request_id"] > first_request + 1
            assert _delivered_theme(sent)["theme"] == "nord"
    finally:
        app.setProperty("_cdmw_ui_localizer", previous)
        localizer.shutdown()
        tab.deleteLater()


def test_helper_without_translation_parts_keeps_its_theme_and_names_the_line_limit(
    tmp_path: Path,
) -> None:
    from cdmw.ui.localization import UiLocalizer

    tab = _tab(tmp_path)
    app = QApplication.instance()
    previous = app.property("_cdmw_ui_localizer")
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="ru")
    app.setProperty("_cdmw_ui_localizer", localizer)
    keys = _pad_native_catalog(localizer, minimum_bytes=400 * 1024)
    sent: list[dict[str, object]] = []
    tab._send_rust_message = lambda payload: sent.append(dict(payload)) or True  # type: ignore[method-assign]
    tab.standalone_rust_ready = True
    tab.standalone_rust_theme_digest = "theme-from-the-manifest"
    try:
        with patch("cdmw.ui.localization_catalogs_v2.native_ui_source_keys", return_value=keys):
            assert tab._send_rust_theme_update() is False
        assert sent == []
        assert tab.standalone_rust_theme_digest == "theme-from-the-manifest"
        status = tab.standalone_status_label.text()
        assert "bytes; limit is" in status
        # A catalogue that fits one line still reaches an older helper.
        assert tab._send_rust_theme_update() is True
        assert [message["event"] for message in sent] == ["theme_update"]
        assert sent[0]["payload"]["translations"] == _expected_native_translations(localizer)
    finally:
        app.setProperty("_cdmw_ui_localizer", previous)
        localizer.shutdown()
        tab.deleteLater()


def test_translation_parts_are_bounded_by_the_helper_catalog_limit(tmp_path: Path) -> None:
    from cdmw.services.mesh_rust_contract import RUST_UI_TRANSLATION_MAX_BYTES
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.mesh_editor.rust_theme_transport import rust_theme_update_messages

    tab = _tab(tmp_path)
    app = QApplication.instance()
    previous = app.property("_cdmw_ui_localizer")
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="zh-Hans")
    app.setProperty("_cdmw_ui_localizer", localizer)
    keys = _pad_native_catalog(
        localizer, minimum_bytes=RUST_UI_TRANSLATION_MAX_BYTES + 65536, repeat=8,
    )
    sent: list[dict[str, object]] = []
    tab._send_rust_message = lambda payload: sent.append(dict(payload)) or True  # type: ignore[method-assign]
    tab.standalone_rust_ready = True
    tab.standalone_rust_translation_parts_supported = True
    try:
        with patch("cdmw.ui.localization_catalogs_v2.native_ui_source_keys", return_value=keys):
            assert tab._send_rust_theme_update() is False
        assert sent == []
        assert f"limit is {RUST_UI_TRANSLATION_MAX_BYTES:,}" in tab.standalone_status_label.text()
        # Without translations a theme that cannot fit one line is refused, not split.
        message = {
            "event": "theme_update", "protocol": "p", "session_id": "s", "request_id": 1,
            "base_revision": 0, "process_generation": 1,
            "payload": {"layout": "x" * (300 * 1024), "translations": {"Undo": "元に戻す"}},
        }
        with pytest.raises(ValueError, match="limit is"):
            rust_theme_update_messages(message, line_limit=256 * 1024, parts_supported=True)
    finally:
        app.setProperty("_cdmw_ui_localizer", previous)
        localizer.shutdown()
        tab.deleteLater()


def test_host_rejects_child_window_owned_by_another_process() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    launch_parent = host.prepare_launch()
    assert launch_parent == int(host._surface.winId())
    assert launch_parent != int(host.winId())
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
    focus_requests = []
    host.focus_requested.connect(lambda: focus_requests.append(True))
    host._focus_request_supported = True
    host.hasFocus = lambda: True
    with patch("cdmw.ui.mesh_editor.rust_host._windows_api", return_value=api):
        attached, reason = host.attach_child_window(123, 77, launch_parent)
        assert (attached, reason) == (True, "")
        host.event(QEvent(QEvent.Type.Resize))
        host.event(QEvent(QEvent.Type.Hide))
        host.event(QEvent(QEvent.Type.Show))
        host.event(QEvent(QEvent.Type.FocusIn))
        assert focus_requests == []
        application.processEvents()
        host.host_hwnd = lambda: launch_parent + 10  # type: ignore[method-assign]
        host.event(QEvent(QEvent.Type.WinIdChange))
        host.host_hwnd = lambda: launch_parent + 20  # type: ignore[method-assign]
        application.sendEvent(host._surface, QEvent(QEvent.Type.WinIdChange))

    assert api.positions
    assert api.positions[-1][:2] == (800, 600)
    assert 0 in api.visible
    assert 5 in api.visible
    assert api.focused == []
    assert focus_requests == [True]
    assert api.parent_hwnd == launch_parent + 20
    host.deleteLater()
    application.processEvents()


def test_prewarmed_host_uses_native_size_settled_after_show_and_resize() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    launch_parent = host.prepare_launch()
    api = _FakeUser32(owner_pid=77, parent_hwnd=launch_parent)
    with patch("cdmw.ui.mesh_editor.rust_host._windows_api", return_value=api):
        assert host.attach_child_window(123, 77, launch_parent) == (True, "")
        assert not host.isVisible()
        host.show()
        assert api.positions[-1][:2] == (800, 600)
        # Windows finishes its parent resize after Qt sends Show/Resize.
        api.client_size = (1600, 900)
        application.processEvents()
        assert api.positions[-1][:2] == (1600, 900)

        host.resize(1100, 720)
        api.client_size = (1650, 1080)
        application.processEvents()
        assert api.positions[-1][:2] == (1650, 1080)

        host.resize(1200, 800)
        host.hide()
        positions = len(api.positions)
        application.processEvents()
        assert len(api.positions) == positions
        host.detach_child_window()
    host.deleteLater()
    application.processEvents()


def test_hiding_or_losing_focus_cancels_an_obsolete_focus_request() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    requests = []
    host.focus_requested.connect(lambda: requests.append(True))
    host.show()
    application.processEvents()
    host._editor_visible = True
    host._child_hwnd = 123
    host._focus_request_supported = True
    host.hasFocus = lambda: True
    try:
        host.event(QEvent(QEvent.Type.FocusIn))
        host.hide()
        application.processEvents()
        assert requests == []
        host._child_hwnd = 0
        host.show()
        application.processEvents()
        host._child_hwnd = 123
        host.event(QEvent(QEvent.Type.FocusIn))
        host.event(QEvent(QEvent.Type.FocusOut))
        application.processEvents()
        assert requests == []
    finally:
        host._child_hwnd = 0
        host.close()
        host.deleteLater()
        application.processEvents()


def test_mesh_editor_routes_focus_through_its_existing_process_channel(tmp_path: Path) -> None:
    tab = _tab(tmp_path)
    sent = []
    tab._send_rust_message = lambda payload: sent.append(payload)
    try:
        tab.standalone_native_host_frame.focus_requested.emit()
        assert len(sent) == 1
        assert sent[0]["event"] == "focus_request"
        assert sent[0]["request_id"] == 0
    finally:
        tab.request_shutdown()
        tab.close()
        tab.deleteLater()
        QApplication.processEvents()


def test_result_page_actions_and_retry_are_explicit_signals() -> None:
    application = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    emitted: list[str] = []
    host.retry_requested.connect(lambda: emitted.append("retry"))
    host.run_validation_requested.connect(lambda: emitted.append("validate"))
    host.build_mod_requested.connect(lambda: emitted.append("build"))
    host.add_to_archive_browser_requested.connect(lambda: emitted.append("browser"))
    host.continue_modified_mesh_requested.connect(lambda: emitted.append("next_pass"))
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
        "MeshEditorRustResultAddtoArchiveBrowser",
        "MeshEditorRustResultContinueeditingmodifiedmesh",
        "MeshEditorRustResultInstallasOverlay",
        "MeshEditorRustResultReopenEdit",
        "MeshEditorRustResultCloseSession",
    ):
        host.findChild(QPushButton, object_name).click()

    assert emitted == ["retry", "validate", "build", "browser", "next_pass", "install", "reopen", "close"]
    assert host.findChild(QPushButton, "MeshEditorRustResultRestoreLastOverlayInstall") is None
    host.deleteLater()
    application.processEvents()


def test_result_page_groups_and_clickable_help_distinguish_editing_choices() -> None:
    app = QApplication.instance() or QApplication([])
    host = RustMeshEditorHostFrame()
    host.show_result("Accepted")
    host.resize(360, 300)
    host.show()
    app.processEvents()
    try:
        assert [group.title() for group in host.findChildren(QGroupBox)] == [
            "Keep editing", "Save and reuse", "Check or install",
        ]
        resume = host.findChild(QPushButton, "MeshEditorRustResultReopenEdit")
        next_pass = host.findChild(QPushButton, "MeshEditorRustResultContinueeditingmodifiedmesh")
        assert resume.text() == "Resume current edit"
        assert next_pass.text() == "Start next edit pass"
        assert "keeping its fitting setup" in resume.whatsThis()
        assert "Undo/Redo starts again" in resume.whatsThis()
        assert "fitting setup start fresh" in next_pass.whatsThis()
        scroll = host.findChild(QScrollArea, "MeshEditorRustResultScroll")
        assert scroll.widgetResizable()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.verticalScrollBar().maximum() > 0
        actions = [button for button in host.findChildren(QPushButton)
                   if button.objectName().startswith("MeshEditorRustResult")]
        assert len(actions) == 7
        with patch("cdmw.ui.mesh_editor.rust_host.QWhatsThis.showText") as explain:
            for button in actions:
                help_button = host.findChild(QToolButton, button.objectName() + "Help")
                assert help_button is not None and help_button.text() == "?"
                assert help_button.whatsThis() == button.toolTip()
                help_button.click()
                assert explain.call_args.args[1] == button.whatsThis()
        assert explain.call_count == 7
    finally:
        host.deleteLater()
        app.processEvents()


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
