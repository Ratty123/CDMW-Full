"""Archive-cache health UI for shell MainWindow."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtWidgets import QMessageBox, QWidget

from cdmw.core.archive import archive_scan_shard_cache_health


class DashboardControllerMixin:
    """Refresh archive-cache health surfaces."""

    def _initialize_archive_cache_status_chip(self) -> None:
        self._dashboard_set_archive_progress(percent=int(getattr(self, "_archive_load_progress_percent", 0) or 0))

    def _set_widget_health_state(self, widget: Optional[QWidget], state: str) -> None:
        if widget is None:
            return
        normalized = str(state or "").strip().lower()
        if normalized not in {"healthy", "building", "missing", "stale", "unhealthy", "unknown"}:
            normalized = ""
        if str(widget.property("healthState") or "") == normalized:
            return
        widget.setProperty("healthState", normalized)
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        except Exception:
            pass
        widget.update()

    def _set_archive_cache_status_chip(
        self,
        state: str,
        detail: str,
        *,
        percent: Optional[int] = None,
        active: bool = False,
    ) -> None:
        label = getattr(self, "archive_cache_status_chip", None)
        if label is None:
            return
        normalized = str(state or "unknown").strip().lower()
        if normalized not in {"unknown", "healthy", "building", "missing", "stale", "unhealthy"}:
            normalized = "unknown"
        if active:
            percent_text = f" {min(max(int(percent or 0), 0), 100)}%" if percent is not None else ""
            text = f"Cache: Building{percent_text}"
        else:
            text = {
                "healthy": "Cache: Healthy",
                "building": "Cache: Building",
                "missing": "Cache: Missing",
                "stale": "Cache: Stale",
                "unhealthy": "Cache: Unhealthy",
            }.get(normalized, "Cache: Unknown")
        detail_text = str(detail or "").strip() or text
        label.setText(text)
        label.setToolTip(detail_text)
        self._set_widget_health_state(label, normalized)

    def _set_archive_cache_health(self, state: str, reason: str, *, package_root: str = "") -> None:
        normalized = str(state or "unknown").strip().lower()
        if normalized not in {"unknown", "healthy", "building", "missing", "stale", "unhealthy"}:
            normalized = "unknown"
        reason_text = str(reason or "").strip()
        if not reason_text:
            if normalized == "healthy":
                reason_text = "Cache Status: Healthy."
            elif normalized == "building":
                reason_text = "Cache Status: Building. Archive cache build is running."
            elif normalized in {"missing", "stale", "unhealthy"}:
                reason_text = "Cache Status: Unhealthy. Rebuild archive cache."
            else:
                reason_text = "Cache Status: Unknown. Archive cache has not been checked."
        self._archive_cache_health_state = normalized
        self._archive_cache_health_reason = reason_text
        self._archive_cache_health_checked_path = str(package_root or self.archive_package_root_edit.text().strip() or "")
        self._dashboard_set_archive_progress()

    def _check_archive_cache_health(self, package_root_text: str = "") -> Dict[str, object]:
        root_text = str(package_root_text or self.archive_package_root_edit.text().strip() or "").strip()
        if not root_text:
            self._set_archive_cache_health("unhealthy", "Cache Status: Unhealthy. No Crimson Desert path is set.", package_root="")
            return {"status": "unhealthy", "reason": self._archive_cache_health_reason}
        package_root = Path(root_text).expanduser()
        if not package_root.exists():
            self._set_archive_cache_health(
                "unhealthy",
                f"Cache Status: Unhealthy. Crimson Desert path does not exist: {package_root}",
                package_root=root_text,
            )
            return {"status": "unhealthy", "reason": self._archive_cache_health_reason}
        try:
            report = archive_scan_shard_cache_health(package_root, self.archive_cache_root)
        except Exception as exc:
            report = {"status": "unhealthy", "reason": f"Could not inspect archive cache: {exc}"}
        status = str(report.get("status", "unknown") or "unknown").strip().lower()
        reason = str(report.get("reason", "") or "").strip()
        if status == "healthy":
            self._set_archive_cache_health("healthy", reason or "Cache Status: Healthy.", package_root=root_text)
        elif status == "missing":
            self._set_archive_cache_health(
                "missing",
                reason or "Cache Status: Unhealthy. Archive cache has not been built yet.",
                package_root=root_text,
            )
        elif status == "stale":
            self._set_archive_cache_health(
                "stale",
                reason or "Cache Status: Unhealthy. Archive cache is stale.",
                package_root=root_text,
            )
        else:
            self._set_archive_cache_health(
                "unhealthy",
                reason or "Cache Status: Unhealthy. Archive cache could not be validated.",
                package_root=root_text,
            )
        return dict(report)

    def _warn_if_archive_cache_stale(self, health_report: Mapping[str, object], package_root_text: str) -> None:
        if str(health_report.get("status", "") or "").strip().lower() != "stale":
            return
        root_key = str(package_root_text or "").strip()
        if root_key and root_key == str(getattr(self, "_archive_cache_stale_warning_shown_for", "") or ""):
            return
        self._archive_cache_stale_warning_shown_for = root_key
        reason = str(health_report.get("reason", "") or "Archive cache is stale.").strip()
        finish_startup_splash = getattr(self, "_finish_startup_splash_before_modal", None)
        if callable(finish_startup_splash):
            finish_startup_splash()
        QMessageBox.warning(
            self,
            "Archive Cache Stale",
            (
                f"{reason}\n\n"
                "CDMW will rebuild the archive cache from the current game files now.\n\n"
                "This can happen after a game update, after adding or removing mod archives, "
                "or after repeatedly editing/replacing archive files while testing."
            ),
        )

    def _dashboard_set_archive_progress(self, phase: str = "", detail: str = "", percent: Optional[int] = None) -> None:
        if not hasattr(self, "archive_cache_status_chip"):
            return
        active = bool(getattr(self, "_archive_load_progress_active", False))
        health_state = str(getattr(self, "_archive_cache_health_state", "unknown") or "unknown")
        health_reason = str(getattr(self, "_archive_cache_health_reason", "") or "").strip()
        percent_value = int(
            getattr(self, "_archive_load_progress_percent", 0) if percent is None else min(max(int(percent), 0), 100)
        )
        detail_text = str(detail or getattr(self, "_archive_load_progress_detail", "") or "").strip()
        phase_text = str(phase or "").strip()
        if not active:
            if health_state == "healthy":
                percent_value = 100
                detail_text = health_reason or "Cache Status: Healthy."
            elif health_state in {"stale", "missing", "unhealthy"}:
                percent_value = 0
                detail_text = health_reason or "Cache Status: Unhealthy. Rebuild archive cache."
            elif health_state == "building":
                detail_text = health_reason or "Archive cache build queued."
            else:
                percent_value = 0
                detail_text = health_reason or "Cache Status: Unknown. Archive cache has not been checked."
        else:
            if not phase_text:
                phase_text = self._archive_progress_phase_for_detail(detail_text)[0] if detail_text else "Working"
            if not detail_text:
                detail_text = "Archive cache build running..."
        progress_health_state = health_state if not active else "building"
        self._set_archive_cache_status_chip(
            progress_health_state,
            detail_text,
            percent=percent_value,
            active=active,
        )

    def _refresh_dashboard(self) -> None:
        if not hasattr(self, "archive_package_root_edit"):
            self._dashboard_set_archive_progress(percent=int(getattr(self, "_archive_load_progress_percent", 0) or 0))
            return
        current_archive_root = self.archive_package_root_edit.text().strip()
        if (
            current_archive_root
            and current_archive_root != str(getattr(self, "_archive_cache_health_checked_path", "") or "")
            and not bool(getattr(self, "_archive_load_progress_active", False))
        ):
            self._check_archive_cache_health(current_archive_root)
            return
        self._dashboard_set_archive_progress(percent=int(getattr(self, "_archive_load_progress_percent", 0) or 0))


__all__ = ["DashboardControllerMixin"]
