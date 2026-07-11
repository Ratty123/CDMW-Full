"""Cancellable generated-icon output coordination for Model Library."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QImage

from cdmw.workers.model_library_workers import (
    ModelLibraryIconOutputRequest,
    ModelLibraryIconOutputResult,
    write_model_library_preview_icon,
)


class ModelLibraryIconOutputMixin:
    def _queue_inline_preview_icon_output(
        self,
        image: QImage,
        *,
        payload: dict[str, object],
        loaded_path: Path,
        native_capture: bool,
    ) -> None:
        self._icon_output_request_id += 1
        request_id = self._icon_output_request_id
        stop_event = threading.Event()
        self._stop_event = stop_event
        self._icon_output_active = True
        request = ModelLibraryIconOutputRequest(
            request_id=request_id,
            image=image,
            output_dir=self.catalogue_dir() / "generated_icons",
            output_stem=self._generated_icon_stem(payload, loaded_path),
            square_crop=not native_capture,
        )

        def task(_progress: Callable[[str], None]) -> object:
            return write_model_library_preview_icon(request, stop_event=stop_event)

        def complete(value: object) -> None:
            if (
                request_id != self._icon_output_request_id
                or bool(getattr(self, "_model_library_shutting_down", False))
                or not isinstance(value, ModelLibraryIconOutputResult)
                or value.request_id != request_id
            ):
                return
            selected = self._selected_payload()
            if selected is None or not self._inline_preview_matches_payload(selected):
                return
            prefix = "native D3D11 " if native_capture else ""
            self._set_inline_preview_status(f"Generated {prefix}model preview icon: {value.output_path.name}")
            self.item_icon_source_generated.emit(str(value.output_path), dict(payload))

        def handle_error(message: str) -> None:
            if request_id == self._icon_output_request_id and not bool(
                getattr(self, "_model_library_shutting_down", False)
            ):
                self._set_inline_preview_status(f"Icon capture failed: {message}", error=True)

        self._set_inline_preview_status("Encoding generated model preview icon...")
        self._run_task(
            "Encoding generated model preview icon...",
            task,
            complete,
            error_handler=handle_error,
        )

    def _cancel_stale_icon_output(self) -> None:
        if not bool(getattr(self, "_icon_output_active", False)):
            return
        self._icon_output_request_id += 1
        stop_event = getattr(self, "_stop_event", None)
        if stop_event is not None and hasattr(stop_event, "set"):
            stop_event.set()


__all__ = ["ModelLibraryIconOutputMixin"]
