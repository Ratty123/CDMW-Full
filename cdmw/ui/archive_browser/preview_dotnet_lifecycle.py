"""Compatibility-facing lifecycle hooks for the resident .NET/Vortice archive preview."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path


class ArchivePreviewDotNetLifecycleMixin:
    """Own the old archive lifecycle method names without a legacy renderer process."""

    def _archive_isolated_renderer_process_running(self) -> bool:
        controller = getattr(getattr(self, "archive_d3d11_preview_host", None), "controller", None)
        return bool(controller is not None and getattr(controller, "is_running", False))

    def _clear_archive_isolated_renderer_surface_for_request(self) -> None:
        host = getattr(self, "archive_d3d11_preview_host", None)
        clear = getattr(host, "clear_preview", None)
        if callable(clear):
            clear()
        self.archive_isolated_renderer_active_package = None
        self.archive_isolated_renderer_package_source = ""

    def _shutdown_archive_isolated_renderer_host(self) -> None:
        host = getattr(self, "archive_d3d11_preview_host", None)
        controller = getattr(host, "controller", None)
        if controller is None:
            return
        if bool(getattr(self, "_shutting_down", False)):
            controller.shutdown()
        else:
            controller.clear_preview()
        self.archive_isolated_renderer_active_package = None
        self.archive_isolated_renderer_package_source = ""

    def _open_archive_isolated_d3d11_preview(self) -> None:
        """Reload the current canonical package in the resident Vortice host.

        The method name remains as a UI compatibility shim for older signal wiring and
        settings. It never launches the retired native renderer.
        """
        package_dir = getattr(self, "archive_isolated_renderer_active_package", None)
        host = getattr(self, "archive_d3d11_preview_host", None)
        if package_dir is None or host is None:
            current = getattr(self, "_current_archive_entry", lambda: None)()
            if current is not None:
                self._render_archive_preview(current, force=True)
            return
        if not host.load_package(Path(package_dir), reset_view=False):
            self.set_status_message(".NET/Vortice Preview rejected the prepared package.", error=True)
            return
        host.set_render_tuning(self._current_model_preview_render_settings())
        self.set_status_message("Reloaded .NET/Vortice Preview.")

    def _start_archive_native_preview_prefetch(self) -> None:
        """Compatibility no-op; canonical packages are cached by preview preparation."""

    def _stop_archive_native_preview_prefetch(self) -> None:
        """Compatibility no-op retained for shared cancellation paths."""

    def _archive_material_channel_debug_from_package(self, package_dir: object) -> str:
        try:
            payload = json.loads(
                (Path(package_dir).expanduser() / "net_materials.json").read_text(encoding="utf-8-sig")
            )
        except (OSError, TypeError, ValueError):
            return ""
        if not isinstance(payload, Mapping):
            return ""
        submeshes = payload.get("submeshes", ())
        if not isinstance(submeshes, Sequence) or isinstance(submeshes, (str, bytes, bytearray)):
            return ""
        summaries: list[str] = []
        for index, raw in enumerate(tuple(submeshes)[:12]):
            if not isinstance(raw, Mapping):
                continue
            channels = raw.get("packaged_channels", raw.get("resolved_channels", {}))
            names = (
                sorted(str(name) for name, value in channels.items() if str(value or "").strip())
                if isinstance(channels, Mapping)
                else []
            )
            material_name = str(raw.get("material_name", raw.get("material", "")) or "").strip()
            summaries.append(
                f"part {index} {material_name or 'material'}: {', '.join(names) or 'no texture channels'}"
            )
        return "Material Authority: " + " | ".join(summaries) if summaries else ""


__all__ = ["ArchivePreviewDotNetLifecycleMixin"]
