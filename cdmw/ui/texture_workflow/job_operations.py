"""Snapshot and lock the shared texture document state for background jobs."""

from copy import deepcopy
from pathlib import Path

from cdmw.services.texture_job_service import TextureJobInput, texture_job_relative_path
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.texture_workflow.editor_export_tasks import copy_texture_editor_layer_pixels


class TextureJobOperationsMixin:
    def open_texture_package_asset(self, asset, editor) -> None:
        """Materialize a selected mod texture using its own package provenance."""
        from dataclasses import replace
        from PySide6.QtCore import QTimer
        from cdmw.services.texture_job_service import materialize_texture_package_asset

        if editor._busy():
            return
        package_path, target = asset.package_path, asset.package_target
        binding = asset.source_binding
        destination = Path(editor.workspace_root) / "sources" / asset.key
        operation = self.job.begin("open_package_texture", asset_keys=(asset.key,))

        def completed(path):
            if not self.job.accept(operation):
                return
            source_binding = replace(binding, source_path=str(path), original_dds_path=str(path))
            asset.source_path = path
            asset.binding = source_binding
            if self.job.active_asset_key == asset.key:
                QTimer.singleShot(0, self, lambda: self.open_texture_sources([path], binding=source_binding))

        editor._run_async_task(
            label="Opening mod texture...",
            task=lambda: materialize_texture_package_asset(package_path, target, destination),
            on_success=completed,
        )

    def capture_texture_job_inputs(self, *, package_only: bool = False):
        self._synchronize_texture_job()
        editor = created_tool_widget(self.editor_container)
        if editor is not None and getattr(editor, "_task_thread", None) is not None:
            raise ValueError("Wait for the texture operation to finish before exporting.")
        inputs = []
        for key, asset in self.job.assets.items():
            if key not in self.job.selected:
                continue
            target = asset.package_target
            if target is not None and target.target_kind == "material_color":
                continue
            if package_only and (target is None or asset.package_path != Path(self.job.recolor_analysis.package_path)):
                continue
            binding = asset.source_binding
            relative = binding.relative_path if Path(binding.relative_path).suffix.lower() == ".dds" else binding.archive_relative_path
            session = asset.session
            if package_only and session is None:
                continue  # The package engine already owns this original payload.
            texture_job_relative_path(relative)
            original = binding.original_dds_path or (str(asset.source_path) if asset.source_path and asset.source_path.suffix.lower() == ".dds" else "")
            archive_entry = asset.original_entry
            if not original and archive_entry is None and relative:
                archive_entry = self._find_archive_entry_for_workflow_relative_path(relative)
            if not original and archive_entry is None and asset.package_path is None:
                raise ValueError(f"Match {asset.label} to its original DDS in Review & Export first.")
            edited = session is not None and (session.history_index > 0 or (asset.source_path and asset.source_path.suffix.lower() != ".dds"))
            inputs.append(TextureJobInput(
                relative, Path(original) if original else None, deepcopy(session.document) if edited else None,
                copy_texture_editor_layer_pixels(session.layer_pixels) if edited else None,
                original_entry=archive_entry, package_path=asset.package_path, package_target=target,
            ))
        return tuple(inputs)

    def begin_texture_operation(self, kind: str):
        self._synchronize_texture_job()
        if getattr(self, "_texture_export_kind", ""):
            raise ValueError("A texture export is already running.")
        if self.shell._background_task_active():
            raise ValueError("Wait for the current background operation before exporting.")
        editor = created_tool_widget(self.editor_container)
        if editor is not None and getattr(editor, "_task_thread", None) is not None:
            raise ValueError("Wait for the texture operation to finish before exporting.")
        self._texture_export_kind = kind
        operation = self.job.begin(kind)
        self._texture_export_operation = operation
        self.set_texture_job_busy(True)
        return operation

    def set_texture_job_busy(self, busy: bool) -> None:
        busy = busy or bool(getattr(self, "_texture_export_kind", ""))
        self.job.busy = busy
        if not hasattr(self, "asset_list"):
            return
        for widget in (self.asset_list, self.add_texture_button, self.add_mod_button, self.remove_texture_button, self.editor_container):
            widget.setEnabled(not busy)
        for controls in (self._editor_controls, self._recolor_controls, self.upscale_controls):
            if controls is not None:
                controls.setEnabled(not busy)
        matcher = created_tool_widget(self.matcher_container)
        if matcher is not None:
            matcher.set_external_busy(busy)
        if hasattr(self, "editor_export_page"):
            self.editor_export_page.setEnabled(not busy)

    def finish_texture_operation(self, value=None) -> bool:
        operation = getattr(self, "_texture_export_operation", None)
        if operation is None:
            return True
        self._synchronize_texture_job()
        accepted = self.job.complete(operation, value) if value is not None else False
        if value is None:
            self.job.cancel(operation.kind)
        self._texture_export_operation = None
        self._texture_export_kind = ""
        self.set_texture_job_busy(False)
        self._queue_next_texture_source()
        return accepted
