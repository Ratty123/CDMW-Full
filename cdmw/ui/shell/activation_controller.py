"""Single-instance activation request handling for the shell."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from cdmw.app.activation import existing_instance_activation_request_path
from cdmw.constants import APP_TITLE


class ActivationController:
    """Composed activation owner with compatibility forwarding through its window."""

    def __init__(self, window: object) -> None:
        self.window = window

    def initialize_polling(self) -> None:
        ActivationControllerMixin._initialize_existing_instance_activation_polling(self.window)

    def configure_system_tray_icon(self, app_icon: QIcon) -> None:
        ActivationControllerMixin._configure_system_tray_icon(self.window, app_icon)

    def handle_system_tray_activated(self, reason: object) -> None:
        ActivationControllerMixin._handle_system_tray_activated(self.window, reason)

    def present_main_window(self, reason: str = "") -> None:
        ActivationControllerMixin._present_main_window(self.window, reason)

    def poll_existing_instance_activation_request(self) -> None:
        ActivationControllerMixin._poll_existing_instance_activation_request(self.window)


class ActivationControllerMixin:
    """Tray presentation and second-launch activation behavior for the shell window."""

    def _initialize_existing_instance_activation_polling(self) -> None:
        self._external_activation_last_seen = 0.0
        try:
            self._external_activation_last_seen = float(existing_instance_activation_request_path().stat().st_mtime)
        except OSError:
            pass
        self._external_activation_timer = QTimer(self)
        self._external_activation_timer.setInterval(500)
        self._external_activation_timer.timeout.connect(self._poll_existing_instance_activation_request)
        self._external_activation_timer.start()

    def _configure_system_tray_icon(self, app_icon: QIcon) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(app_icon)
        if icon.isNull():
            icon = QIcon(self.windowIcon())
        if icon.isNull():
            return
        tray_menu = QMenu(self)
        show_action = tray_menu.addAction("Show Crimson Desert Mod Workbench")
        show_action.triggered.connect(lambda _checked=False: self._present_main_window("tray_menu_show"))
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(lambda _checked=False: self.close())
        tray_icon = QSystemTrayIcon(icon, self)
        tray_icon.setToolTip(APP_TITLE)
        tray_icon.setContextMenu(tray_menu)
        tray_icon.activated.connect(self._handle_system_tray_activated)
        tray_icon.show()
        self.app_tray_menu = tray_menu
        self.app_tray_icon = tray_icon

    def _handle_system_tray_activated(self, reason: object) -> None:
        trigger = getattr(QSystemTrayIcon.ActivationReason, "Trigger", None)
        double_click = getattr(QSystemTrayIcon.ActivationReason, "DoubleClick", None)
        if reason in {trigger, double_click}:
            self._present_main_window("tray_icon")

    def _present_main_window(self, reason: str = "") -> None:
        if bool(getattr(self, "_close_after_workers_requested", False)):
            return
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        try:
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        except Exception:
            pass
        try:
            self.raise_()
            self.activateWindow()
            QApplication.alert(self, 2500)
        except Exception:
            pass
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder("main_window_present_requested", reason=str(reason or "unknown"))

    def _poll_existing_instance_activation_request(self) -> None:
        request_path = existing_instance_activation_request_path()
        try:
            stat_result = request_path.stat()
        except OSError:
            return
        request_seen = float(getattr(stat_result, "st_mtime", 0.0) or 0.0)
        if request_seen <= float(getattr(self, "_external_activation_last_seen", 0.0) or 0.0):
            return
        try:
            payload = json.loads(request_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        self._external_activation_last_seen = request_seen
        try:
            request_path.unlink()
        except OSError:
            pass
        if isinstance(payload, Mapping):
            try:
                if int(payload.get("pid", 0) or 0) == os.getpid():
                    return
            except (TypeError, ValueError):
                pass
        self._present_main_window("second_launch")


__all__ = ["ActivationController", "ActivationControllerMixin"]
