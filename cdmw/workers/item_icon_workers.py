"""Cancellable Item Icon library and preview workers."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from PySide6.QtCore import QObject, QSize, Qt, Signal, Slot
from PySide6.QtGui import QImage, QImageReader

from cdmw.core.atomic_file import (
    atomic_binary_writer,
    atomic_publish_files,
    atomic_write_bytes,
    atomic_write_text,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.library.item_icons import (
    ITEM_ICON_SOURCE_EXTENSIONS,
    ItemIconBuildResult,
    ItemIconLibraryRecord,
    ItemIconLooseModPatchResult,
    ItemIconOverrideSpec,
    ItemIconTemplateInfo,
)
from cdmw.models import RunCancelled
from cdmw.services.item_icon_service import ItemIconService


_ITEM_ICON_SERVICE = ItemIconService()


def scan_item_icon_library(
    roots: tuple[Path, ...],
    *,
    index_path: Path,
    edited_root: Path,
    stop_event: Optional[threading.Event] = None,
) -> tuple[ItemIconLibraryRecord, ...]:
    return _ITEM_ICON_SERVICE.refresh_library(
        roots,
        index_path=index_path,
        edited_root=edited_root,
        stop_event=stop_event,
    )


def update_item_icon_library_record_metadata(
    index_path: Path,
    record_path: Path,
    **kwargs: object,
) -> None:
    _ITEM_ICON_SERVICE.save_record_metadata(index_path, record_path, **kwargs)


def build_item_icon_source_preview_png(source_path: Path, **kwargs: object) -> Path:
    return _ITEM_ICON_SERVICE.build_source_preview(source_path, **kwargs)


def build_item_icon_fit_pad_preview(
    source_path: Path,
    **kwargs: object,
) -> tuple[Path, ItemIconTemplateInfo, tuple[int, int], tuple[str, ...]]:
    return _ITEM_ICON_SERVICE.build_fit_preview(source_path, **kwargs)


def build_item_icon_payload(spec: ItemIconOverrideSpec, **kwargs: object) -> ItemIconBuildResult:
    return _ITEM_ICON_SERVICE.build_payload(spec, **kwargs)


def patch_existing_loose_mod_with_item_icon(
    source_root: Path,
    **kwargs: object,
) -> ItemIconLooseModPatchResult:
    return _ITEM_ICON_SERVICE.patch_existing_package(source_root, **kwargs)


@dataclass(frozen=True, slots=True)
class ItemIconLibraryScanRequest:
    request_id: int
    roots: tuple[Path, ...]
    library_root: Path
    edited_root: Path
    preview_root: Path
    index_path: Path
    selected_path: Optional[Path]
    show_status: bool


@dataclass(frozen=True, slots=True)
class ItemIconLibraryScanResult:
    records: tuple[ItemIconLibraryRecord, ...]


@dataclass(frozen=True, slots=True)
class ItemIconMetadataSaveRequest:
    request_id: int
    index_path: Path
    record_path: Path
    tags: tuple[str, ...]
    notes: str
    favorite: bool


@dataclass(frozen=True, slots=True)
class ItemIconLibraryMutationRequest:
    request_id: int
    action: str
    source_path: Path
    destination_path: Optional[Path]
    edited_root: Path
    index_path: Path
    roots: tuple[Path, ...]
    tags: tuple[str, ...] = ()
    notes: str = ""
    favorite: bool = False
    select: bool = False


@dataclass(frozen=True, slots=True)
class ItemIconLibraryMutationResult:
    action: str
    stored_path: Path
    record: Optional[ItemIconLibraryRecord]


@dataclass(frozen=True, slots=True)
class ItemIconSourcePreviewRequest:
    request_id: int
    source_path: Path
    output_dir: Path
    decode_size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ItemIconSourcePreviewResult:
    source_path: Path
    image: QImage


@dataclass(frozen=True, slots=True)
class ItemIconFinalPreviewRequest:
    request_id: int
    source_path: Path
    target_entry: object
    target_path: str
    output_path: Path
    background_mode: str
    decode_size: tuple[int, int]
    resolve_target_template_path: Callable[[object], Path]
    show_errors: bool


@dataclass(frozen=True, slots=True)
class ItemIconFinalPreviewResult:
    image: QImage
    target_info: ItemIconTemplateInfo
    source_dimensions: tuple[int, int]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ItemIconOutputRequest:
    request_id: int
    action: str
    spec: ItemIconOverrideSpec
    destination: Path
    resolve_target_template_path: Callable[[object], Path]


@dataclass(frozen=True, slots=True)
class ItemIconOutputResult:
    action: str
    destination: Path
    payload: ItemIconBuildResult
    patch_result: Optional[ItemIconLooseModPatchResult] = None


def _decode_preview_image(
    image_path: Path,
    decode_size: tuple[int, int],
    stop_event: threading.Event,
) -> QImage:
    raise_if_cancelled(stop_event, "Item icon preview decode cancelled.")
    reader = QImageReader(str(image_path))
    reader.setAutoTransform(True)
    source_size = reader.size()
    requested = QSize(max(1, int(decode_size[0])), max(1, int(decode_size[1])))
    if (
        source_size.isValid()
        and source_size.width() > requested.width() * 2
        and source_size.height() > requested.height() * 2
    ):
        reader.setScaledSize(source_size.scaled(requested, Qt.AspectRatioMode.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError(reader.errorString() or f"Qt could not read this image for preview: {image_path}")
    raise_if_cancelled(stop_event, "Item icon preview decode cancelled.")
    return image


def _item_icon_path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve()).casefold()
    except OSError:
        return str(path.expanduser()).casefold()


def _item_icon_record_payload(record: ItemIconLibraryRecord) -> dict[str, object]:
    return {
        "path": str(record.path),
        "root_path": str(record.root_path),
        "relative_path": record.relative_path,
        "file_size": int(record.file_size),
        "mtime_ns": int(record.mtime_ns),
        "width": int(record.width),
        "height": int(record.height),
        "tags": list(record.tags),
        "notes": record.notes,
        "favorite": bool(record.favorite),
        "source_kind": record.source_kind,
        "warning": record.warning,
    }


def _write_item_icon_index_stage(
    request: ItemIconLibraryMutationRequest,
    output_path: Path,
    *,
    record: Optional[ItemIconLibraryRecord],
    remove_path: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    raise_if_cancelled(stop_event, "Item icon library mutation cancelled.")
    loaded = _ITEM_ICON_SERVICE.load_library_index(request.index_path)
    raw_records = loaded.get("records")
    records = dict(raw_records) if isinstance(raw_records, dict) else {}
    if remove_path is not None:
        records.pop(_item_icon_path_key(remove_path), None)
    if record is not None:
        records[_item_icon_path_key(record.path)] = _item_icon_record_payload(record)
    payload = {
        "version": 1,
        "roots": [str(root) for root in request.roots],
        "records": records,
    }
    raise_if_cancelled(stop_event, "Item icon library mutation cancelled.")
    atomic_write_text(output_path, json.dumps(payload, indent=2, sort_keys=True))


def _copy_item_icon_source_to_stage(
    source_path: Path,
    staged_path: Path,
    stop_event: Optional[threading.Event],
) -> None:
    with source_path.open("rb") as source, atomic_binary_writer(staged_path) as destination:
        while True:
            raise_if_cancelled(stop_event, "Item icon source copy cancelled.")
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            destination.write(chunk)
    raise_if_cancelled(stop_event, "Item icon source copy cancelled.")
    shutil.copystat(source_path, staged_path)


def _unlink_item_icon_backup(path: Path) -> None:
    path.unlink(missing_ok=True)


def _run_item_icon_library_mutation(
    request: ItemIconLibraryMutationRequest,
    stop_event: threading.Event,
) -> ItemIconLibraryMutationResult:
    action = request.action
    source = request.source_path.expanduser()
    if action not in {"delete", "import", "register"}:
        raise ValueError(f"Unsupported item icon library mutation: {action}")
    if not source.is_file():
        raise FileNotFoundError(f"Item icon source was not found: {source}")
    request.index_path.parent.mkdir(parents=True, exist_ok=True)
    raise_if_cancelled(stop_event, "Item icon library mutation cancelled.")

    if action == "delete":
        with tempfile.TemporaryDirectory(prefix=".cdmw_item_icon_delete_", dir=request.index_path.parent) as temp_dir:
            staged_index = Path(temp_dir) / request.index_path.name
            _write_item_icon_index_stage(
                request,
                staged_index,
                record=None,
                remove_path=source,
                stop_event=stop_event,
            )
            raise_if_cancelled(stop_event, "Item icon source delete cancelled.")
            backup = source.with_name(f".{source.name}.{uuid4().hex}.delete")
            os.replace(source, backup)
            try:
                atomic_publish_files({staged_index: request.index_path})
            except Exception:
                os.replace(backup, source)
                raise
            _unlink_item_icon_backup(backup)
        return ItemIconLibraryMutationResult(action=action, stored_path=source, record=None)

    destination = (request.destination_path or source).expanduser()
    if source.suffix.lower() not in ITEM_ICON_SOURCE_EXTENSIONS:
        raise ValueError(f"Unsupported edited item icon source format: {source.suffix}")
    same_path = _item_icon_path_key(source) == _item_icon_path_key(destination)
    if not same_path and destination.exists():
        raise FileExistsError(f"Item icon library destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cdmw_item_icon_store_", dir=request.index_path.parent) as temp_dir:
        stage_root = Path(temp_dir)
        staged_index = stage_root / request.index_path.name
        inspected_path = source
        publications: dict[Path, Path] = {}
        if not same_path:
            staged_source = stage_root / destination.name
            _copy_item_icon_source_to_stage(source, staged_source, stop_event)
            inspected_path = staged_source
            publications[staged_source] = destination
        record = _ITEM_ICON_SERVICE.inspect_library_source(
            inspected_path,
            record_path=destination,
            root_path=request.edited_root,
            tags=request.tags,
            notes=request.notes,
            favorite=request.favorite,
            source_kind="edited",
            stop_event=stop_event,
        )
        _write_item_icon_index_stage(
            request,
            staged_index,
            record=record,
            stop_event=stop_event,
        )
        publications[staged_index] = request.index_path
        raise_if_cancelled(stop_event, "Item icon library mutation cancelled.")
        atomic_publish_files(publications)
    return ItemIconLibraryMutationResult(action=action, stored_path=destination, record=record)


class _CancellableItemIconWorker(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.stop_event = threading.Event()

    @Slot()
    def stop(self) -> None:
        self.stop_event.set()


class ItemIconLibraryScanWorker(_CancellableItemIconWorker):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: ItemIconLibraryScanRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            raise_if_cancelled(self.stop_event, "Item icon library scan cancelled.")
            request.library_root.mkdir(parents=True, exist_ok=True)
            request.edited_root.mkdir(parents=True, exist_ok=True)
            request.preview_root.mkdir(parents=True, exist_ok=True)
            records = scan_item_icon_library(
                request.roots,
                index_path=request.index_path,
                edited_root=request.edited_root,
                stop_event=self.stop_event,
            )
            raise_if_cancelled(self.stop_event, "Item icon library scan cancelled.")
            self.completed.emit(request.request_id, ItemIconLibraryScanResult(records=records))
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


class ItemIconMetadataSaveWorker(_CancellableItemIconWorker):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: ItemIconMetadataSaveRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            update_item_icon_library_record_metadata(
                request.index_path,
                request.record_path,
                tags=request.tags,
                notes=request.notes,
                favorite=request.favorite,
                stop_event=self.stop_event,
            )
            raise_if_cancelled(self.stop_event, "Item icon metadata save cancelled.")
            self.completed.emit(request.request_id, request)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


class ItemIconLibraryMutationWorker(_CancellableItemIconWorker):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: ItemIconLibraryMutationRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            result = _run_item_icon_library_mutation(request, self.stop_event)
            self.completed.emit(request.request_id, result)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


class ItemIconSourcePreviewWorker(_CancellableItemIconWorker):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: ItemIconSourcePreviewRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            preview_path = build_item_icon_source_preview_png(
                request.source_path,
                output_dir=request.output_dir,
                stop_event=self.stop_event,
            )
            image = _decode_preview_image(preview_path, request.decode_size, self.stop_event)
            self.completed.emit(
                request.request_id,
                ItemIconSourcePreviewResult(source_path=request.source_path, image=image),
            )
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


class ItemIconFinalPreviewWorker(_CancellableItemIconWorker):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: ItemIconFinalPreviewRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            raise_if_cancelled(self.stop_event, "Item icon final preview cancelled.")
            template_path = Path(request.resolve_target_template_path(request.target_entry))
            raise_if_cancelled(self.stop_event, "Item icon final preview cancelled.")
            preview_path, target_info, source_dimensions, warnings = build_item_icon_fit_pad_preview(
                request.source_path,
                target_path=request.target_path,
                target_template_path=template_path,
                output_path=request.output_path,
                background_mode=request.background_mode,
                stop_event=self.stop_event,
            )
            image = _decode_preview_image(preview_path, request.decode_size, self.stop_event)
            self.completed.emit(
                request.request_id,
                ItemIconFinalPreviewResult(
                    image=image,
                    target_info=target_info,
                    source_dimensions=source_dimensions,
                    warnings=warnings,
                ),
            )
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


class ItemIconOutputWorker(_CancellableItemIconWorker):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request: ItemIconOutputRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        request = self.request
        try:
            if request.action not in {"export", "patch"}:
                raise ValueError(f"Unsupported item icon output action: {request.action}")
            raise_if_cancelled(self.stop_event, "Item icon output cancelled.")
            template_path = Path(request.resolve_target_template_path(request.spec.target_entry))
            payload = build_item_icon_payload(
                request.spec,
                target_template_path=template_path,
                stop_event=self.stop_event,
            )
            raise_if_cancelled(self.stop_event, "Item icon output cancelled.")
            patch_result: Optional[ItemIconLooseModPatchResult] = None
            if request.action == "export":
                atomic_write_bytes(request.destination, payload.payload_data)
            else:
                patch_result = patch_existing_loose_mod_with_item_icon(
                    request.destination,
                    target_path=payload.target_path,
                    payload_data=payload.payload_data,
                    target_entry=request.spec.target_entry,
                    stop_event=self.stop_event,
                )
            self.completed.emit(
                request.request_id,
                ItemIconOutputResult(
                    action=request.action,
                    destination=request.destination,
                    payload=payload,
                    patch_result=patch_result,
                ),
            )
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(request.request_id, str(exc))
        finally:
            self.finished.emit()


__all__ = [
    "ItemIconFinalPreviewRequest",
    "ItemIconFinalPreviewResult",
    "ItemIconFinalPreviewWorker",
    "ItemIconLibraryScanRequest",
    "ItemIconLibraryScanResult",
    "ItemIconLibraryScanWorker",
    "ItemIconLibraryMutationRequest",
    "ItemIconLibraryMutationResult",
    "ItemIconLibraryMutationWorker",
    "ItemIconMetadataSaveRequest",
    "ItemIconMetadataSaveWorker",
    "ItemIconOutputRequest",
    "ItemIconOutputResult",
    "ItemIconOutputWorker",
    "ItemIconSourcePreviewRequest",
    "ItemIconSourcePreviewResult",
    "ItemIconSourcePreviewWorker",
]
