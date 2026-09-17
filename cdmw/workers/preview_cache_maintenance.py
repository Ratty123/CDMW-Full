"""Immutable requests for background preview cache maintenance."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from cdmw.rendering.native_preview_package_cache import (
    clear_native_preview_package_cache_tiers,
    prune_native_preview_package_cache_tiers,
)
from cdmw.services.mesh_workflow_service import clear_pac_xml_profile_index_cache


@dataclass(frozen=True)
class PreviewCacheMaintenanceRequest:
    cache_root: Path
    max_bytes: int = 0
    target_bytes: int = 0
    index_root: Path | None = None
    cleared_count: int = 0


class PreviewCacheMaintenanceJob(QObject):
    finished = Signal(object, str)

    def __init__(self, request: PreviewCacheMaintenanceRequest, parent: QObject) -> None:
        super().__init__(parent)
        self.request = request

    def cleanup(self) -> None:
        error = ""
        try:
            request = self.request
            if request.max_bytes > 0:
                prune_native_preview_package_cache_tiers(
                    request.cache_root, max_bytes=request.max_bytes, target_bytes=request.target_bytes,
                )
            else:
                clear_native_preview_package_cache_tiers(request.cache_root)
            if request.index_root is not None:
                clear_pac_xml_profile_index_cache(request.index_root)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        self.finished.emit(self.request, error)
