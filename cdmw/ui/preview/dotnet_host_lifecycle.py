"""Package-lease and QWidget lifecycle behavior for the resident .NET preview host."""

from __future__ import annotations

from pathlib import Path

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

    def hideEvent(self, event: object) -> None:  # type: ignore[override]
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
        self._status_panel.setGeometry(self.rect())
        self._resident_banner.setGeometry(8, 8, max(0, self.width() - 16), 58)
        self._sync_embedded_child_geometry()


__all__ = ["DotNetPreviewHostLifecycleMixin"]
