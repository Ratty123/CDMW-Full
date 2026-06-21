"""Progress bar helpers for Research tab worker/status updates."""

from __future__ import annotations

from PySide6.QtWidgets import QProgressBar

__all__ = ["set_progress_error", "set_progress_idle", "set_progress_ready", "set_research_progress"]


def set_research_progress(progress: QProgressBar, current: int, total: int) -> int:
    if total > 0:
        safe_current = min(max(int(current), 0), int(total))
        progress.setRange(0, int(total))
        progress.setValue(safe_current)
        progress.setFormat(f"{safe_current} / {int(total)}")
        return safe_current
    progress.setRange(0, 0)
    progress.setFormat("Working...")
    return 0


def set_progress_error(progress: QProgressBar) -> None:
    progress.setRange(0, 1)
    progress.setValue(0)
    progress.setFormat("Error")


def set_progress_idle(progress: QProgressBar) -> None:
    progress.setRange(0, 1)
    progress.setValue(0)
    progress.setFormat("Idle")


def set_progress_ready(progress: QProgressBar) -> None:
    progress.setRange(0, 1)
    progress.setValue(1)
    progress.setFormat("Ready")
