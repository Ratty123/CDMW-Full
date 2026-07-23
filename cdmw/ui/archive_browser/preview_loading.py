"""Archive preview loading indicator and timeout watchdog helpers."""

from __future__ import annotations

import time
from pathlib import PurePosixPath
from typing import List, Optional

from cdmw.services.archive_query_service import build_archive_asset_family_graph
from cdmw.services.archive_read_service import (
    build_archive_entry_detail_text,
    build_archive_entry_metadata_summary,
)
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, ArchivePreviewResult, RelationConfidence, RelationKind
from cdmw.services.material_sidecar_service import material_sidecar_candidate_basenames_for_model
from cdmw.services.preview_rendering_service import shutdown_native_preview_core_service
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11


class ArchivePreviewLoadingMixin:
    """Archive preview loading status updates and stalled-preview recovery."""

    def _quick_archive_model_preview_result(self, entry: Optional[ArchiveEntry]) -> Optional[ArchivePreviewResult]:
        if entry is None or entry.extension not in ARCHIVE_MESH_EXTENSIONS:
            return None
        sidecar_refs: List[ArchiveModelTextureReference] = []
        candidate_basenames = material_sidecar_candidate_basenames_for_model(entry.path)
        seen_paths: set[str] = set()
        for basename in candidate_basenames:
            for related_entry in self.archive_entries_by_basename.get(basename.lower(), ()):
                normalized_related = related_entry.path.replace("\\", "/")
                if normalized_related in seen_paths:
                    continue
                seen_paths.add(normalized_related)
                sidecar_refs.append(
                    ArchiveModelTextureReference(
                        reference_name=PurePosixPath(normalized_related).name,
                        semantic_label="Material Sidecar",
                        resolution_status="resolved",
                        resolved_archive_path=related_entry.path,
                        resolved_package_label=related_entry.package_label,
                        resolved_entry=related_entry,
                        usage_count=1,
                        reference_kind=RelationKind.MATERIAL_SIDECAR.value,
                        relation_group="Material Sidecars",
                        relation_reason="Same-stem material sidecar",
                        relation_confidence=RelationConfidence.DERIVED_SAME_STEM.value,
                    )
                )
        detail_parts = [
            build_archive_entry_detail_text(
                entry,
                "Quick preview is showing metadata and same-stem material sidecars while the full 3D model preview builds in the background.",
            ),
            "Full preview loading...",
        ]
        if sidecar_refs:
            detail_parts.append(f"Found {len(sidecar_refs):,} likely material sidecar(s).")
        return ArchivePreviewResult(
            status="ok",
            title=entry.basename,
            metadata_summary=f"{build_archive_entry_metadata_summary(entry)} | Full preview loading...",
            detail_text="\n\n".join(part for part in detail_parts if part),
            model_texture_references=tuple(sidecar_refs),
            asset_family_graph=build_archive_asset_family_graph(entry, tuple(sidecar_refs)),
            preferred_view="info",
            sidecar_generation=self.archive_sidecar_generation,
        )

    def _show_archive_preview_loading_state(self, entry: Optional[ArchiveEntry]) -> None:
        host = getattr(self, "archive_d3d11_preview_host", None)
        controller = getattr(host, "controller", None)
        keep_d3d11_visible = bool(
            self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
            and controller is not None
            and getattr(controller, "applied_package_path", "")
        )
        self.archive_preview_title_label.setText(entry.basename if entry is not None else "Select an archive file")
        self.archive_preview_meta_label.setText("Loading preview...")
        role_label = self._archive_entry_role_label(entry)
        self.archive_preview_role_badge.setText(role_label)
        self.archive_preview_role_badge.setVisible(bool(entry))
        self._set_archive_preview_health_message(
            f"Loading {role_label.lower()} preview...",
            visible=bool(entry),
        )
        self._clear_archive_texture_reference_views()
        self.archive_preview_warning_badge.clear()
        self.archive_preview_warning_badge.setVisible(False)
        self.archive_preview_warning_label.clear()
        self.archive_preview_warning_label.setVisible(False)
        self.archive_preview_loose_toggle_button.setVisible(False)
        self.archive_preview_loose_toggle_button.setEnabled(False)
        self._set_archive_preview_base_detail_text(
            "Preparing archive preview...",
            include_current_model_debug=False,
        )
        self.archive_preview_info_edit.setPlainText("Preparing archive preview...")
        self.archive_preview_text_edit.clear()
        if not keep_d3d11_visible:
            self.archive_preview_label.clear_preview("Preparing archive preview...")
            self.archive_media_preview.clear_media("Preparing archive preview...")
        self._update_archive_model_action_controls(None)
        if not keep_d3d11_visible:
            self.archive_preview_stack.setCurrentWidget(self.archive_preview_info_edit)
        self.archive_preview_tabs.setCurrentIndex(0)
        self._set_archive_preview_image_controls_enabled(False)
        if self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11 and not keep_d3d11_visible:
            self._clear_archive_isolated_renderer_surface_for_request()
        self._start_archive_preview_loading_indicator(entry)

    def _start_archive_preview_loading_indicator(self, entry: Optional[ArchiveEntry]) -> None:
        self.archive_preview_loading_started_at = time.perf_counter()
        self.archive_preview_loading_request_id = int(getattr(self, "archive_preview_request_id", 0) or 0)
        self.archive_preview_loading_stall_reported = False
        self.archive_preview_loading_entry_name = entry.basename if entry is not None else "selected file"
        self.archive_preview_loading_loose = bool(self.archive_preview_requested_loose)
        self.set_status_message(
            f"Loading {'loose-file ' if self.archive_preview_loading_loose else ''}preview for {self.archive_preview_loading_entry_name}..."
        )
        self._update_archive_preview_loading_indicator()
        self.archive_preview_loading_timer.start()

    def _update_archive_preview_loading_indicator(self) -> None:
        if self.archive_preview_loading_started_at <= 0.0:
            return
        if int(getattr(self, "archive_preview_loading_request_id", 0) or 0) != int(
            getattr(self, "archive_preview_request_id", 0) or 0
        ):
            self._stop_archive_preview_loading_indicator(success=None)
            return
        elapsed = max(0.0, time.perf_counter() - self.archive_preview_loading_started_at)
        if elapsed >= 60.0:
            self._handle_archive_preview_loading_stall(elapsed)
            return
        prefix = "Loading loose-file preview" if self.archive_preview_loading_loose else "Loading preview"
        detail = f"{prefix} for {self.archive_preview_loading_entry_name}... {elapsed:.1f}s"
        self.archive_preview_meta_label.setToolTip(detail)
        if not self.archive_preview_quick_result_active:
            self.archive_preview_meta_label.setText(f"{prefix}... {elapsed:.1f}s")
        loading_text = (
            f"{detail}\n\n"
            "Large .pam/.pamlod files and textured model previews can take a few seconds. "
            "The preview worker is still running."
        )
        if self.archive_preview_stack.currentWidget() is self.archive_preview_info_edit and not self.archive_preview_quick_result_active:
            self.archive_preview_info_edit.setPlainText(loading_text)
        if not self.archive_preview_quick_result_active:
            self._set_archive_preview_base_detail_text(loading_text, include_current_model_debug=False)

    def _handle_archive_preview_loading_stall(self, elapsed: float) -> None:
        if bool(getattr(self, "archive_preview_loading_stall_reported", False)):
            return
        self.archive_preview_loading_stall_reported = True
        request_id = int(getattr(self, "archive_preview_loading_request_id", 0) or 0)
        has_fast_result = str(getattr(getattr(self, "current_archive_preview_result", None), "quality_tier", "") or "").strip().lower() == "fast"
        preview_phase = "full_after_fast" if has_fast_result or self.archive_preview_quick_result_active else "initial"
        recorder = getattr(self, "_record_runtime_event", None)
        if self.archive_preview_worker is not None:
            try:
                self.archive_preview_worker.stop()
            except Exception as exc:
                if callable(recorder):
                    recorder("archive_preview_worker_failed", reason="worker_failed", request_id=request_id, error=str(exc))
        if self.archive_preview_thread is not None:
            try:
                self.archive_preview_thread.requestInterruption()
            except Exception as exc:
                if callable(recorder):
                    recorder("archive_preview_worker_failed", reason="worker_failed", request_id=request_id, error=str(exc))
            try:
                self.archive_preview_thread.quit()
            except Exception as exc:
                if callable(recorder):
                    recorder("archive_preview_worker_failed", reason="worker_failed", request_id=request_id, error=str(exc))
        try:
            shutdown_native_preview_core_service()
        except Exception as exc:
            if callable(recorder):
                recorder("archive_preview_core_shutdown_failed", reason="worker_failed", request_id=request_id, error=str(exc))
        if callable(recorder):
            recorder(
                "archive_preview_stalled",
                preview_stalled=True,
                preview_phase=preview_phase,
                request_id=request_id,
                elapsed_seconds=round(float(elapsed), 3),
                path=str(getattr(self._current_archive_entry(), "path", "") or ""),
            )
        self.archive_preview_request_id += 1
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self.archive_preview_debounce_timer.stop()
        self.archive_preview_loading_timer.stop()
        self.archive_preview_loading_started_at = 0.0
        self.archive_preview_loading_entry_name = ""
        self.archive_preview_loading_loose = False
        self.archive_preview_quick_result_active = False
        if has_fast_result:
            message = "Fast preview remains visible; full preview timed out and was stopped."
            self._set_archive_preview_health_message(message, visible=True)
            self.set_status_message(message, error=True)
            return
        self._clear_archive_preview("Preview timed out while loading. Select the file again or use Fast Detail.")
        self.set_status_message("Archive preview timed out and was stopped.", error=True)

    def _stop_archive_preview_loading_indicator(self, *, success: Optional[bool]) -> None:
        elapsed = (
            max(0.0, time.perf_counter() - self.archive_preview_loading_started_at)
            if self.archive_preview_loading_started_at > 0.0
            else 0.0
        )
        entry_name = self.archive_preview_loading_entry_name
        self.archive_preview_loading_timer.stop()
        self.archive_preview_loading_started_at = 0.0
        self.archive_preview_loading_request_id = 0
        self.archive_preview_loading_stall_reported = False
        self.archive_preview_loading_entry_name = ""
        self.archive_preview_loading_loose = False
        self.archive_preview_quick_result_active = False
        if success is None:
            return
        if success:
            label = f"Preview ready for {entry_name}."
            if elapsed >= 1.0:
                label = f"{label} ({elapsed:.1f}s)"
            self.archive_preview_meta_label.setToolTip(label)
        else:
            label = f"Preview failed for {entry_name}."
            if elapsed >= 1.0:
                label = f"{label} ({elapsed:.1f}s)"
            self._set_archive_preview_health_message(label, visible=True)
