"""Lazy optional-helper discovery for the Settings Setup page."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, QThread, QTimer

from cdmw.workers.utility_workers import UtilityWorker


def asset_authoring_helper_status_text(report: Mapping[str, object]) -> str:
    helpers = report.get("helpers", {})
    if not isinstance(helpers, Mapping) or not helpers:
        return "No asset authoring helpers reported."
    lines: list[str] = []
    for helper in helpers.values():
        if not isinstance(helper, Mapping):
            continue
        label = str(helper.get("label") or helper.get("key") or "Helper")
        status = str(helper.get("status") or "unknown")
        version_status = str(helper.get("version_status") or "")
        version = str(helper.get("version") or "").strip()
        if version:
            version_text = version
        elif version_status == "not_checked":
            version_text = "version not checked"
        elif version_status:
            version_text = f"version {version_status}"
        else:
            version_text = "version unavailable"
        path = str(helper.get("path") or "").strip()
        path_text = f" | {path}" if path else ""
        lines.append(f"{label}: {status} | {version_text}{path_text}")
    return "\n".join(lines) if lines else "No asset authoring helpers reported."


class SettingsHelperDiscoveryMixin:
    def _resolve_asset_authoring_service(self):
        service = self.asset_authoring_service
        if service is None:
            factory = self._asset_authoring_service_factory
            if factory is None:
                from cdmw.services.asset_authoring_service import AssetAuthoringService

                service = AssetAuthoringService(settings=self.settings)
            else:
                service = factory()
            self.asset_authoring_service = service
        return service

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._schedule_asset_authoring_helper_discovery()

    def _handle_settings_section_changed(self, _row: int) -> None:
        if self.isVisible():
            self._schedule_asset_authoring_helper_discovery()

    def _current_settings_section_key(self) -> str:
        item = self.section_nav_list.currentItem()
        return str(item.data(Qt.UserRole) or "") if item is not None else ""

    def _schedule_asset_authoring_helper_discovery(self) -> None:
        if (
            self._asset_authoring_helpers_loaded
            or self._asset_authoring_helper_discovery_scheduled
            or self._current_settings_section_key() != "setup"
        ):
            return
        self._asset_authoring_helper_discovery_scheduled = True
        QTimer.singleShot(0, self._ensure_asset_authoring_helper_status_loaded)

    def _ensure_asset_authoring_helper_status_loaded(self) -> None:
        self._asset_authoring_helper_discovery_scheduled = False
        if (
            self._asset_authoring_helpers_loaded
            or not self.isVisible()
            or self._current_settings_section_key() != "setup"
        ):
            return
        self._refresh_asset_authoring_helper_status(include_versions=False)

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread | None, object | None], ...]:
        return (("asset_authoring_helper_versions", self._asset_authoring_helper_thread, self._asset_authoring_helper_worker),)

    def request_shutdown(self) -> None:
        worker = self._asset_authoring_helper_worker
        if worker is not None and hasattr(worker, "stop"):
            worker.stop()
        thread = self._asset_authoring_helper_thread
        if thread is not None and thread.isRunning():
            thread.quit()

    def _refresh_asset_authoring_helper_status(self, *, include_versions: bool) -> None:
        self._asset_authoring_helpers_loaded = True
        try:
            report = self._resolve_asset_authoring_service().discovery_report(include_versions=include_versions)
        except Exception as exc:
            self.asset_authoring_helper_status_label.setText(f"Asset authoring helper discovery failed: {exc}")
            return
        self._apply_asset_authoring_helper_report(report)

    def _start_asset_authoring_helper_version_refresh(self) -> None:
        self._asset_authoring_helpers_loaded = True
        thread = self._asset_authoring_helper_thread
        if thread is not None and thread.isRunning():
            return
        self.asset_authoring_helper_refresh_button.setEnabled(False)
        self.asset_authoring_helper_status_label.setText("Checking asset authoring helper versions...")
        thread = QThread(self)
        worker = UtilityWorker(
            lambda _log: self._resolve_asset_authoring_service().discovery_report(include_versions=True)
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_asset_authoring_helper_report, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self._handle_asset_authoring_helper_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._finish_asset_authoring_helper_version_refresh(thread, worker))
        self._asset_authoring_helper_thread = thread
        self._asset_authoring_helper_worker = worker
        thread.start(QThread.LowPriority)

    def _handle_asset_authoring_helper_report(self, report: object) -> None:
        if isinstance(report, Mapping):
            self._apply_asset_authoring_helper_report(report)
            return
        self.asset_authoring_helper_status_label.setText("Asset authoring helper discovery returned an invalid report.")

    def _handle_asset_authoring_helper_error(self, message: str) -> None:
        self.asset_authoring_helper_status_label.setText(f"Asset authoring helper version check failed: {message}")

    def _finish_asset_authoring_helper_version_refresh(self, thread: QThread, worker: object) -> None:
        if self._asset_authoring_helper_thread is thread:
            self._asset_authoring_helper_thread = None
        if self._asset_authoring_helper_worker is worker:
            self._asset_authoring_helper_worker = None
        self.asset_authoring_helper_refresh_button.setEnabled(True)

    def _apply_asset_authoring_helper_report(self, report: Mapping[str, object]) -> None:
        self.asset_authoring_helper_status_label.setText(asset_authoring_helper_status_text(report))


__all__ = ["SettingsHelperDiscoveryMixin", "asset_authoring_helper_status_text"]
