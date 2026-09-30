"""Archive filtering through the standalone catalogue."""
from __future__ import annotations

from cdmw.domain.archives.catalogue_operations import ArchiveBackendError


def _record_archive_filter_worker_lifecycle(target, event, **fields):
    recorder = getattr(target, "_record_runtime_event", None)
    if callable(recorder):
        recorder(event, **fields)


class ArchiveFilterWorkerMixin:
    def _request_archive_structure_children(self) -> None:
        bridge = self.archive_remote_bridge
        if bridge is None:
            self._handle_archive_backend_failure("fetch_children", ArchiveBackendError("backend_unavailable", "The standalone archive backend is unavailable."))
        elif bridge.structure_requests_ready:
            bridge.request_structure_children(self._current_archive_structure_filter_value())

    def _submit_archive_filter(self, preferred_path="", **_kwargs) -> None:
        bridge = self.archive_remote_bridge
        if bridge is None:
            self._handle_archive_backend_failure("create_query", ArchiveBackendError("backend_unavailable", "The standalone archive backend is unavailable."))
        else:
            bridge.apply_current_query()

    def _apply_archive_filter(self) -> None:
        self._capture_archive_controls_scroll_for_filter()
        self._mark_archive_browser_render_stale()
        if self.archive_active_asset_catalog_scope:
            self.archive_active_asset_catalog_scope = ""
            self.archive_clear_asset_scope_button.setVisible(False)
            if hasattr(self, "archive_scope_banner_label"):
                self.archive_scope_banner_label.clear()
                self.archive_scope_banner_label.setVisible(False)
            self.archive_filter_edit.setPlaceholderText("Include path/item-name filter or glob, e.g. Vow of the Dead King or */texture/*")
            self.archive_package_filter_hint_label.setText("Exclude accepts semicolon-separated substrings or globs.")
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self.archive_preview_debounce_timer.stop()
        self._stop_archive_native_preview_prefetch()
        if self.archive_preview_worker is not None:
            _record_archive_filter_worker_lifecycle(
                self,
                "archive_preview_worker_cancelled",
                reason="cancelled_by_filter_change",
            )
            try:
                self.archive_preview_worker.stop()
            except Exception as exc:
                _record_archive_filter_worker_lifecycle(
                    self,
                    "archive_preview_worker_failed",
                    reason="worker_failed",
                    error=str(exc),
                )
        self._stop_archive_preview_loading_indicator(success=None)
        self._submit_archive_filter()
        self._restore_archive_controls_scroll_after_filter()
