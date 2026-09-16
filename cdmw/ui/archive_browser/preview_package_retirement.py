"""Retire Archive Preview's transient output after its last reader lets go."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from cdmw.rendering.native_preview_package_cache import native_preview_package_live_paths_guard
from cdmw.ui.shell.close_controller import register_transient_worker_controller
from cdmw.workers.archive_preview_cleanup_worker import ArchivePreviewPackageCleanup
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane


class ArchivePreviewPackageRetirement(QObject):
    def __init__(self, owner: QObject, root: Path) -> None:
        super().__init__(owner)
        self.owner = owner
        self.root = root.resolve()
        self.pending: dict[Path, ArchivePreviewPackageCleanup] = {}
        self.lane = ModelSourceCleanupLane(parent=self)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.collect)
        register_transient_worker_controller(owner.shell, self)

    def track(self, package: Path) -> None:
        package = package.resolve()
        if (package.name != "package" or not package.parent.name.startswith("cdmw_rust_preview_")
                or package.parent.parent != self.root):
            return
        self.pending.setdefault(package, ArchivePreviewPackageCleanup(package, self.root))
        self.timer.start()

    def collect(self) -> None:
        owner = self.owner
        # A worker can hold a snapshot of an evicted memory-cache entry.
        if getattr(owner, "archive_preview_thread", None) is not None:
            return
        controller = getattr(getattr(owner, "archive_d3d11_preview_host", None), "controller", None)
        closing = bool(getattr(owner.shell, "_shutting_down", False))
        pending_exits = set(getattr(controller, "_pending_process_exits", ()))
        if not closing and getattr(controller, "process", None) is not None:
            pending_exits.discard(controller.process_generation)
        if pending_exits:
            return
        referenced = set()
        if not closing:
            results = [
                *getattr(owner, "archive_preview_cache", {}).values(),
                getattr(owner, "current_archive_preview_result", None),
                getattr(owner, "_archive_pending_texture_result", None),
            ]
            for result in results:
                path = str(getattr(result, "dotnet_preview_package_path", "") or "")
                if path:
                    referenced.add(Path(path).resolve())
        for path, job in tuple(self.pending.items()):
            if job.removed:
                self.pending.pop(path)
            elif not job.queued and path not in referenced:
                with native_preview_package_live_paths_guard() as live:
                    leased = any(item.is_relative_to(path.parent) for item in live)
                if leased:
                    continue
                # A skipped cleanup may still be retiring its QThread.
                # Give the retry its own job rather than requeue that owner.
                job = ArchivePreviewPackageCleanup(path, self.root, retired_root=job.retired_root)
                self.pending[path] = job
                job.queued = True
                self.lane.retire(job)
        if not self.pending:
            self.timer.stop()

    def iter_shutdown_workers(self):
        self.collect()
        return self.lane.iter_shutdown_workers()


def track_archive_preview_package(owner: QObject, result: object) -> None:
    path = str(getattr(result, "dotnet_preview_package_path", "") or "")
    if not path or not Path(path).parent.name.startswith("cdmw_rust_preview_"):
        return
    retirement = getattr(owner, "_archive_preview_package_retirement", None)
    if retirement is None:
        retirement = ArchivePreviewPackageRetirement(owner, owner._native_preview_package_cache_root())
        owner._archive_preview_package_retirement = retirement
    retirement.track(Path(path))
