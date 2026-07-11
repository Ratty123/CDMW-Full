"""Bounded, cancellable directory scans for UI workflows."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import RunCancelled


@dataclass(frozen=True, slots=True)
class DirectoryScanRequest:
    request_id: int
    root: Path
    suffixes: tuple[str, ...] = ()
    max_results: int = 100_000
    max_entries: int = 2_000_000


@dataclass(frozen=True, slots=True)
class DirectoryScanResult:
    paths: tuple[Path, ...]
    entries_visited: int
    skipped_directories: int
    truncated: bool


def scan_directory_files(
    request: DirectoryScanRequest,
    *,
    stop_event: threading.Event | None = None,
) -> DirectoryScanResult:
    """Scan without following directory symlinks and enforce hard ceilings."""

    root = Path(request.root).expanduser()
    suffixes = tuple(
        suffix.casefold() if str(suffix).startswith(".") else f".{str(suffix).casefold()}"
        for suffix in request.suffixes
        if str(suffix).strip()
    )
    max_results = max(1, int(request.max_results))
    max_entries = max(1, int(request.max_entries))
    if not root.is_dir():
        raise OSError(f"Directory does not exist or is not readable: {root}")

    paths: list[Path] = []
    pending = [root]
    visited = 0
    skipped = 0
    truncated = False
    while pending:
        raise_if_cancelled(stop_event, "Directory scan cancelled.")
        directory = pending.pop()
        try:
            iterator = os.scandir(directory)
        except OSError:
            skipped += 1
            continue
        with iterator:
            for entry in iterator:
                if not (visited & 1023):
                    raise_if_cancelled(stop_event, "Directory scan cancelled.")
                visited += 1
                if visited > max_entries:
                    truncated = True
                    pending.clear()
                    break
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                name = entry.name.casefold()
                if suffixes and not any(name.endswith(suffix) for suffix in suffixes):
                    continue
                paths.append(Path(entry.path))
                if len(paths) >= max_results:
                    truncated = True
                    pending.clear()
                    break
        if truncated:
            break
    paths.sort(key=lambda path: str(path).casefold())
    return DirectoryScanResult(tuple(paths), visited, skipped, truncated)


class DirectoryScanWorker(QObject):
    completed = Signal(int, object)
    cancelled = Signal(int)
    error = Signal(int, str)
    finished = Signal(int)

    def __init__(self, request: DirectoryScanRequest) -> None:
        super().__init__()
        self.request = request
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    request_stop = stop

    @Slot()
    def run(self) -> None:
        request_id = int(self.request.request_id)
        try:
            self.completed.emit(
                request_id,
                scan_directory_files(self.request, stop_event=self.stop_event),
            )
        except RunCancelled:
            self.cancelled.emit(request_id)
        except Exception as exc:
            self.error.emit(request_id, str(exc))
        finally:
            self.finished.emit(request_id)


__all__ = [
    "DirectoryScanRequest",
    "DirectoryScanResult",
    "DirectoryScanWorker",
    "scan_directory_files",
]
