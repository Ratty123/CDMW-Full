"""Best-effort background prewarm task for the resident Rust preview host."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.services.mesh_rust_preview_package import build_rust_preview_prewarm_package


class _DotNetPreviewPrewarmSignals(QObject):
    completed = Signal(object)


class DotNetPreviewPrewarmTask(QRunnable):
    def __init__(self, cache_root: Path, executable: Path | None = None) -> None:
        super().__init__()
        self.cache_root = Path(cache_root)
        self.executable = Path(executable) if executable else None
        self.signals = _DotNetPreviewPrewarmSignals()

    def run(self) -> None:
        """Contain all errors because the global pool may outlive the owning host."""

        started_at = time.perf_counter()
        try:
            package = build_rust_preview_prewarm_package(self.cache_root)
            result = {
                "package": package,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001 - prewarm is best-effort
            result = {
                "package": None,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": str(exc),
            }
        try:
            self.signals.completed.emit(result)
        except RuntimeError:
            return


class DialogPreviewPrewarm(QObject):
    """One hidden spare helper, consumed once by the next dialog host."""

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self._parking = QWidget()
        self._parking.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self._parking.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._parking.resize(64, 64)
        self._controller = None
        self._task = None
        self._closed = False
        self._cache_root: Path | None = None
        self._configured = None
        self._localizer = None
        self._launch_identity = None
        self._launch_configured = ""
        self._refill = QTimer(self)
        self._refill.setSingleShot(True)
        self._refill.timeout.connect(self._prepare)
        application.aboutToQuit.connect(self.shutdown)

    @staticmethod
    def _identity(path: Path | str | None) -> tuple | None:
        if not path:
            return None
        try:
            resolved = Path(path).resolve()
            stat = resolved.stat()
            return (str(resolved).casefold(), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except OSError:
            return None

    @staticmethod
    def _configured_key(path: Path | str | None) -> str:
        return str(Path(path).resolve()).casefold() if path else ""

    def ensure(self, cache_root: Path, configured=None, localizer=None) -> None:
        if self._closed:
            return
        self._cache_root = Path(cache_root)
        self._configured = configured
        self._localizer = localizer
        if self._task is None and self._controller is None:
            self._prepare()

    def _prepare(self) -> None:
        if self._closed or self._task is not None or self._controller is not None or self._cache_root is None:
            return
        task = DotNetPreviewPrewarmTask(self._cache_root)
        task.signals.completed.connect(self._prepared)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _prepared(self, result: object) -> None:
        self._task = None
        if self._closed or not isinstance(result, dict):
            return
        package = result.get("package")
        if package is None:
            return
        from cdmw.ui.preview.dotnet_session import RustPreviewSessionController

        controller = RustPreviewSessionController(
            parent=self, host_hwnd=lambda: int(self._parking.winId()),
            configured_executable=self._configured,
        )
        self._controller = controller
        controller.set_ui_localizer(self._localizer)
        controller.state_changed.connect(self._state_changed)
        if not controller.prewarm(package):
            self._discard()
            return
        self._launch_identity = self._identity(controller._executable)
        self._launch_configured = self._configured_key(self._configured)

    def _state_changed(self, state: str, _message: str) -> None:
        controller = self._controller
        if controller is None or self._closed:
            return
        if state == "prewarmed" and "dialog_prewarm_hold_v1" in controller.capabilities:
            controller.send_correlated("prewarm_hold_request")
        elif state in {"package_error", "failed", "retrying"}:
            self._discard()
        elif state in {"inactive", "closed"} and not controller.is_running:
            self._discard()

    @staticmethod
    def _reparent(controller, parent_hwnd: int) -> bool:
        if sys.platform != "win32":
            return False
        import ctypes
        from ctypes import wintypes

        child = int((controller._renderer_ready_payload or {}).get("child_hwnd", 0))
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.GetParent.restype = wintypes.HWND
        api.GetParent.argtypes = [wintypes.HWND]
        api.SetParent.restype = wintypes.HWND
        api.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        if not child or not parent_hwnd:
            return False
        owner = wintypes.DWORD()
        api.GetWindowThreadProcessId(wintypes.HWND(child), ctypes.byref(owner))
        if owner.value != controller.process_id:
            return False
        api.SetParent(wintypes.HWND(child), wintypes.HWND(parent_hwnd))
        return int(api.GetParent(wintypes.HWND(child)) or 0) == parent_hwnd

    def _discard(self) -> None:
        controller, self._controller = self._controller, None
        if controller is not None:
            controller.state_changed.disconnect(self._state_changed)
            controller.shutdown()
            controller.deleteLater()

    def take(self, *, parent, host_hwnd, profile, configured, terminate_on_close, direct_authoring):
        controller = self._controller
        if self._closed or controller is None or not terminate_on_close:
            return None
        if (
            self._configured_key(configured) != self._launch_configured
            or self._identity(controller._executable) != self._launch_identity
        ):
            self._discard()
            return None
        if "dialog_prewarm_hold_v1" not in controller.capabilities:
            return None
        from cdmw.services.mesh_rust_contract import resolve_rust_mesh_editor, validate_rust_mesh_editor_package

        if validate_rust_mesh_editor_package(resolve_rust_mesh_editor(configured)):
            self._discard()
            return None
        if (not controller._renderer_ready or not controller._session_established
                or not controller.serving_prewarm_placeholder or controller.desired_package_path):
            return None
        if not self._reparent(controller, host_hwnd()):
            self._discard()
            return None
        payload = controller.adopt_prewarmed_host(
            parent=parent, host_hwnd=host_hwnd, profile=profile,
            terminate_on_close=terminate_on_close, direct_authoring=direct_authoring,
        )
        if payload is None:
            return None
        controller.state_changed.disconnect(self._state_changed)
        self._controller = None
        self._refill.start(5_000)
        return controller, payload

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._refill.stop()
        self._discard()
        self._parking.deleteLater()


def ensure_dialog_preview_prewarm(cache_root: Path, configured=None, localizer=None) -> None:
    application = QApplication.instance()
    if application is None:
        return
    pool = getattr(application, "_cdmw_dialog_preview_prewarm", None)
    if pool is None:
        pool = DialogPreviewPrewarm(application)
        application._cdmw_dialog_preview_prewarm = pool
    pool.ensure(cache_root, configured, localizer)


def take_dialog_preview_prewarm(**kwargs):
    application = QApplication.instance()
    pool = getattr(application, "_cdmw_dialog_preview_prewarm", None)
    return pool.take(**kwargs) if pool is not None else None


__all__ = ["DotNetPreviewPrewarmTask", "DialogPreviewPrewarm", "ensure_dialog_preview_prewarm", "take_dialog_preview_prewarm"]
