"""Archive preview memory audit payload and logging helpers."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Dict, Optional

from cdmw.models import ArchivePreviewResult
from cdmw.ui.shell.diagnostics_controller import windows_process_memory_snapshot as _windows_process_memory_snapshot


class ArchivePreviewMemoryAuditMixin:
    """Memory diagnostics for archive preview, native-core, and D3D11 workers."""

    @staticmethod
    def _memory_mib(value: object) -> float:
        try:
            return max(0.0, float(int(value or 0)) / (1024.0 * 1024.0))
        except (TypeError, ValueError):
            return 0.0

    def _archive_memory_audit_payload(
        self,
        reason: str,
        *,
        d3d11_payload: Optional[Mapping[str, object]] = None,
    ) -> Dict[str, object]:
        entry = self._current_archive_entry()
        result = getattr(self, "current_archive_preview_result", None)
        native_preview_diagnostics: Dict[str, object] = {}
        if isinstance(result, ArchivePreviewResult):
            native_preview_diagnostics = dict(getattr(result, "native_preview_diagnostics", {}) or {})
        d3d11_payload = dict(d3d11_payload or getattr(self, "archive_isolated_renderer_last_status_payload", {}) or {})
        main_memory = _windows_process_memory_snapshot(os.getpid())

        d3d11_pid = 0
        try:
            d3d11_pid = int(self._archive_qprocess_pid(getattr(self, "archive_isolated_renderer_process", None)) or 0)
        except (TypeError, ValueError):
            d3d11_pid = 0
        d3d11_memory = _windows_process_memory_snapshot(d3d11_pid)

        preview_core_pid = 0
        for key in ("native_preview_core_process_pid", "preview_core_process_pid"):
            try:
                preview_core_pid = int(native_preview_diagnostics.get(key, 0) or 0)
            except (TypeError, ValueError):
                preview_core_pid = 0
            if preview_core_pid > 0:
                break
        preview_core_memory = _windows_process_memory_snapshot(preview_core_pid)

        def _snapshot_value(snapshot: Mapping[str, object], key: str, fallback: object = 0) -> int:
            try:
                return int(snapshot.get(key, fallback) or 0)
            except (TypeError, ValueError):
                return 0

        item_preload_timer = getattr(self, "archive_item_icon_preload_timer", None)
        preview_core_idle_timer = getattr(self, "archive_preview_core_idle_shutdown_timer", None)
        name_search_index = getattr(self, "archive_name_search_index", None)
        active_workers = [
            name
            for name, thread in (
                ("archive_scan", getattr(self, "worker_thread", None)),
                ("basic_index", getattr(self, "archive_basic_index_thread", None)),
                ("enhanced_index", getattr(self, "archive_enhanced_index_thread", None)),
                ("derived_cache_write", getattr(self, "archive_derived_cache_thread", None)),
                ("sidecar_index", getattr(self, "archive_sidecar_thread", None)),
                ("structure_filter", getattr(self, "archive_structure_filter_thread", None)),
                ("icon_warmup", getattr(self, "archive_item_icon_warmup_thread", None)),
                ("icon_priority", getattr(self, "archive_item_icon_priority_thread", None)),
                ("filter", getattr(self, "archive_filter_worker", None)),
                ("preview", getattr(self, "archive_preview_thread", None)),
                ("d3d11_package", getattr(self, "archive_isolated_package_thread", None)),
            )
            if thread is not None
        ]
        payload: Dict[str, object] = {
            "reason": str(reason or "audit"),
            "selected_archive_path": str(getattr(entry, "path", "") or ""),
            "archive_entry_count": len(getattr(self, "archive_entries", []) or []),
            "archive_filtered_entry_count": len(getattr(self, "archive_filtered_entries", []) or []),
            "archive_filtered_shares_raw_entries": getattr(self, "archive_filtered_entries", None)
            is getattr(self, "archive_entries", None),
            "archive_filtered_dds_count": int(getattr(self, "archive_filtered_dds_count", 0) or 0),
            "archive_path_index_key_count": len(getattr(self, "archive_entries_by_normalized_path", {}) or {}),
            "archive_basename_index_key_count": len(getattr(self, "archive_entries_by_basename", {}) or {}),
            "archive_extension_index_key_count": len(getattr(self, "archive_entries_by_extension", {}) or {}),
            "archive_role_index_key_count": len(getattr(self, "archive_entries_by_role", {}) or {}),
            "archive_basic_index_state": str(getattr(self, "archive_basic_index_state", "") or ""),
            "archive_name_search_token_count": int(getattr(name_search_index, "row_count", 0) or 0),
            "archive_asset_family_cache_entries": len(getattr(self, "archive_asset_family_cache", {}) or {}),
            "archive_active_workers": tuple(active_workers),
            "archive_preview_cache_entries": len(getattr(self, "archive_preview_cache", {}) or {}),
            "archive_preview_cache_prepared_bytes": sum(
                self._archive_preview_result_prepared_bytes(cached_result)
                for cached_result in tuple(getattr(self, "archive_preview_cache", {}).values())
                if isinstance(cached_result, ArchivePreviewResult)
            ),
            "archive_preview_current_prepared_bytes": (
                self._archive_preview_result_prepared_bytes(result)
                if isinstance(result, ArchivePreviewResult)
                else 0
            ),
            "archive_item_icon_cache_entries": len(getattr(self, "archive_item_icon_pixmap_cache", {}) or {}),
            "archive_item_icon_cache_limit": int(getattr(self, "archive_item_icon_pixmap_cache_limit", 0) or 0),
            "archive_item_icon_preload_limit": int(getattr(self, "archive_item_icon_preload_limit", 0) or 0),
            "archive_item_icon_preload_queue_entries": len(getattr(self, "archive_item_icon_preload_queue", []) or []),
            "archive_item_icon_priority_queue_entries": len(
                getattr(self, "archive_item_icon_priority_queue", []) or []
            ),
            "archive_item_icon_warmup_thread_active": getattr(self, "archive_item_icon_warmup_thread", None) is not None,
            "archive_item_icon_priority_thread_active": getattr(self, "archive_item_icon_priority_thread", None) is not None,
            "archive_item_icon_preload_active": bool(
                getattr(self, "archive_item_icon_preload_queue", None)
                or (item_preload_timer is not None and item_preload_timer.isActive())
                or getattr(self, "archive_item_icon_priority_queue", None)
                or getattr(self, "archive_item_icon_priority_thread", None) is not None
            ),
            "asset_family_row_count": len(getattr(self, "current_archive_family_member_rows", []) or []),
            "archive_name_search_loaded": getattr(self, "archive_name_search_index", None) is not None,
            "main_process_private_bytes": _snapshot_value(main_memory, "private_bytes"),
            "main_process_working_set_bytes": _snapshot_value(main_memory, "working_set_bytes"),
            "preview_core_process_pid": preview_core_pid,
            "preview_core_idle_shutdown_ms": int(getattr(self, "archive_preview_core_idle_shutdown_ms", 0) or 0),
            "preview_core_idle_shutdown_count": int(getattr(self, "archive_preview_core_idle_shutdown_count", 0) or 0),
            "preview_core_idle_shutdown_timer_active": bool(
                preview_core_idle_timer is not None and preview_core_idle_timer.isActive()
            ),
            "preview_core_process_private_bytes": _snapshot_value(
                preview_core_memory,
                "private_bytes",
                native_preview_diagnostics.get("process_private_bytes", 0),
            ),
            "preview_core_process_working_set_bytes": _snapshot_value(
                preview_core_memory,
                "working_set_bytes",
                native_preview_diagnostics.get("process_working_set_bytes", 0),
            ),
            "preview_core_decoded_cache_bytes": int(native_preview_diagnostics.get("decoded_cache_bytes", 0) or 0),
            "preview_core_decoded_cache_entries": int(native_preview_diagnostics.get("decoded_cache_entries", 0) or 0),
            "preview_core_service_job_count": int(native_preview_diagnostics.get("service_job_count", 0) or 0),
            "preview_core_service_recycle_reason": str(native_preview_diagnostics.get("service_recycle_reason", "") or ""),
            "d3d11_process_pid": d3d11_pid,
            "d3d11_process_private_bytes": _snapshot_value(
                d3d11_memory,
                "private_bytes",
                d3d11_payload.get("process_private_bytes", 0),
            ),
            "d3d11_process_working_set_bytes": _snapshot_value(
                d3d11_memory,
                "working_set_bytes",
                d3d11_payload.get("process_working_set_bytes", 0),
            ),
            "d3d11_texture_cache_entries": int(d3d11_payload.get("texture_cache_entries", 0) or 0),
            "d3d11_texture_cache_releases": int(d3d11_payload.get("texture_cache_releases", 0) or 0),
            "d3d11_estimated_texture_bytes": int(d3d11_payload.get("estimated_texture_bytes", 0) or 0),
            "d3d11_frame_count": int(d3d11_payload.get("frame_count", 0) or 0),
            "d3d11_render_request_count": int(d3d11_payload.get("render_request_count", 0) or 0),
            "d3d11_render_suppressed_count": int(d3d11_payload.get("render_suppressed_count", 0) or 0),
            "d3d11_parent_unresponsive_count": int(d3d11_payload.get("parent_unresponsive_count", 0) or 0),
        }
        payload["memory_total_private_bytes"] = (
            int(payload.get("main_process_private_bytes", 0) or 0)
            + int(payload.get("preview_core_process_private_bytes", 0) or 0)
            + int(payload.get("d3d11_process_private_bytes", 0) or 0)
        )
        return payload

    def _record_archive_memory_audit(
        self,
        reason: str,
        *,
        d3d11_payload: Optional[Mapping[str, object]] = None,
        log_if_high: bool = False,
    ) -> Dict[str, object]:
        payload = self._archive_memory_audit_payload(reason, d3d11_payload=d3d11_payload)
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder("archive_memory_audit", **payload)
        main_private = self._memory_mib(payload.get("main_process_private_bytes", 0))
        preview_core_private = self._memory_mib(payload.get("preview_core_process_private_bytes", 0))
        d3d11_private = self._memory_mib(payload.get("d3d11_process_private_bytes", 0))
        should_log = bool(log_if_high) and (
            main_private >= 1536.0 or preview_core_private >= 512.0 or d3d11_private >= 512.0
        )
        now = time.monotonic()
        if should_log and now - float(getattr(self, "archive_memory_audit_last_log_at", 0.0) or 0.0) >= 30.0:
            self.archive_memory_audit_last_log_at = now
            self.append_archive_log(
                "Memory audit | "
                f"phase={str(reason or 'audit')}; "
                f"main_private={main_private:.1f} MiB; "
                f"preview_core_private={preview_core_private:.1f} MiB; "
                f"d3d11_private={d3d11_private:.1f} MiB; "
                f"preview_core_decoded_cache={self._memory_mib(payload.get('preview_core_decoded_cache_bytes', 0)):.1f} MiB; "
                f"d3d11_texture_est={self._memory_mib(payload.get('d3d11_estimated_texture_bytes', 0)):.1f} MiB; "
                f"entries={int(payload.get('archive_entry_count', 0) or 0):,}; "
                f"filtered={int(payload.get('archive_filtered_entry_count', 0) or 0):,}; "
                f"name_tokens={int(payload.get('archive_name_search_token_count', 0) or 0):,}; "
                f"asset_family_cache={int(payload.get('archive_asset_family_cache_entries', 0) or 0):,}; "
                f"workers={','.join(payload.get('archive_active_workers', ()) or ()) or 'none'}; "
                f"preview_cache_entries={int(payload.get('archive_preview_cache_entries', 0) or 0):,}; "
                f"icon_cache_entries={int(payload.get('archive_item_icon_cache_entries', 0) or 0):,}; "
                f"d3d11_frames={int(payload.get('d3d11_frame_count', 0) or 0):,}"
            )
            if main_private >= 3500.0:
                self.append_archive_log(
                    "WARNING: Archive Browser RAM is high "
                    f"during {str(reason or 'audit')}: main_private={main_private:.1f} MiB; "
                    f"workers={','.join(payload.get('archive_active_workers', ()) or ()) or 'none'}."
                )
        return payload
