"""Publish replacement imports and remove shared assets without opening images."""

from collections import deque

from PySide6.QtWidgets import QMessageBox

from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.texture_workflow.job import TextureJobAsset, _source_key


class TextureReplacementSourcesMixin:
    def can_change_texture_sources(self) -> bool:
        editor = created_tool_widget(self.editor_container)
        matcher = created_tool_widget(self.matcher_container)
        return (not self.job.busy and not (editor is not None and editor._busy())
                and not (matcher is not None and matcher.is_busy()))

    def confirm_texture_asset_removal(self, keys) -> bool:
        if not any(self.job.assets[key].session is not None for key in keys if key in self.job.assets):
            return True
        return QMessageBox.question(
            self, "Close texture documents",
            "This will close the selected texture documents and discard their in-app edits. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes

    def remove_texture_assets(self, keys, *, confirm=True, importing=False) -> bool:
        if not importing and not self.can_change_texture_sources():
            return False
        keys = set(keys).intersection(self.job.assets)
        if confirm and not self.confirm_texture_asset_removal(keys):
            return False
        editor = created_tool_widget(self.editor_container)
        paths = {_source_key(self.job.assets[key].source_path) for key in keys
                 if self.job.assets[key].source_path is not None}
        session_ids = {id(self.job.assets[key].session) for key in keys}
        self._syncing_texture_assets = True
        try:
            if editor is not None:
                editor._close_document_tabs([
                    index for index, session in enumerate(self.job.sessions) if id(session) in session_ids
                ])
            for key in keys:
                self.job.assets.pop(key)
            self.job.selected.difference_update(keys)
            if self.job.active_asset_key in keys:
                self.job.active_asset_key = ""
            self._pending_texture_sources = deque(
                (path, binding) for path, binding in self._pending_texture_sources
                if _source_key(path) not in paths
            )
            self.job.cancel("replacement_review")
            self._replacement_review_revisions = None
            if not self.job.assets:
                self.job.recolor_analysis = None
                self._pending_texture_sources.clear()
                recolor = created_tool_widget(self.recolor_container)
                if recolor is not None:
                    recolor.analysis = None
                    recolor.current_preview_image = None
                    recolor.source_path_edit.clear()
                    recolor._sync_shared_recolor_target()
        finally:
            self._syncing_texture_assets = False
        if not importing:
            self._synchronize_texture_job()
            self.prepare_replacement_review()
        return True

    def accept_replacement_import(self, matcher, items, *, replace_job=False) -> None:
        if replace_job:
            self.remove_texture_assets(tuple(self.job.assets), confirm=False, importing=True)
        by_path = {_source_key(asset.source_path): asset for asset in self.job.assets.values()
                   if asset.source_path is not None}
        for item in items:
            identity = _source_key(item.source_path)
            if identity in by_path:
                continue
            asset = TextureJobAsset(
                item.source_path, matcher._build_texture_editor_binding(item), replacement_item=item,
            )
            by_path[identity] = asset
            self.job.assets[asset.key] = asset
            self.job.selected.add(asset.key)
        if matcher._pending_import_select_path:
            selected = by_path.get(_source_key(matcher._pending_import_select_path))
            if selected is not None:
                self.job.active_asset_key = selected.key
        matcher._pending_import_select_path = ""
        self._replacement_review_revisions = None
        self._refresh_texture_assets()

    def replacement_item_key(self, item) -> str:
        return getattr(self, "_replacement_asset_keys", {}).get(_source_key(item.source_path), "")

    def open_replacement_item(self, item) -> None:
        asset = self.job.assets.get(self.replacement_item_key(item))
        if asset is None or not self.can_change_texture_sources():
            return
        self.job.active_asset_key = asset.key
        self.set_texture_mode("edit")
        if asset.session is not None:
            def select(editor):
                editor._store_active_session()
                editor._load_session_index(self.job.sessions.index(asset.session))
            self._with_texture_editor(select)
        elif asset.source_path is not None:
            self.open_texture_sources([asset.source_path], binding=asset.source_binding)
        else:
            self._with_texture_editor(lambda editor: self.open_texture_package_asset(asset, editor))

    def set_replacement_item_included(self, item, included: bool) -> None:
        key = self.replacement_item_key(item)
        if key not in self.job.assets:
            return
        if included:
            self.job.selected.add(key)
        else:
            self.job.selected.discard(key)
        self._refresh_texture_assets()

    def replacement_build_items(self, matcher):
        return [item for item in matcher.items if self.replacement_item_key(item) in self.job.selected]
