"""Replacement review prepared from the shared job's current documents."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.texture_workflow.editor_export_tasks import copy_texture_editor_layer_pixels


class TextureJobReviewMixin:
    def select_replacement_asset(self, path) -> None:
        key = getattr(self, "_replacement_asset_keys", {}).get(str(Path(path).resolve()).casefold())
        if key not in self.job.assets:
            return
        for index in range(self.asset_list.topLevelItemCount()):
            item = self.asset_list.topLevelItem(index)
            from PySide6.QtCore import Qt
            if item.data(0, Qt.UserRole) == key:
                self.asset_list.setCurrentItem(item)
                break

    def prepare_replacement_review(self, callback=None) -> None:
        self._synchronize_texture_job()
        editor = created_tool_widget(self.editor_container)
        matcher = created_tool_widget(self.matcher_container)
        if editor is None or matcher is None or not hasattr(editor, "job"):
            return
        if editor._busy() or matcher.is_busy():
            return
        from cdmw.services.texture_job_service import TextureJobInput, _texture_job_original
        revisions = tuple(self.job._revision(key) for key in sorted(self.job.selected))
        if revisions == getattr(self, "_replacement_review_revisions", None):
            if callback:
                callback()
            return
        snapshots = []
        for key, asset in self.job.assets.items():
            if key not in self.job.selected or (asset.package_target and asset.package_target.target_kind == "material_color"):
                continue
            session = asset.session
            if session is not None:
                destination = Path(editor.workspace_root) / "review" / key / (Path(session.label).stem + ".png")
                snapshots.append((key, destination, deepcopy(session.document), copy_texture_editor_layer_pixels(session.layer_pixels), asset.source_binding, None))
            elif asset.source_path is not None:
                snapshots.append((key, asset.source_path, None, None, asset.source_binding, None))
            elif asset.package_path is not None:
                destination = Path(editor.workspace_root) / "review" / key / "texture.png"
                original = TextureJobInput(asset.source_binding.relative_path, None,
                    package_path=asset.package_path, package_target=asset.package_target)
                snapshots.append((key, destination, None, None, asset.source_binding, original))
        operation = self.job.begin("replacement_review")
        workspace_root = Path(editor.workspace_root)
        def task():
            from cdmw.services.texture_editor_service import TextureEditorService
            prepared = []
            for key, path, document, pixels, binding, original in snapshots:
                if original is not None:
                    path = _texture_job_original(original, workspace_root / "sources" / key, None)
                    binding = replace(binding, source_path=str(path), original_dds_path=str(path))
                if document is None and path.suffix.lower() == ".dds":
                    document, pixels, _png = TextureEditorService.create_document_from_source(
                        path, workspace_root=workspace_root, binding=binding,
                    )
                    binding = document.source_binding
                    path = workspace_root / "review" / key / (path.stem + ".png")
                if document is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    TextureEditorService.export_flattened_png(document, pixels, path)
                prepared.append((key, path, binding))
            return prepared
        def complete(prepared):
            self._synchronize_texture_job()
            if not self.job.accept(operation):
                return
            previous_matches = {str(item.source_path.resolve()).casefold(): item.matched_original for item in matcher.items}
            matcher.items.clear()
            self._replacement_asset_keys = {}
            for key, path, binding in prepared:
                self.job.assets[key].binding = binding
                self._replacement_asset_keys[str(path.resolve()).casefold()] = key
                matched = previous_matches.get(str(path.resolve()).casefold()) or matcher._matched_original_from_binding(binding)
                matcher.accept_editor_export_prepared(path, binding, matched)
            self._replacement_review_revisions = tuple(self.job._revision(key) for key in sorted(self.job.selected))
            if callback:
                # The editor's worker refs are cleared on its next queued signal.
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self, callback)
        editor._run_async_task(label="Preparing replacement review...", task=task, on_success=complete)

    def synchronize_replacement_matches(self, matcher) -> None:
        import dataclasses
        for item in matcher.items:
            key = getattr(self, "_replacement_asset_keys", {}).get(str(item.source_path.resolve()).casefold())
            asset = self.job.assets.get(key)
            if asset is None or item.matched_original is None:
                continue
            match = item.matched_original
            binding = dataclasses.replace(asset.source_binding,
                archive_relative_path=match.archive_relative_path,
                relative_path=str(match.loose_relative_path).replace("\\", "/"),
                original_dds_path=str(match.original_dds_path) if match.original_dds_path else asset.source_binding.original_dds_path,
                package_root=match.package_root,
            )
            asset.binding = binding
            asset.original_entry = match.archive_entry
            if asset.session is not None:
                asset.session.document = dataclasses.replace(asset.session.document, source_binding=binding)
                editor = created_tool_widget(self.editor_container)
                if editor is not None and editor._active_session_index >= 0 and self.job.sessions[editor._active_session_index] is asset.session:
                    editor.document = asset.session.document
        self._refresh_texture_assets()
