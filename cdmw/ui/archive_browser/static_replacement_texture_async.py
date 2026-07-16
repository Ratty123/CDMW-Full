"""Latest-wins workers for static-replacement DDS UI preparation."""

from __future__ import annotations

import threading
import tempfile
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from shutil import rmtree

from PySide6.QtCore import QObject, QSize, QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage, QImageReader

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.texture_workflow_service import parse_dds
from cdmw.services.preview_workflow_service import ensure_dds_display_preview_png
from cdmw.models import RunCancelled
from cdmw.ui.shell.close_controller import register_transient_worker_controller
from cdmw.ui.archive_browser.static_replacement_advanced_dds_state import (
    AdvancedDdsOverrideRowScanState,
    advanced_dds_override_row_scan_state,
)
from cdmw.ui.archive_browser.static_replacement_texture_rows import (
    resolve_dds_detail_preview_path,
)


@dataclass(frozen=True, slots=True)
class AdvancedDdsRowScanRequest:
    request_id: int
    suggested_mappings: tuple[object, ...]
    sidecar_bindings: tuple[object, ...]
    texture_sets: tuple[tuple[str, object], ...]
    seen_texture_rows: frozenset[tuple[str, str, str, str]]
    binding_matches_target: Callable[[object, str], bool]
    best_source_for_slot: Callable[..., str]
    texture_is_shared: Callable[[str], bool]


@dataclass(frozen=True, slots=True)
class DdsDetailPreviewRequest:
    request_id: int
    source_path: str
    slot_kind: str


@dataclass(frozen=True, slots=True)
class DdsDetailPreviewResult:
    preview_path: Path | None
    status_text: str
    image: QImage


@dataclass(frozen=True, slots=True)
class MaterialAuthorityResourceRequest:
    request_id: int
    texture_sets: tuple[tuple[str, object], ...]
    material_profile: object
    affected_channels: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class MaterialAuthorityResourceResult:
    request_id: int
    output_root: Path
    bindings: tuple[dict[str, object], ...]
    affected_channels: tuple[str, ...]
    reason: str

    def cleanup(self) -> None:
        rmtree(self.output_root, ignore_errors=True)


class _MaterialAuthorityResourceWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: MaterialAuthorityResourceRequest) -> None:
        super().__init__()
        self.request = request
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        from cdmw.services.material_authority_resource_service import (
            generate_material_authority_resource_bindings,
        )

        request = self.request
        output_root: Path | None = Path(tempfile.mkdtemp(prefix=f"cdmw_material_resources_{request.request_id}_"))
        try:
            bindings = generate_material_authority_resource_bindings(
                request.texture_sets,
                request.material_profile,
                request.affected_channels,
                output_root,
                self.stop_event,
            )
            raise_if_cancelled(self.stop_event, "Material resource generation cancelled.")
            result = MaterialAuthorityResourceResult(
                request.request_id,
                output_root,
                tuple(bindings),
                request.affected_channels,
                request.reason,
            )
            output_root = None
            self.completed.emit(request.request_id, result)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            if output_root is not None:
                rmtree(output_root, ignore_errors=True)
            self.finished.emit()


class _AdvancedDdsRowWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: AdvancedDdsRowScanRequest) -> None:
        super().__init__()
        self.request = request
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            result = advanced_dds_override_row_scan_state(
                request.suggested_mappings,
                request.sidecar_bindings,
                dict(request.texture_sets),
                set(request.seen_texture_rows),
                binding_matches_target=request.binding_matches_target,
                best_source_for_slot=request.best_source_for_slot,
                texture_is_shared=request.texture_is_shared,
                stop_event=self.stop_event,
            )
            raise_if_cancelled(self.stop_event, "Advanced DDS row scan cancelled.")
            self.completed.emit(request.request_id, result)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


class _DdsDetailPreviewWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: DdsDetailPreviewRequest) -> None:
        super().__init__()
        self.request = request
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            preview_path, status_text = resolve_dds_detail_preview_path(
                request.source_path,
                request.slot_kind,
                parse_dds_file=parse_dds,
                ensure_dds_display_preview=ensure_dds_display_preview_png,
                stop_event=self.stop_event,
            )
            raise_if_cancelled(self.stop_event, "DDS detail preview cancelled.")
            image = QImage()
            if preview_path is not None:
                reader = QImageReader(str(preview_path))
                reader.setAutoTransform(True)
                source_size = reader.size()
                if source_size.isValid():
                    reader.setScaledSize(source_size.scaled(QSize(256, 256), Qt.KeepAspectRatio))
                image = reader.read()
                if image.isNull() and not status_text:
                    status_text = reader.errorString() or "Preview image could not be decoded."
            raise_if_cancelled(self.stop_event, "DDS detail preview cancelled.")
            self.completed.emit(
                request.request_id,
                DdsDetailPreviewResult(preview_path, status_text, image),
            )
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


class _LatestWorkerController(QObject):
    def __init__(self, owner: QObject, dialog: QObject, *, lane: str) -> None:
        super().__init__(dialog)
        self._owner = owner
        self._lane = lane
        self._request_id = 0
        self._jobs: dict[int, tuple[QThread, object]] = {}
        self._closed = False
        self._on_complete: Callable[[object], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._on_idle: Callable[[], None] | None = None
        register_transient_worker_controller(owner, self)

    def _launch(
        self,
        worker: object,
        request_id: int,
        *,
        on_complete: Callable[[object], None],
        on_error: Callable[[str], None],
        on_idle: Callable[[], None],
    ) -> None:
        self._on_complete = on_complete
        self._on_error = on_error
        self._on_idle = on_idle
        thread = QThread(self._owner)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_completed, Qt.QueuedConnection)
        worker.error.connect(self._handle_error, Qt.QueuedConnection)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda rid=request_id: self._handle_thread_finished(rid),
            Qt.QueuedConnection,
        )
        self._jobs[request_id] = (thread, worker)
        thread.start(QThread.LowPriority)

    def cancel(self) -> None:
        self._request_id += 1
        for _thread, worker in tuple(self._jobs.values()):
            try:
                worker.stop()
            except RuntimeError:
                # Qt may delete the worker before its queued finished callback
                # removes the Python wrapper from the job table.
                pass

    def request_shutdown(self) -> None:
        self._closed = True
        self.cancel()

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread, object], ...]:
        workers: list[tuple[str, QThread, object]] = []
        for thread, worker in self._jobs.values():
            try:
                if thread.isRunning():
                    workers.append((self._lane, thread, worker))
            except RuntimeError:
                pass
        return tuple(workers)

    @Slot(int, object)
    def _handle_completed(self, request_id: int, result: object) -> None:
        if not self._closed and request_id == self._request_id and self._on_complete is not None:
            self._on_complete(result)
            return
        cleanup = getattr(result, "cleanup", None)
        if callable(cleanup):
            cleanup()

    @Slot(int, str)
    def _handle_error(self, request_id: int, message: str) -> None:
        if not self._closed and request_id == self._request_id and self._on_error is not None:
            self._on_error(message)

    def _handle_thread_finished(self, request_id: int) -> None:
        self._jobs.pop(request_id, None)
        if not self._closed and request_id == self._request_id and self._on_idle is not None:
            self._on_idle()


class StaticReplacementAdvancedDdsController(_LatestWorkerController):
    def __init__(self, owner: QObject, dialog: QObject) -> None:
        super().__init__(owner, dialog, lane="advanced_dds_rows")

    def start(
        self,
        request: AdvancedDdsRowScanRequest,
        *,
        on_complete: Callable[[AdvancedDdsOverrideRowScanState], None],
        on_error: Callable[[str], None],
        on_idle: Callable[[], None],
    ) -> bool:
        if self._closed:
            return False
        self.cancel()
        self._request_id += 1
        current = AdvancedDdsRowScanRequest(
            self._request_id,
            request.suggested_mappings,
            request.sidecar_bindings,
            request.texture_sets,
            request.seen_texture_rows,
            request.binding_matches_target,
            request.best_source_for_slot,
            request.texture_is_shared,
        )
        self._launch(
            _AdvancedDdsRowWorker(current),
            current.request_id,
            on_complete=on_complete,
            on_error=on_error,
            on_idle=on_idle,
        )
        return True


class StaticReplacementDdsDetailController(_LatestWorkerController):
    def __init__(self, owner: QObject, dialog: QObject) -> None:
        super().__init__(owner, dialog, lane="dds_detail_preview")

    def start(
        self,
        *,
        source_path: object,
        slot_kind: object,
        on_complete: Callable[[DdsDetailPreviewResult], None],
        on_error: Callable[[str], None],
        on_idle: Callable[[], None] = lambda: None,
    ) -> bool:
        if self._closed:
            return False
        self.cancel()
        self._request_id += 1
        request = DdsDetailPreviewRequest(
            self._request_id,
            str(source_path or ""),
            str(slot_kind or "base"),
        )
        self._launch(
            _DdsDetailPreviewWorker(request),
            request.request_id,
            on_complete=on_complete,
            on_error=on_error,
            on_idle=on_idle,
        )
        return True


class StaticReplacementMaterialAuthorityResourceController(_LatestWorkerController):
    def __init__(self, owner: QObject, dialog: QObject) -> None:
        super().__init__(owner, dialog, lane="material_authority_resources")
        self._owned_results: list[MaterialAuthorityResourceResult] = []

    def start(
        self,
        *,
        texture_sets: Mapping[str, object] | Sequence[tuple[str, object]],
        material_profile: object,
        affected_channels: Sequence[str],
        reason: str,
        on_complete: Callable[[MaterialAuthorityResourceResult], bool],
        on_error: Callable[[str], None],
        on_idle: Callable[[], None] = lambda: None,
    ) -> bool:
        channels = tuple(dict.fromkeys(str(channel or "").strip().lower() for channel in affected_channels))
        channels = tuple(channel for channel in channels if channel)
        if self._closed or not channels:
            return False
        self.cancel()
        self._request_id += 1
        items = tuple(texture_sets.items()) if isinstance(texture_sets, Mapping) else tuple(texture_sets)
        request = MaterialAuthorityResourceRequest(
            self._request_id,
            tuple((str(name), deepcopy(texture_set)) for name, texture_set in items),
            deepcopy(material_profile),
            channels,
            str(reason or "material_authority_resource_update"),
        )

        def publish(result: MaterialAuthorityResourceResult) -> None:
            if not on_complete(result):
                result.cleanup()
                return
            self._owned_results.append(result)

        self._launch(
            _MaterialAuthorityResourceWorker(request),
            request.request_id,
            on_complete=publish,
            on_error=on_error,
            on_idle=on_idle,
        )
        return True

    def finish(
        self,
        _generation: int,
        _committed: bool,
        bindings: Sequence[Mapping[str, object]],
    ) -> None:
        finished_resources = {
            (
                str(binding.get("resource_id", "") or "").strip(),
                str(binding.get("channel", "") or "").strip().casefold(),
            )
            for binding in bindings
            if isinstance(binding, Mapping)
        }
        retained: list[MaterialAuthorityResourceResult] = []
        for result in self._owned_results:
            result_resources = {
                (
                    str(binding.get("resource_id", "") or "").strip(),
                    str(binding.get("channel", "") or "").strip().casefold(),
                )
                for binding in result.bindings
            }
            if finished_resources.intersection(result_resources):
                result.cleanup()
            else:
                retained.append(result)
        self._owned_results = retained

    def request_shutdown(self) -> None:
        super().request_shutdown()
        for result in self._owned_results:
            result.cleanup()
        self._owned_results.clear()


__all__ = [
    "AdvancedDdsRowScanRequest",
    "DdsDetailPreviewResult",
    "MaterialAuthorityResourceRequest",
    "MaterialAuthorityResourceResult",
    "StaticReplacementAdvancedDdsController",
    "StaticReplacementDdsDetailController",
    "StaticReplacementMaterialAuthorityResourceController",
]
