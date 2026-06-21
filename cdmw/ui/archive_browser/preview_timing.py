"""Archive preview timing summaries and slow-path logging."""

from __future__ import annotations

from typing import Dict, Optional

from cdmw.services.diagnostics_service import format_timing_summary as _format_timing_summary
from cdmw.services.diagnostics_service import timing_value as _timing_value


class ArchivePreviewTimingMixin:
    """Timing labels and warnings for archive preview work."""

    def _archive_preview_timing_summary(self, source: str, timings: Optional[Dict[str, float]]) -> str:
        return _format_timing_summary(
            "Archive preview timings",
            source,
            timings,
            (
                ("cache_lookup_s", "cache_lookup"),
                ("native_package_cache_lookup_s", "native_pkg_cache"),
                ("worker_build_s", "worker_build"),
                ("entry_read_s", "read"),
                ("model_sidecar_refs_s", "sidecar_refs"),
                ("model_geometry_s", "geometry"),
                ("model_base_texture_attach_s", "base_tex"),
                ("model_sidecar_texture_attach_s", "sidecar_tex"),
                ("model_support_texture_attach_s", "support_tex"),
                ("model_texture_references_s", "refs"),
                ("prepared_model_s", "prepare_model"),
                ("image_attach_s", "image_attach"),
                ("ui_apply_s", "ui_apply"),
                ("model_apply_s", "model_apply"),
                ("total_s", "total"),
            ),
        )

    def _archive_preview_timing_warning(self, source: str, timings: Optional[Dict[str, float]]) -> str:
        total_s = _timing_value(timings, "total_s")
        model_apply_s = _timing_value(timings, "model_apply_s")
        if source == "preview_cache" and total_s > 2.0:
            return f"Archive preview cache hit is slower than expected: total={total_s:.2f}s."
        if model_apply_s > 0.50:
            return f"Archive preview model apply is slower than expected: model_apply={model_apply_s:.2f}s."
        return ""

    def _log_archive_preview_timing_if_needed(
        self,
        entry_name: str,
        source: str,
        timings: Optional[Dict[str, float]],
        timing_summary: str,
    ) -> None:
        total_s = _timing_value(timings, "total_s")
        model_apply_s = _timing_value(timings, "model_apply_s")
        warning_text = self._archive_preview_timing_warning(source, timings)
        if total_s < 0.35 and model_apply_s < 0.15 and not warning_text:
            return
        label = str(entry_name or "selected entry").strip()
        self.append_archive_log(f"{timing_summary} | entry={label}", verbose=True)
        if warning_text:
            self.append_archive_log(f"WARNING: {warning_text}")
