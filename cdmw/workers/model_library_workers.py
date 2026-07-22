"""Qt workers for Model Library background tasks."""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QImage

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.library.models import is_importable_model_path
from cdmw.services.model_library_service import ModelLibraryService


@dataclass(frozen=True, slots=True)
class ModelLibraryImportPathRequest:
    kind: str
    import_path: str = ""
    archive_path: str = ""
    source_path: str = ""
    asset_dir: str = ""
    uid: str = ""
    download_root: str = ""
    candidate_filenames: tuple[str, ...] = ()
    selected_member: str = ""


@dataclass(frozen=True, slots=True)
class ModelLibraryImportPathResult:
    import_path: Optional[Path]
    archive_path: Optional[Path] = None
    asset_dir: Optional[Path] = None
    candidate_members: tuple[str, ...] = ()
    selected_member: str = ""


@dataclass(frozen=True, slots=True)
class ModelLibraryIconOutputRequest:
    request_id: int
    image: QImage
    output_dir: Path
    output_stem: str
    square_crop: bool
    size: int = 512


@dataclass(frozen=True, slots=True)
class ModelLibraryIconOutputResult:
    request_id: int
    output_path: Path
    square_crop: bool


def prepare_model_library_preview_icon(image: QImage, *, size: int = 512) -> QImage:
    """Format a detached preview snapshot without touching a QWidget."""

    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise ValueError("Model preview framebuffer is empty.")
    output_size = max(1, int(size))
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    scaled = source.scaled(
        output_size,
        output_size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - output_size) // 2)
    y = max(0, (scaled.height() - output_size) // 2)
    return scaled.copy(x, y, min(output_size, scaled.width()), min(output_size, scaled.height()))


def write_model_library_preview_icon(
    request: ModelLibraryIconOutputRequest,
    *,
    stop_event: Optional[threading.Event] = None,
) -> ModelLibraryIconOutputResult:
    """Encode and atomically publish one collision-safe generated icon."""

    raise_if_cancelled(stop_event, "Model Library icon output cancelled.")
    output_dir = Path(request.output_dir)
    output_stem = str(request.output_stem or "").strip()
    if not output_stem or Path(output_stem).name != output_stem:
        raise ValueError("Generated icon output stem is invalid.")
    output_dir.mkdir(parents=True, exist_ok=True)
    image = (
        prepare_model_library_preview_icon(request.image, size=request.size)
        if request.square_crop
        else request.image.copy()
    )
    raise_if_cancelled(stop_event, "Model Library icon output cancelled.")
    staging = output_dir / f".{output_stem}.{uuid.uuid4().hex}.cdmw-tmp.png"
    published: Optional[Path] = None
    try:
        if not image.save(str(staging), "PNG"):
            raise OSError(f"Could not encode generated icon {staging.name}.")
        with staging.open("r+b") as handle:
            os.fsync(handle.fileno())
        raise_if_cancelled(stop_event, "Model Library icon output cancelled.")
        counter = 1
        while True:
            suffix = "" if counter == 1 else f"_{counter}"
            candidate = output_dir / f"{output_stem}{suffix}.png"
            try:
                if os.name == "nt":
                    staging.rename(candidate)
                else:
                    os.link(staging, candidate)
            except FileExistsError:
                counter += 1
                continue
            published = candidate
            break
        try:
            raise_if_cancelled(stop_event, "Model Library icon output cancelled.")
        except Exception:
            published.unlink(missing_ok=True)
            published = None
            raise
        return ModelLibraryIconOutputResult(
            request_id=int(request.request_id),
            output_path=published,
            square_crop=bool(request.square_crop),
        )
    finally:
        staging.unlink(missing_ok=True)


def resolve_model_library_import_path(
    request: ModelLibraryImportPathRequest,
    *,
    stop_event: Optional[threading.Event] = None,
    service: Optional[ModelLibraryService] = None,
) -> ModelLibraryImportPathResult:
    """Resolve/extract one immutable Model Library selection off the UI thread."""

    raise_if_cancelled(stop_event, "Model Library import resolution cancelled.")
    model_service = service or ModelLibraryService()
    existing_import = Path(request.import_path).expanduser() if request.import_path else None
    if existing_import is not None and existing_import.is_file() and is_importable_model_path(existing_import):
        return ModelLibraryImportPathResult(import_path=existing_import)

    if request.kind != "mirror":
        source = Path(request.source_path).expanduser() if request.source_path else None
        if source is None or not source.is_file():
            return ModelLibraryImportPathResult(import_path=None)
        resolved, candidates = _resolve_model_library_source(
            model_service,
            source,
            selected_member=request.selected_member,
            stop_event=stop_event,
        )
        return ModelLibraryImportPathResult(
            import_path=resolved,
            archive_path=source if source.suffix.lower() == ".zip" else None,
            candidate_members=candidates,
            selected_member=request.selected_member if resolved is not None else "",
        )

    asset_dir = _existing_model_library_asset_dir(request, stop_event=stop_event)
    archive_path = _existing_model_library_archive_path(request, asset_dir, stop_event=stop_event)
    if archive_path is not None:
        extract_root = asset_dir / "gltf" if asset_dir is not None and archive_path.suffix.lower() == ".zip" else None
        resolved, candidates = _resolve_model_library_source(
            model_service,
            archive_path,
            extract_root=extract_root,
            selected_member=request.selected_member,
            stop_event=stop_event,
        )
        if resolved is not None:
            return ModelLibraryImportPathResult(
                resolved,
                archive_path,
                asset_dir,
                selected_member=request.selected_member,
            )
        if candidates:
            return ModelLibraryImportPathResult(None, archive_path, asset_dir, candidates)
    if asset_dir is not None:
        resolved = model_service.resolve_importable_model(asset_dir, stop_event=stop_event)
        if resolved is not None:
            return ModelLibraryImportPathResult(resolved, archive_path, asset_dir)
    return ModelLibraryImportPathResult(None, archive_path, asset_dir)


def _resolve_model_library_source(
    service: ModelLibraryService,
    source: Path,
    *,
    extract_root: Optional[Path] = None,
    selected_member: str = "",
    stop_event: Optional[threading.Event] = None,
) -> tuple[Optional[Path], tuple[str, ...]]:
    members = (
        service.importable_model_members(source, stop_event=stop_event)
        if source.suffix.lower() == ".zip"
        else ()
    )
    if len(members) > 1 and not str(selected_member or "").strip():
        return None, members
    return (
        service.resolve_importable_model(
            source,
            extract_root=extract_root,
            selected_member=selected_member,
            stop_event=stop_event,
        ),
        (),
    )


def _existing_model_library_asset_dir(
    request: ModelLibraryImportPathRequest,
    *,
    stop_event: Optional[threading.Event],
) -> Optional[Path]:
    if request.asset_dir:
        candidate = Path(request.asset_dir).expanduser()
        if candidate.is_dir():
            return candidate
    if not request.uid or not request.download_root:
        return None
    root = Path(request.download_root).expanduser()
    if not root.is_dir():
        return None
    matches: list[tuple[float, Path]] = []
    wanted_suffix = f"-{request.uid}".casefold()
    for candidate in root.iterdir():
        raise_if_cancelled(stop_event, "Model Library import resolution cancelled.")
        if not candidate.name.casefold().endswith(wanted_suffix) or not candidate.is_dir():
            continue
        try:
            modified_at = candidate.stat().st_mtime
        except OSError:
            modified_at = 0.0
        matches.append((modified_at, candidate))
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1] if matches else None


def _existing_model_library_archive_path(
    request: ModelLibraryImportPathRequest,
    asset_dir: Optional[Path],
    *,
    stop_event: Optional[threading.Event],
) -> Optional[Path]:
    if request.archive_path:
        candidate = Path(request.archive_path).expanduser()
        if candidate.is_file():
            return candidate
    if asset_dir is None or not asset_dir.is_dir():
        return None
    for filename in request.candidate_filenames:
        raise_if_cancelled(stop_event, "Model Library import resolution cancelled.")
        candidate = asset_dir / Path(filename).name
        if candidate.is_file():
            return candidate
    archives: list[Path] = []
    for candidate in asset_dir.iterdir():
        raise_if_cancelled(stop_event, "Model Library import resolution cancelled.")
        if candidate.is_file() and candidate.suffix.lower() in {".zip", ".glb"}:
            archives.append(candidate)
    archives.sort(key=lambda path: path.name.lower())
    return archives[0] if archives else None


class ModelLibraryTaskWorker(QObject):
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()
    progress = Signal(str)

    def __init__(self, task: Callable[[Callable[[str], None]], object]) -> None:
        super().__init__()
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            result = self.task(lambda message: self._emit(self.progress, str(message)))
            self._emit(self.completed, result)
        except Exception as exc:
            self._emit(self.error, str(exc))
        finally:
            self._emit(self.finished)

    @staticmethod
    def _emit(signal: object, *args: object) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


def _remove_model_library_preview_package_dir(package_dir: Path) -> None:
    try:
        shutil.rmtree(package_dir, ignore_errors=True)
    except OSError:
        pass


def remove_model_library_preview_package_dir(package_dir: Path | str | None) -> threading.Thread | None:
    if package_dir is None:
        return None
    path = Path(package_dir)
    if path.name == "package" and path.parent.name.startswith("cdmw_dotnet_preview_"):
        path = path.parent
    if not path.name.startswith("cdmw_dotnet_preview_"):
        return None
    thread = threading.Thread(
        target=_remove_model_library_preview_package_dir,
        args=(path,),
        name="cdmw-model-library-preview-cleanup",
        daemon=True,
    )
    thread.start()
    return thread


__all__ = [
    "ModelLibraryIconOutputRequest",
    "ModelLibraryIconOutputResult",
    "ModelLibraryImportPathRequest",
    "ModelLibraryImportPathResult",
    "ModelLibraryTaskWorker",
    "prepare_model_library_preview_icon",
    "remove_model_library_preview_package_dir",
    "resolve_model_library_import_path",
    "write_model_library_preview_icon",
]
