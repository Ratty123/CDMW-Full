"""Replacement review prepared from the shared job's current documents."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from cdmw.models import ReplaceAssistantItem
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.texture_workflow.editor_export_tasks import copy_texture_editor_layer_pixels
from cdmw.ui.texture_workflow.job import _source_key


class TextureJobReviewMixin:
    def select_replacement_asset(self, path) -> None:
        key = getattr(self, "_replacement_asset_keys", {}).get(_source_key(path))
        if key not in self.job.assets:
            return
        if self.job.mode == "replace":
            self.job.active_asset_key = key
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
        if matcher is None or getattr(matcher, "_shutting_down", False):
            return
        if self.job.busy or matcher.is_busy() or (editor is not None and editor._busy()):
            return
        from cdmw.services.texture_job_service import TextureJobInput, _texture_job_original
        keys = tuple(key for key, asset in self.job.assets.items()
                     if not (asset.package_target and asset.package_target.target_kind == "material_color"))
        revisions = tuple(self.job._revision(key) for key in keys)
        if revisions == getattr(self, "_replacement_review_revisions", None):
            if callback:
                callback()
            return
        needs_editor = any(self.job.assets[key].session is not None or
                           self.job.assets[key].source_path is None for key in keys)
        if needs_editor and editor is None:
            self._with_texture_editor(lambda _editor: self.prepare_replacement_review(callback))
            return
        snapshots = []
        for key in keys:
            asset = self.job.assets[key]
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
        operation = self.job.begin("replacement_review", asset_keys=keys)
        workspace_root = Path(editor.workspace_root) if needs_editor else None
        def task():
            from cdmw.services.texture_editor_service import TextureEditorService
            prepared = []
            for key, path, document, pixels, binding, original in snapshots:
                if original is not None:
                    path = _texture_job_original(original, workspace_root / "sources" / key, None)
                    binding = replace(binding, source_path=str(path), original_dds_path=str(path))
                if document is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    TextureEditorService.export_flattened_png(document, pixels, path)
                prepared.append((key, path, binding))
            return prepared
        def complete(prepared):
            self._synchronize_texture_job()
            if not self.job.accept(operation):
                return
            items = []
            self._replacement_asset_keys = {}
            for key, path, binding in prepared:
                asset = self.job.assets[key]
                asset.binding = binding
                self._replacement_asset_keys[_source_key(path)] = key
                previous = asset.replacement_item
                if previous is not None:
                    item = replace(previous, source_path=path, source_kind=path.suffix.lower().lstrip("."))
                else:
                    # A loose DDS opened for editing is not its own original.
                    has_target = bool(binding.archive_relative_path or binding.relative_path)
                    distinct_original = bool(binding.original_dds_path and asset.source_path is not None
                                             and _source_key(binding.original_dds_path) != _source_key(asset.source_path))
                    matched = matcher._matched_original_from_binding(binding) if has_target or distinct_original else None
                    item = ReplaceAssistantItem(
                        source_path=path, source_kind=path.suffix.lower().lstrip("."),
                        detected_relative_path=binding.archive_relative_path or binding.relative_path,
                        detected_package_root=binding.package_root, matched_original=matched,
                        status="matched" if matched is not None else "pending",
                        status_detail=matched.match_reason if matched is not None else "ready to auto-match",
                    )
                asset.replacement_item = item
                items.append(item)
            matcher.items = items
            matcher._refresh_queue_tree()
            self._replacement_review_revisions = tuple(self.job._revision(key) for key in keys)
            if callback:
                callback()
        if not needs_editor:
            complete([(key, path, binding) for key, path, _doc, _pixels, binding, _original in snapshots])
            return

        results = []
        def finished():
            editor._task_finished_on_ui.disconnect(finished)
            self.set_texture_job_busy(False)
            if results and not getattr(matcher, "_shutting_down", False):
                complete(results[0])
            else:
                self.job.cancel("replacement_review")
        editor._task_finished_on_ui.connect(finished)
        if editor._run_async_task(label="Preparing replacement review...", task=task, on_success=results.append):
            self.set_texture_job_busy(True)
        else:
            finished()

    def synchronize_replacement_matches(self, matcher) -> None:
        import dataclasses
        for item in matcher.items:
            key = self.replacement_item_key(item)
            asset = self.job.assets.get(key)
            if asset is None:
                continue
            asset.replacement_item = item
            match = item.matched_original
            binding = dataclasses.replace(asset.source_binding,
                archive_relative_path=match.archive_relative_path if match else "",
                relative_path=str(match.loose_relative_path).replace("\\", "/") if match else "",
                original_dds_path=str(match.original_dds_path) if match and match.original_dds_path else "",
                package_root=match.package_root if match else "",
            )
            asset.binding = binding
            asset.original_entry = match.archive_entry if match else None
            if asset.session is not None:
                asset.session.document = dataclasses.replace(asset.session.document, source_binding=binding)
                editor = created_tool_widget(self.editor_container)
                if editor is not None and editor._active_session_index >= 0 and self.job.sessions[editor._active_session_index] is asset.session:
                    editor.document = asset.session.document
        self._refresh_texture_assets()
        self._replacement_review_revisions = None
