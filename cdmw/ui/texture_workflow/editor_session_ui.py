from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from cdmw.models import TextureEditorDocument, TextureEditorSourceBinding
from cdmw.ui.texture_workflow.editor_session import (
    create_texture_editor_session,
    texture_editor_document_key,
    texture_editor_open_document_ids,
    texture_editor_session_close_state,
    texture_editor_session_tab_state,
)
from cdmw.ui.texture_workflow.editor_source_binding import (
    build_texture_editor_source_binding,
    configured_texture_editor_root_path,
)


class TextureEditorSessionUiMixin:
    """Own Texture Editor document-session and tab-bar coordination."""

    def _store_active_session(self) -> None:
        if self._switching_session:
            return
        if not (0 <= self._active_session_index < len(self._sessions)):
            return
        if self._adjustment_property_dirty:
            self.commit_selected_adjustment_properties()
        session = self._sessions[self._active_session_index]
        session.document = self.document
        session.layer_pixels = self.layer_pixels
        session.history_snapshots = self.history_snapshots
        session.history_index = self.history_index
        session.layer_property_dirty = self._layer_property_dirty
        session.floating_pixels = None if self._floating_pixels is None else self._floating_pixels.copy()
        session.floating_mask = None if self._floating_mask is None else self._floating_mask.copy()
        session.composite_cache = None if self._composite_cache is None else self._composite_cache.copy()
        session.composite_cache_revision = self._composite_cache_revision
        session.composite_dirty_bounds = self._composite_dirty_bounds
        session.thumbnail_cache = dict(self._thumbnail_cache)
        session.label = self.document.title if self.document is not None else session.label
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()
        self._sync_document_tab_label(self._active_session_index)

    def _sync_document_tab_label(self, index: int) -> None:
        if not (0 <= index < len(self._sessions)):
            return
        state = texture_editor_session_tab_state(self._sessions[index], index)
        self.document_tab_bar.setTabText(index, state.label)
        self.document_tab_bar.setTabToolTip(index, state.tooltip)

    def _load_session_index(self, index: int) -> None:
        self._switching_session = True
        try:
            if not (0 <= index < len(self._sessions)):
                self._active_session_index = -1
                self.document = None
                self.layer_pixels = {}
                self.history_snapshots = []
                self.history_index = -1
                self._layer_property_dirty = False
                self._floating_pixels = None
                self._floating_mask = None
                self._composite_cache = None
                self._composite_cache_revision = -1
                self._composite_dirty_bounds = None
                self._thumbnail_cache = {}
                self.document_tab_bar.blockSignals(True)
                self.document_tab_bar.setCurrentIndex(-1)
                self.document_tab_bar.blockSignals(False)
                self._refresh_ui()
                return
            self._active_session_index = index
            session = self._sessions[index]
            self.document = session.document
            self.layer_pixels = session.layer_pixels
            self.history_snapshots = session.history_snapshots
            self.history_index = session.history_index
            self._layer_property_dirty = session.layer_property_dirty
            self._floating_pixels = None if session.floating_pixels is None else session.floating_pixels.copy()
            self._floating_mask = None if session.floating_mask is None else session.floating_mask.copy()
            self._composite_cache = None if session.composite_cache is None else session.composite_cache.copy()
            self._composite_cache_revision = session.composite_cache_revision
            self._composite_dirty_bounds = session.composite_dirty_bounds
            self._thumbnail_cache = dict(session.thumbnail_cache)
            self.document_tab_bar.blockSignals(True)
            self.document_tab_bar.setCurrentIndex(index)
            self.document_tab_bar.blockSignals(False)
            self._sync_document_tab_label(index)
            self.workspace = dataclasses.replace(
                self.workspace,
                open_document_ids=texture_editor_open_document_ids(self._sessions),
                active_document_id=texture_editor_document_key(self.document),
            )
            self._apply_view_state(self.workspace.document_view_state.get(texture_editor_document_key(self.document)))
            self._refresh_ui()
        finally:
            self._switching_session = False

    def _create_session(self, document: TextureEditorDocument, layer_pixels: Dict[str, np.ndarray], *, label: str) -> None:
        self._store_active_session()
        session = create_texture_editor_session(document, layer_pixels, label=label)
        self._sessions.append(session)
        self.document_tab_bar.addTab(label)
        self.document_tab_bar.show()
        self.workspace = dataclasses.replace(
            self.workspace,
            open_document_ids=texture_editor_open_document_ids(self._sessions),
        )
        self._load_session_index(len(self._sessions) - 1)

    def _handle_document_tab_changed(self, index: int) -> None:
        if self._switching_session or index == self._active_session_index:
            return
        self._store_active_session()
        self._load_session_index(index)

    def _close_document_tab(self, index: int) -> None:
        if not (0 <= index < len(self._sessions)):
            return
        self._store_active_session()
        close_state = texture_editor_session_close_state(
            session_count_before=len(self._sessions),
            active_index=self._active_session_index,
            closed_index=index,
        )
        self.document_tab_bar.blockSignals(True)
        self.document_tab_bar.removeTab(index)
        self.document_tab_bar.blockSignals(False)
        self._sessions.pop(index)
        self.workspace = dataclasses.replace(
            self.workspace,
            open_document_ids=texture_editor_open_document_ids(self._sessions),
        )
        if not self._sessions:
            self.document_tab_bar.hide()
            self._load_session_index(-1)
            self._set_status(close_state.status_message, False)
            return
        self._active_session_index = close_state.adjusted_active_index
        self._load_session_index(close_state.next_index)
        self.document_tab_bar.show()

    def _build_binding_for_source(
        self,
        source_path: Path,
        *,
        launch_origin: str,
        binding: Optional[TextureEditorSourceBinding] = None,
    ) -> TextureEditorSourceBinding:
        return build_texture_editor_source_binding(
            source_path,
            launch_origin=launch_origin,
            binding=binding,
            png_root=configured_texture_editor_root_path(self.get_png_root),
            original_root=configured_texture_editor_root_path(self.get_original_dds_root),
        )
