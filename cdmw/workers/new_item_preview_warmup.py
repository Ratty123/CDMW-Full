"""One opportunistic native preview warm-up owned by the snapshot worker."""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from cdmw.models import ArchiveEntry, clamp_model_preview_render_settings

_LOGGER = logging.getLogger(__name__)


class NewItemPreviewWarmup:
    """Overlap native cache preparation with catalogue/table reads, then drain it."""

    def __init__(self, cache_root: Path | None, render_settings: object, parent_stop: object) -> None:
        self.cache_root = Path(cache_root) if cache_root is not None else None
        self.render_settings = replace(
            clamp_model_preview_render_settings(render_settings), use_textures_by_default=True,
        )
        self.parent_stop = parent_stop
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def is_set(self) -> bool:
        return self.stop_event.is_set() or bool(getattr(self.parent_stop, "is_set", lambda: False)())

    def offer(self, entries: Iterable[ArchiveEntry]) -> None:
        if self.cache_root is None or self.thread is not None or self.is_set():
            return
        for entry in entries:
            if self.is_set():
                return
            # Small real character models exercise the shared material/index
            # path without loading a large scene or procedural PAC placeholder.
            if (
                entry.extension == ".pac"
                and entry.path.replace("\\", "/").casefold().startswith("character/model/")
                and 32768 <= entry.comp_size <= 262144
            ):
                thread = threading.Thread(
                    target=self._run, args=(replace(entry),), name="cdmw-new-item-preview-warmup",
                )
                try:
                    thread.start()
                except RuntimeError:
                    self.cache_root = None
                    return
                self.thread = thread
                return

    def _run(self, entry: ArchiveEntry) -> None:
        from cdmw.domain.cancellation import RunCancelled
        from cdmw.services.preview_rendering_service import run_native_preview_core_preview_job

        started = time.perf_counter()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        output: Path | None = None
        status = "cancelled"
        try:
            if self.is_set():
                return
            output = Path(tempfile.mkdtemp(prefix="cdmw_new_item_warmup_", dir=temporary_root))
            attempt = run_native_preview_core_preview_job(
                entry, cache_root=self.cache_root, render_settings=self.render_settings,
                package_root=Path(entry.pamt_path).parent.parent, output_root=output,
                timeout_seconds=8.0, stop_event=self,
            )
            status = attempt.status
        except RunCancelled:
            pass
        except Exception:  # noqa: BLE001 - optional warmth must not fail the snapshot
            status = "unavailable"
        finally:
            if output is not None:
                resolved = output.resolve()
                if resolved != temporary_root and resolved.is_relative_to(temporary_root):
                    shutil.rmtree(resolved, ignore_errors=True)
            _LOGGER.debug(
                "new_item_preview_warmup status=%s elapsed_ms=%.1f",
                status, (time.perf_counter() - started) * 1000,
            )

    def finish(self) -> None:
        # Warm-up never extends past the snapshot's ownership. Incomplete work
        # is cancelled rather than delaying the template the user selected.
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
