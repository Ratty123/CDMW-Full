"""Archive browser load and scan progress UI helpers."""

from __future__ import annotations

import time
from typing import Optional, Tuple


class ArchiveProgressMixin:
    """Coalesced archive scan progress and startup splash updates."""

    def _set_archive_warmup_overlay(
        self,
        visible: bool,
        title: str = "",
        message: str = "",
        *,
        current: int = 0,
        total: int = 0,
        fmt: str = "",
    ) -> None:
        if not hasattr(self, "archive_warmup_overlay"):
            return
        self.archive_warmup_overlay.hide()

    def _reset_archive_load_progress(self) -> None:
        self._archive_load_progress_percent = 0
        self._archive_load_progress_active = True
        self._archive_load_progress_detail = ""

    def _archive_progress_phase_for_detail(self, detail: str) -> Tuple[str, int, int]:
        text = " ".join(str(detail or "Working").split())
        lowered = text.lower()
        if "fail" in lowered or "error" in lowered:
            return "Failed", 0, 0
        if "cancel" in lowered or "stop" in lowered:
            return "Stopping", 0, 0
        if (
            "archive ready" in lowered
            or "archive scan complete" in lowered
            or "loaded " in lowered and "archive entries" in lowered and "background" not in lowered
        ):
            return "Ready", 100, 100
        if "render" in lowered or "browser view" in lowered or "browser items" in lowered:
            return "Rendering", 90, 99
        if "opening archive list" in lowered or "preparing archive list" in lowered:
            return "List", 86, 90
        if "sidecar" in lowered:
            return "Sidecar", 86, 98
        if (
            "item-name" in lowered
            or "name search" in lowered
            or "name-search" in lowered
            or "path lookup" in lowered
            or "derived index" in lowered
            or "category index" in lowered
            or "browser indexes" in lowered
        ):
            return "Indexing", 72, 88
        if "cache" in lowered and any(token in lowered for token in ("building", "compressing", "writing", "written", "saving")):
            return "Cache", 55, 74
        if "cache" in lowered:
            return "Cache", 4, 38
        if "native archive scan" in lowered or "archive indexes" in lowered or "parsing " in lowered:
            return "Scanning", 8, 55
        if "refresh" in lowered or "scan" in lowered:
            return "Scanning", 8, 55
        if "preparing" in lowered:
            return "Preparing", 1, 4
        return "Working", 1, 95

    def _archive_progress_percent_for_detail(self, current: int, total: int, detail: str) -> int:
        phase, start, end = self._archive_progress_phase_for_detail(detail)
        if phase in {"Ready", "Failed", "Stopping"}:
            return start
        previous = int(getattr(self, "_archive_load_progress_percent", 0) or 0)
        bounded_total = max(0, int(total or 0))
        if bounded_total > 0:
            bounded_current = min(max(int(current or 0), 0), bounded_total)
            fraction = bounded_current / max(bounded_total, 1)
            candidate = int(round(start + (max(end, start) - start) * fraction))
        else:
            candidate = start if previous < start else min(max(end - 1, start), previous + 1)
        if bool(getattr(self, "_archive_load_progress_active", False)):
            candidate = max(previous, candidate)
        return min(max(candidate, 0), 100)

    def _set_archive_load_progress(
        self,
        detail: str,
        current: int = 0,
        total: int = 0,
        *,
        phase: str = "",
        percent: Optional[int] = None,
        allow_decrease: bool = False,
        indeterminate: bool = False,
    ) -> None:
        detail_text = str(detail or "Working...").strip() or "Working..."
        phase_text = str(phase or "").strip()
        if not phase_text:
            phase_text = self._archive_progress_phase_for_detail(detail_text)[0]
        if percent is None:
            percent_value = self._archive_progress_percent_for_detail(current, total, detail_text)
        else:
            percent_value = min(max(int(percent), 0), 100)
        previous = int(getattr(self, "_archive_load_progress_percent", 0) or 0)
        new_work_after_ready = (
            not allow_decrease
            and previous >= 100
            and percent_value < previous
            and phase_text not in {"Ready", "Failed"}
        )
        if not allow_decrease and not new_work_after_ready:
            percent_value = max(previous, percent_value)
        self._archive_load_progress_active = (indeterminate or percent_value < 100) and phase_text not in {"Ready", "Failed"}
        self._archive_load_progress_percent = percent_value
        self._archive_load_progress_detail = detail_text
        if hasattr(self, "archive_scan_progress_bar"):
            if indeterminate:
                self.archive_scan_progress_bar.setRange(0, 0)
                self.archive_scan_progress_bar.setFormat("")
            else:
                self.archive_scan_progress_bar.setRange(0, 100)
                self.archive_scan_progress_bar.setValue(percent_value)
                self.archive_scan_progress_bar.setFormat(f"{percent_value}%")
            self.archive_scan_progress_bar.setToolTip(detail_text)
        if hasattr(self, "archive_scan_progress_label"):
            self.archive_scan_progress_label.setText(phase_text)
            self.archive_scan_progress_label.setToolTip(detail_text)
        self._dashboard_set_archive_progress(phase_text, detail_text, percent_value)

    def _apply_archive_scan_progress(self, current: int, total: int, detail: str) -> None:
        progress_detail = str(detail or "Working...")
        if bool(getattr(self, "archive_startup_hold_until_ready", False)):
            self._startup_splash_last_progress_at = time.monotonic()
        if total > 0:
            completed_value = min(max(current, 0), total)
            percent = self._archive_progress_percent_for_detail(completed_value, total, progress_detail)
            phase_percent = int(round(100.0 * completed_value / max(total, 1)))
            detail_with_progress = f"{progress_detail} ({phase_percent}%)"
            self._set_archive_load_progress(progress_detail, completed_value, total, percent=percent)
            self._update_startup_splash(detail_with_progress, percent, 100)
            self._set_archive_warmup_overlay(
                True,
                "Scanning Archive Packages",
                detail_with_progress,
                current=completed_value,
                total=total,
                fmt=f"{percent}%",
            )
        else:
            percent = self._archive_progress_percent_for_detail(current, total, progress_detail)
            detail_with_progress = progress_detail
            self._set_archive_load_progress(
                progress_detail,
                current,
                total,
                percent=percent,
                indeterminate=True,
            )
            self._update_startup_splash(detail_with_progress)
            self._set_archive_warmup_overlay(
                True,
                "Scanning Archive Packages",
                progress_detail,
            )
        self.set_status_message(progress_detail if total <= 0 else detail_with_progress)

    def _flush_archive_scan_progress(self) -> None:
        pending = self._archive_scan_progress_pending
        if pending is None:
            return
        self._archive_scan_progress_pending = None
        self._archive_scan_progress_last_flush = time.perf_counter()
        current, total, detail = pending
        self._apply_archive_scan_progress(current, total, detail)

    def _handle_archive_scan_progress(self, current: int, total: int, detail: str) -> None:
        self._archive_scan_progress_pending = (
            int(current or 0),
            int(total or 0),
            self._startup_splash_progress_detail(str(detail or "Working...")),
        )
        now = time.perf_counter()
        elapsed = now - self._archive_scan_progress_last_flush
        if elapsed >= self._archive_scan_progress_min_interval_s:
            self._archive_scan_progress_timer.stop()
            self._flush_archive_scan_progress()
            return
        if not self._archive_scan_progress_timer.isActive():
            delay_ms = max(1, int((self._archive_scan_progress_min_interval_s - elapsed) * 1000.0))
            self._archive_scan_progress_timer.start(delay_ms)


__all__ = ["ArchiveProgressMixin"]
