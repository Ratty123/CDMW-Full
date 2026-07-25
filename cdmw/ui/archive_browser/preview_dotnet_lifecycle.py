"""Compatibility-facing lifecycle hooks for the resident .NET/Vortice archive preview."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer


ARCHIVE_DOTNET_PREWARM_ATTEMPT_LIMIT = 3
ARCHIVE_DOTNET_PREWARM_RETRY_MS = 3_000


class ArchivePreviewDotNetLifecycleMixin:
    """Own the old archive lifecycle method names without a legacy renderer process."""

    def _archive_isolated_renderer_process_running(self) -> bool:
        controller = getattr(getattr(self, "archive_d3d11_preview_host", None), "controller", None)
        return bool(controller is not None and getattr(controller, "is_running", False))

    def _archive_resident_scene_available(self) -> bool:
        controller = getattr(getattr(self, "archive_d3d11_preview_host", None), "controller", None)
        return bool(controller is not None and getattr(controller, "applied_package_path", ""))

    def _preserve_archive_resident_scene_error(self, message: str) -> bool:
        if not self._archive_resident_scene_available():
            return False
        self.set_status_message(
            f"Preview update failed; the previous model remains visible: {message}",
            error=True,
        )
        self._sync_archive_texture_action_state()
        return True

    def _prewarm_archive_dotnet_preview(self) -> None:
        host = getattr(self, "archive_d3d11_preview_host", None)
        controller = getattr(host, "controller", None)
        if host is None or controller is None:
            return
        if bool(getattr(controller, "desired_package_path", "")):
            # A selection already owns the renderer; it no longer needs warming.
            return
        if bool(getattr(controller, "is_running", False)):
            return
        attempt = int(getattr(self, "_archive_dotnet_prewarm_attempts", 0) or 0) + 1
        self._archive_dotnet_prewarm_attempts = attempt
        try:
            queued = bool(host.prewarm_from_cache(
                self._native_preview_package_cache_root()
            ))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self.archive_isolated_renderer_debug_text = (
                f"prewarm=skipped attempt={attempt} reason={exc}"
            )
            self._schedule_archive_dotnet_preview_prewarm_retry(attempt)
            return
        self.archive_isolated_renderer_debug_text = (
            f"prewarm={'building' if queued else 'superseded'} attempt={attempt}"
        )
        if not queued:
            self._schedule_archive_dotnet_preview_prewarm_retry(attempt)
            return
        # The budget is per warm-up episode, not per session: a later warm-up
        # after the renderer has stopped gets its own retries rather than
        # inheriting an exhausted count.
        self._archive_dotnet_prewarm_attempts = 0

    def _schedule_archive_dotnet_preview_prewarm_retry(self, attempt: int) -> None:
        """Re-arm the warm-up so one transient miss does not cost the first click.

        A failed launch clears the controller's prewarm package outright, so
        without this the very next .pac selection pays the helper's full cold
        start instead of landing on a resident renderer.
        """

        if bool(getattr(self, "_shutting_down", False)):
            return
        if int(attempt) >= ARCHIVE_DOTNET_PREWARM_ATTEMPT_LIMIT:
            return
        QTimer.singleShot(
            ARCHIVE_DOTNET_PREWARM_RETRY_MS,
            self._prewarm_archive_dotnet_preview,
        )

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
        """Apply the persisted texture checkbox without restarting the renderer."""
        checkbox = getattr(self, "archive_isolated_renderer_button", None)
        settings = self._current_model_preview_render_settings()
        host = getattr(self, "archive_d3d11_preview_host", None)
        package_dir = getattr(self, "archive_isolated_renderer_active_package", None)
        if checkbox is not None and hasattr(checkbox, "isChecked"):
            enabled = bool(checkbox.isChecked())
            if bool(settings.use_textures_by_default) != enabled:
                self._handle_model_preview_settings_changed(
                    replace(settings, use_textures_by_default=enabled)
                )
                return
        else:
            enabled = bool(
                package_dir is None
                or not self._archive_active_package_has_textures()
                or not bool(getattr(self, "_archive_textures_visible", True))
            )
        if host is None:
            return
        if bool(getattr(self, "_archive_texture_request_loading", False)):
            self._sync_archive_texture_action_state()
            return
        if enabled:
            if package_dir is None or not self._archive_active_package_has_textures():
                self._request_archive_preview_textures(
                    automatic=bool(checkbox is not None and hasattr(checkbox, "isChecked"))
                )
                return
            if not bool(getattr(self, "_archive_textures_visible", False)):
                host.set_viewport_display_mode("textured")
                self._archive_textures_visible = True
                self.set_status_message("Textures shown.")
        elif (
            package_dir is not None
            and self._archive_active_package_has_textures()
            and bool(getattr(self, "_archive_textures_visible", False))
        ):
            host.set_viewport_display_mode("untextured_wire")
            self._archive_textures_visible = False
            self.set_status_message("Textures hidden; geometry remains resident.")
        self._sync_archive_texture_action_state()

    def _archive_preview_effective_render_settings(self, request_id: int | None = None):
        settings = self._current_model_preview_render_settings()
        active_request_id = int(
            self.archive_preview_request_id if request_id is None else request_id
        )
        texture_request_id = int(getattr(self, "_archive_texture_request_id", 0) or 0)
        return replace(
            settings,
            use_textures_by_default=bool(texture_request_id and active_request_id == texture_request_id),
        )

    def _archive_active_package_has_textures(self) -> bool:
        package_dir = getattr(self, "archive_isolated_renderer_active_package", None)
        if package_dir is None:
            return False
        try:
            payload = json.loads((Path(package_dir) / "net_materials.json").read_text(encoding="utf-8-sig"))
        except (OSError, TypeError, ValueError):
            return False
        resources = payload.get("resources", ()) if isinstance(payload, Mapping) else ()
        return bool(resources) and isinstance(resources, Sequence) and not isinstance(resources, (str, bytes, bytearray))

    def _request_archive_preview_textures(self, *, automatic: bool = False) -> bool:
        current = getattr(self, "_current_archive_entry", lambda: None)()
        if current is None or bool(getattr(self, "_archive_texture_request_loading", False)):
            return False
        request_id = int(getattr(self, "archive_preview_request_id", 0) or 0) + 1
        self._archive_texture_request_id = request_id
        self._archive_texture_request_loading = True
        self._archive_texture_request_automatic = bool(automatic)
        self._sync_archive_texture_action_state()
        self.set_status_message("Loading textures while keeping geometry visible...")
        self._render_archive_preview(current, force=True)
        return True

    def _handle_archive_resident_package_applied(self, package_path: str, generation: int) -> None:
        if not bool(getattr(self, "_archive_texture_request_loading", False)):
            return
        if int(generation or 0) != int(getattr(self, "_archive_texture_package_generation", 0) or 0):
            return
        expected_path = str(getattr(self, "_archive_texture_package_path", "") or "")
        if expected_path and self._archive_package_key(package_path) != self._archive_package_key(expected_path):
            return
        self.archive_isolated_renderer_active_package = Path(package_path)
        self.archive_isolated_renderer_package_source = "dotnet-canonical"
        render_settings = getattr(self, "_archive_texture_render_settings", None)
        host = getattr(self, "archive_d3d11_preview_host", None)
        automatic_request = bool(getattr(self, "_archive_texture_request_automatic", False))
        show_textures = bool(
            not automatic_request
            or self._current_model_preview_render_settings().use_textures_by_default
        )
        if host is not None and render_settings is not None:
            host.set_render_tuning(render_settings)
            host.set_viewport_display_mode("textured" if show_textures else "untextured_wire")
        has_textures = self._archive_active_package_has_textures()
        request_id = int(getattr(self, "_archive_texture_request_id", 0) or 0)
        pending_result = getattr(self, "_archive_pending_texture_result", None)
        self._finish_archive_texture_request(
            request_id,
            success=has_textures,
            message="The prepared package did not contain resolved DDS resources." if not has_textures else "",
        )
        if has_textures and not show_textures:
            self._archive_textures_visible = False
            self._sync_archive_texture_action_state()
        if has_textures and pending_result is not None:
            self.current_archive_preview_result = pending_result
            self._refresh_archive_preview_details_text()
            self.set_status_message(
                "Textures loaded in the resident .NET/Vortice preview."
                if show_textures
                else "Textures prepared; geometry remains untextured."
            )

    def _handle_archive_resident_package_failed(
        self,
        package_path: str,
        generation: int,
        message: str,
    ) -> None:
        del package_path
        if int(generation or 0) != int(getattr(self, "_archive_texture_package_generation", 0) or 0):
            return
        self._finish_archive_texture_request(
            int(getattr(self, "_archive_texture_request_id", 0) or 0),
            success=False,
            message=str(message or "Resident package update failed."),
        )

    @staticmethod
    def _archive_package_key(package_path: object) -> str:
        try:
            return str(Path(str(package_path)).expanduser().resolve()).casefold()
        except OSError:
            return str(package_path or "").casefold()

    def _finish_archive_texture_request(self, request_id: int, *, success: bool, message: str = "") -> bool:
        if int(request_id or 0) != int(getattr(self, "_archive_texture_request_id", 0) or 0):
            return False
        self._archive_texture_request_loading = False
        self._archive_texture_request_id = 0
        self._archive_texture_request_automatic = False
        self._archive_texture_package_generation = 0
        self._archive_texture_package_path = ""
        self._archive_texture_render_settings = None
        self._archive_pending_texture_result = None
        self._archive_textures_visible = bool(success and self._archive_active_package_has_textures())
        self._sync_archive_texture_action_state()
        if not success:
            self.set_status_message(
                f"Texture loading failed; the untextured model remains available: {message}",
                error=True,
            )
        return True

    def _sync_archive_texture_action_state(self) -> None:
        checkbox = getattr(self, "archive_isolated_renderer_button", None)
        if checkbox is None:
            return
        preference_enabled = bool(
            self._current_model_preview_render_settings().use_textures_by_default
        )
        previous_blocked = checkbox.blockSignals(True)
        try:
            checkbox.setChecked(preference_enabled)
        finally:
            checkbox.blockSignals(previous_blocked)
        loading = bool(getattr(self, "_archive_texture_request_loading", False))
        if loading:
            checkbox.setText("Loading textures...")
            checkbox.setEnabled(False)
            checkbox.setToolTip("Resolving DDS materials while the current geometry remains visible.")
        else:
            checkbox.setText("Load textures")
            checkbox.setEnabled(True)
            if self._archive_active_package_has_textures() and bool(
                getattr(self, "_archive_textures_visible", False)
            ):
                checkbox.setToolTip(
                    "Uncheck to hide textures without unloading geometry. This choice is kept after restart."
                )
            else:
                checkbox.setToolTip(
                    "Check to resolve and display textures after geometry is usable. This choice is kept after restart."
                )

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
