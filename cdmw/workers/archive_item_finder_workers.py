"""Cancellable off-thread thumbnail conversion for the remote Item Finder."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage, QImageReader

from cdmw.services.preview_workflow_service import ensure_dds_display_preview_png


class ArchiveItemThumbnailWorker(QObject):
    """Convert one bounded icon batch and decode detached ``QImage`` values."""

    icon_ready = Signal(int, int, str, object)
    icon_failed = Signal(int, int, str)
    finished = Signal(int)

    def __init__(
        self,
        generation: int,
        sources: Mapping[int, str],
        owner_thread: QThread,
        *,
        max_dimension: int = 120,
    ) -> None:
        super().__init__()
        self.generation = int(generation)
        self.sources = {int(item_id): str(path) for item_id, path in sources.items()}
        self.owner_thread = owner_thread
        self.max_dimension = max(32, int(max_dimension))
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def _decoded_image(self, path: Path) -> QImage:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        source_size = reader.size()
        if source_size.isValid() and max(source_size.width(), source_size.height()) > self.max_dimension:
            reader.setScaledSize(
                source_size.scaled(
                    self.max_dimension,
                    self.max_dimension,
                    Qt.KeepAspectRatio,
                )
            )
        image = reader.read()
        if image.isNull():
            return image
        if max(image.width(), image.height()) > self.max_dimension:
            image = image.scaled(
                self.max_dimension,
                self.max_dimension,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        return image.copy()

    def _batch_dds_previews(self) -> dict[str, Path]:
        jobs = [
            {
                "dds_path": str(path),
                "max_dimension": self.max_dimension,
                "slot_kind": "base",
            }
            for path in (Path(source) for source in self.sources.values())
            if path.suffix.casefold() == ".dds"
        ]
        if not jobs or self.stop_event.is_set():
            return {}
        try:
            from cdmw.core.temp_cache import ITEM_ICON_PREVIEW_CACHE_DIRNAME
            from cdmw.core.texture_native import ensure_directxtex_dds_preview_pngs

            return ensure_directxtex_dds_preview_pngs(
                jobs,
                cache_dirname=ITEM_ICON_PREVIEW_CACHE_DIRNAME,
                stop_event=self.stop_event,
            )
        except Exception:
            return {}

    @Slot()
    def run(self) -> None:
        try:
            batch_previews = self._batch_dds_previews()
            for item_id, source in self.sources.items():
                if self.stop_event.is_set():
                    break
                try:
                    source_path = Path(source).expanduser().resolve()
                    preview_path = source_path
                    if source_path.suffix.casefold() == ".dds":
                        preview_path = batch_previews.get(str(source_path)) or ensure_dds_display_preview_png(
                            source_path,
                            max_dimension=self.max_dimension,
                            slot_kind="base",
                            stop_event=self.stop_event,
                        )
                    if not preview_path.is_file():
                        raise ValueError("Converted thumbnail was not published.")
                    image = self._decoded_image(preview_path)
                    if image.isNull():
                        raise ValueError("Converted thumbnail could not be decoded.")
                    if self.stop_event.is_set():
                        break
                    self.icon_ready.emit(
                        self.generation,
                        item_id,
                        str(preview_path),
                        image,
                    )
                except Exception as exc:
                    if not self.stop_event.is_set():
                        self.icon_failed.emit(self.generation, item_id, str(exc))
        finally:
            self.moveToThread(self.owner_thread)
            self.finished.emit(self.generation)


__all__ = ["ArchiveItemThumbnailWorker"]
