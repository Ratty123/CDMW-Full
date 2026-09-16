"""Lease-aware retirement of an owned Archive Preview temporary directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from cdmw.rendering.native_preview_package_cache import native_preview_package_live_paths_guard
from cdmw.workers.new_item_cleanup_worker import PreviewPackageCleanup


@dataclass
class ArchivePreviewPackageCleanup:
    package: Path
    root: Path
    queued: bool = False
    removed: bool = False
    retired_root: Path | None = None

    def cleanup(self) -> None:
        try:
            if self.retired_root is None:
                # Detach while leases are stable, then delete outside the lock.
                # Renderer/UI lease acquisition must never wait for rmtree.
                with native_preview_package_live_paths_guard() as live:
                    if any(path.is_relative_to(self.package.parent) for path in live):
                        return
                    wrapper = self.package.parent.resolve()
                    if wrapper.parent != self.root:
                        return
                    if not wrapper.exists():
                        self.removed = True
                        return
                    retired = self.root / f".cdmw_retired_preview_{uuid4().hex}"
                    try:
                        wrapper.rename(retired)
                    except OSError:
                        return
                    self.retired_root = retired
            PreviewPackageCleanup(self.retired_root, self.root).cleanup()
            self.removed = not self.retired_root.exists()
        finally:
            self.queued = False
