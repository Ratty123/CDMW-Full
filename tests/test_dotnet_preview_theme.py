from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.ui.preview.dotnet_host import DotNetPreviewHostFrame


_APP = QApplication.instance() or QApplication([])


class _ThemeController(QObject):
    state_changed = Signal(str, str)
    protocol_event = Signal(object)
    view_state_changed = Signal(object)
    part_pick_result = Signal(object)
    capture_completed = Signal(object)
    renderer_ready = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.capabilities = ("ui_theme_state_v1",)
        self.process_generation = 7
        self.writes: list[dict[str, object]] = []

    def set_ui_localizer(self, _localizer: object) -> None:
        return

    def set_visible(self, _visible: bool) -> None:
        return

    def retry_now(self) -> None:
        return

    def shutdown(self) -> None:
        return

    def _send_json(self, payload: dict[str, object]) -> bool:
        self.writes.append(dict(payload))
        return True


def test_host_sends_the_active_theme_once_per_resident_process() -> None:
    controller = _ThemeController()
    host = DotNetPreviewHostFrame(controller=controller, theme_key="crimson_desert")
    try:
        theme_messages = [item for item in controller.writes if item.get("event") == "ui_theme_state"]
        assert len(theme_messages) == 1
        assert theme_messages[0]["theme_key"] == "crimson_desert"
        assert theme_messages[0]["palette"]["window"] == "#211814"
        assert "#211814" in host._status_panel.styleSheet()

        host.set_theme("light")
        host.set_theme("light")
        theme_messages = [item for item in controller.writes if item.get("event") == "ui_theme_state"]
        assert len(theme_messages) == 2
        assert theme_messages[-1]["palette"]["surface"] == "#ffffff"

        controller.process_generation = 8
        controller.renderer_ready.emit({})
        theme_messages = [item for item in controller.writes if item.get("event") == "ui_theme_state"]
        assert len(theme_messages) == 3
        assert theme_messages[-1]["process_generation"] == 8
    finally:
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_new_preview_host_inherits_the_application_theme_when_the_caller_omits_one() -> None:
    previous_theme_key = _APP.property("_cdmw_theme_key")
    _APP.setProperty("_cdmw_theme_key", "light")
    controller = _ThemeController()
    host = DotNetPreviewHostFrame(controller=controller)
    try:
        assert host._theme_key == "light"
        assert "#f4f6f8" in host._status_panel.styleSheet()
        assert "#eef2f6" in host._resident_banner.styleSheet()
        theme_messages = [item for item in controller.writes if item.get("event") == "ui_theme_state"]
        assert len(theme_messages) == 1
        assert theme_messages[0]["theme_key"] == "light"
    finally:
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        _APP.setProperty("_cdmw_theme_key", previous_theme_key)
