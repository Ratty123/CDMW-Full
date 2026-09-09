"""Library preferences and recipe inspector integration for the resident workspace."""
from __future__ import annotations

import hashlib
from dataclasses import replace

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QToolButton

from cdmw.domain.new_item.effect_authoring import EffectLook
from cdmw.ui.new_item.effect_recipe_panel import EffectRecipePanel, EffectUserLibrary
from cdmw.ui.new_item.state import EffectWorkspaceState


class EffectWorkspaceAuthoringMixin:
    def _build_library_tools(self, layout):
        self.user_library = EffectUserLibrary(getattr(self._controller, 'effect_cache_path', None))
        self.recipe_panel = None
        self._thumbnail_request = None
        row = QHBoxLayout()
        self.favourite = QToolButton()
        self.favourite.setText('☆')
        self.favourite.setToolTip('Add or remove the selected effect from favourites')
        self.favourite.clicked.connect(self._toggle_favourite)
        row.addWidget(self.favourite)
        self.favourites_only = QToolButton()
        self.favourites_only.setText('Favourites')
        self.family_only = QToolButton()
        self.family_only.setText('Variants')
        self.family_only.setToolTip('Show effects from the same named family as the selected effect')
        for button in (self.favourites_only, self.family_only):
            button.setCheckable(True)
            button.clicked.connect(self._refresh_library)
            row.addWidget(button)
        self.thumbnail = QToolButton()
        self.thumbnail.setText('Thumbnail')
        self.thumbnail.setToolTip('Use the current preview frame as this effect’s library thumbnail')
        self.thumbnail.setEnabled(False)
        self.thumbnail.clicked.connect(self._capture_thumbnail)
        row.addWidget(self.thumbnail)
        row.addStretch()
        layout.addLayout(row)
        self.large_thumbnails = QToolButton()
        self.large_thumbnails.setText('Large thumbnails')
        self.large_thumbnails.setCheckable(True)
        self.large_thumbnails.toggled.connect(self._thumbnail_size_changed)
        layout.addWidget(self.large_thumbnails)
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.setSingleShot(True)
        self._thumbnail_timer.setInterval(80)
        self._thumbnail_timer.timeout.connect(self._load_visible_thumbnails)
        self.library_view.verticalScrollBar().valueChanged.connect(lambda _: self._thumbnail_timer.start())

    def _thumbnail_size_changed(self, large):
        self.library_view.setIconSize(QSize(48,48) if large else QSize(20,20))
        self.library_view.verticalHeader().setDefaultSectionSize(56 if large else 24)
        self.library_view.horizontalHeader().resizeSection(0, 56 if large else 24)
        self._thumbnail_timer.start()

    def _load_visible_thumbnails(self):
        if self._library_closed or not self.isVisible():
            return
        first = max(0, self.library_view.rowAt(0))
        last = self.library_view.rowAt(self.library_view.viewport().height() - 1)
        last = self.library_model.rowCount() - 1 if last < 0 else last
        for index in range(first, min(last + 1, first + 40)):
            row = self.library_model.row(index)
            path = self._thumbnail_path(row.stem)
            if path and path.is_file():
                self.library_model.set_thumbnail(row.stem, QIcon(str(path)))

    @staticmethod
    def _effect_family(stem):
        # Consume variant suffixes once from the right; ambiguous regex repetitions
        # can stall the UI on catalogue names that almost match the suffix grammar.
        text = stem.casefold()
        stop = len(text) - int(text.endswith('\n'))
        end = stop
        while end:
            start = end
            letter = 'a' <= text[start - 1] <= 'z'
            if letter:
                start -= 1
                if start >= 2 and text[start - 2:start] == '__':
                    end = start - 2
                    continue
            digit_end = start
            while start and text[start - 1].isdecimal():
                start -= 1
            if start == digit_end:
                break
            # '__1a' leaves one underscore, but '__12a' can be '__1' + '2a'.
            if (not letter or digit_end - start > 1) and start >= 2 and text[start - 2:start] == '__':
                start -= 2
            elif start and text[start - 1] in '_-':
                start -= 1
            end = start
        return text[:end] + text[stop:]

    def _sync_library_tools(self, stem):
        self.favourite.setText('★' if stem in self.user_library.favourites else '☆')
        self.favourite.setEnabled(bool(stem))
        self.family_only.setEnabled(bool(stem))
        # Only read the small selected thumbnail, never thousands of images while indexing.
        path = self._thumbnail_path(stem)
        if path and path.is_file():
            self.library_model.set_thumbnail(stem, QIcon(str(path)))

    def _toggle_favourite(self):
        stem = self._staged.stem
        if not stem:
            return
        if stem in self.user_library.favourites:
            self.user_library.favourites.remove(stem)
        else:
            self.user_library.favourites.add(stem)
        self.user_library.save()
        self._refresh_library()

    def _thumbnail_path(self, stem):
        if not stem or self.user_library.path is None:
            return None
        return self.user_library.path / ('thumb_' + hashlib.sha256(stem.encode()).hexdigest()[:24] + '.png')

    def _capture_thumbnail(self):
        placement = self.placement
        path = self._thumbnail_path(self._staged.stem)
        capture = getattr(getattr(placement, 'host', None), 'capture_replacement_icon', None)
        if path is None or not callable(capture):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self._thumbnail_request = (self._staged.stem, str(path))
        if not capture(path, width=128, height=128):
            self._thumbnail_request = None

    def _thumbnail_ready(self, payload):
        if self._library_closed or not isinstance(payload, dict) or self._thumbnail_request is None:
            return
        stem, path = self._thumbnail_request
        if str(payload.get('requested_output_path') or payload.get('output_path') or '') != path:
            return
        self._thumbnail_request = None
        icon = QIcon(path)
        if not icon.isNull():
            self.library_model.set_thumbnail(stem, icon)

    def _stage_source(self, stem):
        if not stem:
            self._staged = EffectWorkspaceState.defaults()
        elif self._staged.layers is not None and self._staged.resolved_layers():
            layers = list(self._staged.resolved_layers())
            index = self._staged.active_layer
            if layers[index].stem != stem:
                layers[index] = replace(layers[index], stem=stem, look=EffectLook())
            self._staged = EffectWorkspaceState.from_layers(tuple(layers), index)
        else:
            self._staged = self._committed if stem == self._committed.stem else EffectWorkspaceState.defaults(stem)
        if self.recipe_panel is not None:
            self.recipe_panel.set_preview(None)

    def _attach_authoring(self):
        placement = self.placement
        inspector = getattr(placement, 'inspector_widget', None)
        if inspector is None:
            return
        self.recipe_panel = EffectRecipePanel(self.user_library, inspector)
        self.recipe_panel.hide()
        tabs = self.recipe_panel.tabs
        while tabs.count():
            page, title = tabs.widget(0), tabs.tabText(0)
            tabs.removeTab(0)
            page.layout().setContentsMargins(10, 8, 10, 8)
            placement._add_inspector_tab(page, title)
        self.recipe_panel.changed.connect(self._recipe_changed)
        self.recipe_panel.preview_controls.connect(self._send_effect_controls)
        placement.effect_preview_ready.connect(self.recipe_panel.set_preview)
        placement.preview_presented.connect(self._thumbnail_presented)
        host = placement.host
        signal = getattr(getattr(host, 'controller', None), 'capture_completed', None)
        if signal is not None:
            signal.connect(self._thumbnail_ready)
        self.thumbnail.setEnabled(False)

    def _thumbnail_presented(self, generation):
        self.thumbnail.setEnabled(bool(not self._library_closed and not self._preview_dirty and self.user_library.path and self._staged.stem and generation == self.placement._package_generation))

    def _send_effect_controls(self, controls):
        method = getattr(getattr(self.placement, 'host', None), 'set_effect_preview_controls', None)
        if callable(method):
            method(**controls)

    def _sync_authoring(self):
        if self.recipe_panel is not None:
            self.recipe_panel.set_state(self._staged)
        controls = {'active_layer': self._staged.active_layer}
        if self.recipe_panel is not None:
            controls['solo_layer'] = self._staged.active_layer if self.recipe_panel.solo_layer.isChecked() else -1
            controls['solo_emitter'] = self.recipe_panel.emitter.currentIndex() if self.recipe_panel.solo_emitter.isChecked() else -1
        self._send_effect_controls(controls)

    def _recipe_changed(self, state):
        if self.recipe_panel is not None and (state.stem != self._staged.stem or state.active_layer != self._staged.active_layer or state.emitter_order != self._staged.emitter_order):
            self.recipe_panel.set_preview(None)
        self._staged = state
        self._send_effect_controls({'active_layer': state.active_layer})
        self._refresh_library()
        self._sync_placement_from_state()
        self._refresh_compatibility()
        self._publish_dirty()
        self._schedule_preview()

    def _has_authored_emitters(self):
        return any(layer.look.emitters or layer.look.emitter_order is not None for layer in self._staged.resolved_layers())
