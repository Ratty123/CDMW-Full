"""Package-lease and QWidget lifecycle behavior for the resident .NET preview host."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QResizeEvent


class DotNetPreviewHostLifecycleMixin:
    def hold_package_lease(self, package_dir: Path) -> bool:
        return self.controller.hold_package_lease(package_dir)

    def release_package_lease(self, package_dir: Path) -> None:
        self.controller.release_package_lease(package_dir)

    def retain_package_lease(self, package_dir: Path) -> None:
        self.controller.retain_package_lease(package_dir)

    def release_package_leases(self) -> None:
        self.controller.release_package_leases()

    hold_native_preview_package_cache_lease = hold_package_lease
    release_native_preview_package_cache_lease = release_package_lease
    retain_native_preview_package_cache_lease = retain_package_lease
    release_native_preview_package_cache_leases = release_package_leases

    def last_mesh_edit_send_metrics(self) -> dict[str, object]:
        return {
            "profile": self._profile.value,
            "process_generation": self.controller.process_generation,
            "package_generation": self.controller.package_generation,
            "applied_package_generation": self.controller.applied_package_generation,
        }

    def showEvent(self, event: object) -> None:  # type: ignore[override]
        super().showEvent(event)  # type: ignore[arg-type]
        self.controller.set_visible(True)
        self._request_child_geometry_sync(force_frame_refresh=True)

    def hideEvent(self, event: object) -> None:  # type: ignore[override]
        self._geometry_sync_timer.stop()
        self.controller.set_visible(False)
        super().hideEvent(event)  # type: ignore[arg-type]

    def closeEvent(self, event: object) -> None:  # type: ignore[override]
        if self._terminate_on_close:
            self.controller.shutdown()
        else:
            self.controller.deactivate()
        super().closeEvent(event)  # type: ignore[arg-type]

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_viewport_geometry()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is getattr(self, "_viewport", None):
            if event.type() == QEvent.Type.WinIdChange:
                self._reembed_helper_in_current_window()
            elif event.type() == QEvent.Type.Resize:
                self._sync_viewport_geometry()
        return super().eventFilter(watched, event)

    def _sync_viewport_geometry(self) -> None:
        viewport = self._viewport.geometry()
        self._status_panel.setGeometry(viewport)
        self._resident_banner.setGeometry(
            viewport.x() + 8, viewport.y() + 8, max(0, viewport.width() - 16), 58
        )
        self._request_child_geometry_sync()

    def _request_child_geometry_sync(self, *, force_frame_refresh: bool = False) -> None:
        self._geometry_force_frame_refresh |= force_frame_refresh
        if self.isVisible():
            self._geometry_sync_timer.start(0)

    def _flush_child_geometry_sync(self) -> None:
        if not self.isVisible():
            return
        force = self._geometry_force_frame_refresh
        self._geometry_force_frame_refresh = False
        self._sync_embedded_child_geometry(force_frame_refresh=force)


__all__ = ["DotNetPreviewHostLifecycleMixin"]
