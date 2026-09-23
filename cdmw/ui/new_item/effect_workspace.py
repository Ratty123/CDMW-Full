"""Guided Step 5 visual-effect library, staging, placement and look controls."""

from __future__ import annotations

import tempfile
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Optional

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.new_item_effect_search import filter_effect_rows
from cdmw.workers.new_item_lookup import NewItemLookupLane

from PySide6.QtCore import QModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from cdmw.ui.new_item.state import EffectWorkspaceState
from cdmw.ui.new_item.effect_workspace_authoring import EffectWorkspaceAuthoringMixin

__all__ = [
    "CATEGORY_RULES",
    "EffectLibraryModel",
    "GuidedEffectsWorkspace",
    "effect_category",
    "effect_display_label",
]


from cdmw.ui.new_item.effect_library_model import (  # noqa: F401 - compatibility exports
    CATEGORY_RULES, CATEGORY_GLYPHS, EffectLibraryRow, EffectLibraryModel,
    effect_category, effect_display_label, _unique_effect_labels, _effect_dimensions,
)

_CHARACTER_RIGS = ("", "1_phm", "2_phw")


class GuidedEffectsWorkspace(EffectWorkspaceAuthoringMixin, QWidget):
    """The complete resident Effects tab; edits stay staged until Apply placement."""

    staged_changed = Signal(bool)
    applied = Signal(object)

    def _build_library_view(self, library_layout):
        self.library_view = QTableView()
        self.library_view.setObjectName("effect_library")
        self.library_view.setModel(self.library_model)
        self.library_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.library_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.library_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.library_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.library_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.library_view.setWordWrap(False)
        self.library_view.setMouseTracking(True)
        self.library_view.setAlternatingRowColors(True)
        self.library_view.setShowGrid(False)
        self.library_view.setCornerButtonEnabled(False)
        vertical_header = self.library_view.verticalHeader()
        vertical_header.setVisible(False)
        vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical_header.setMinimumSectionSize(20)
        vertical_header.setDefaultSectionSize(24)
        horizontal_header = self.library_view.horizontalHeader()
        horizontal_header.setFixedHeight(22)
        horizontal_header.setMinimumSectionSize(20)
        horizontal_header.setStretchLastSection(False)
        # Bound metadata sizing even before the hidden page has a viewport layout.
        horizontal_header.setResizeContentsPrecision(32)
        horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        horizontal_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        horizontal_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.library_view.selectionModel().currentChanged.connect(self._library_selection_changed)
        library_layout.addWidget(self.library_view, 1)


    def __init__(
        self,
        controller: NewItemStudioController,
        parent: Optional[QWidget] = None,
        *,
        placement_factory=EffectPlacementWorkspace,
        host_factory=None,
        confirm_unreviewed=None,
    ) -> None:
        super().__init__(parent)
        self._initialize_state(controller, placement_factory, host_factory, confirm_unreviewed)

        self._configure_preview_timers()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        # The assembled page hosts these controls beside the existing Effects tab.
        self.library_controls = QWidget()
        header = QHBoxLayout(self.library_controls)
        header.setContentsMargins(4, 0, 4, 0)
        header.setSpacing(6)
        self.library_toggle = QToolButton()
        self.library_toggle.setObjectName("effect_library_toggle")
        self.library_toggle.setText("Browse effects")
        self.library_toggle.setCheckable(True)
        self.library_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.library_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.library_toggle.toggled.connect(
            lambda expanded: self.library_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        )
        header.addWidget(self.library_toggle)
        self.search = QLineEdit()
        self.search.setObjectName("effect_search")
        self.search.setPlaceholderText("Search effects…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._refresh_library)
        self.search.textEdited.connect(lambda _text: self.library_toggle.setChecked(True))
        self.category_choice = QComboBox()
        for category in ("All", *(name for name, _tokens in CATEGORY_RULES), "Other"):
            self.category_choice.addItem(category, category)
        self.category_choice.currentIndexChanged.connect(self._refresh_library)
        self.category_choice.activated.connect(lambda _index: self.library_toggle.setChecked(True))
        self.selected_effect_label = QLabel("No effect")
        self.selected_effect_label.setTextFormat(Qt.TextFormat.PlainText)
        self.selected_effect_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.selected_effect_label.setMinimumWidth(100)
        self.selected_effect_label.setMaximumWidth(240)
        header.addWidget(self.selected_effect_label, 1)
        layout.addWidget(self.library_controls)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("effect_workspace_splitter")
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

        library = QFrame()
        self.library_panel = library
        library.setObjectName("effect_library_panel")
        library.setMinimumWidth(300)
        self.library_toggle.toggled.connect(library.setVisible)
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(8, 4, 8, 4)
        library_layout.setSpacing(4)
        title_row = QHBoxLayout()
        title = QLabel("Effect Library")
        title.setObjectName("effect_library_heading")
        title_row.addWidget(title)
        self.library_count = QLabel("")
        self.library_count.setObjectName("effect_library_count")
        title_row.addWidget(self.library_count, 1, Qt.AlignmentFlag.AlignRight)
        library_layout.addLayout(title_row)
        library_layout.addWidget(self.search)
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.behavior_group = QButtonGroup(self)
        self.behavior_group.setExclusive(True)
        self.behavior_all = QToolButton()
        self.behavior_all.setText("All")
        self.behavior_all.setToolTip("Show loop and one-shot effects")
        self.loop_only = QToolButton()
        self.loop_only.setText("Loops")
        self.loop_only.setToolTip("Show loops only")
        self.one_shot_only = QToolButton()
        self.one_shot_only.setText("One-shot")
        self.one_shot_only.setToolTip("Show one-shot effects only")
        for button in (self.behavior_all, self.loop_only, self.one_shot_only):
            button.setCheckable(True)
            button.setProperty("effectChip", True)
            button.clicked.connect(self._refresh_library)
            self.behavior_group.addButton(button)
            search_row.addWidget(button)
        self.behavior_all.setChecked(True)
        search_row.addWidget(self.category_choice)
        search_row.addStretch(1)
        library_layout.addLayout(search_row)
        self.compatibility_label = QLabel("")
        self.compatibility_label.setObjectName("effect_compatibility")
        self.compatibility_label.setWordWrap(True)
        self.compatibility_label.setVisible(False)

        self.library_model = EffectLibraryModel(self)
        self._build_library_view(library_layout)
        self._build_library_tools(library_layout)
        self.empty_results = QLabel("No matching effects. Change or reset the filters.")
        self.empty_results.setWordWrap(True)
        self.empty_results.setVisible(False)
        library_layout.addWidget(self.empty_results)
        self.reset_filters = QToolButton()
        self.reset_filters.setText("Reset filters")
        self.reset_filters.setAutoRaise(True)
        self.reset_filters.clicked.connect(self._reset_filters)
        self.library_tools.addWidget(self.reset_filters)
        self.selection_detail = QLabel("")
        self.selection_detail.setObjectName("effect_selection_detail")
        self.selection_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.selection_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.selection_detail.setToolTip("Exact shipped effect stem")
        self.selection_detail.setVisible(False)
        library_layout.addWidget(self.selection_detail)

        self.placement_holder = QWidget()
        self.placement_holder.setMinimumWidth(820)
        self.placement_layout = QVBoxLayout(self.placement_holder)
        self.placement_layout.setContentsMargins(0, 0, 0, 0)
        self._build_character_fit_row()
        self.placeholder = QLabel("Choose a template to prepare the resident placement viewport.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placement_layout.addWidget(self.placeholder, 1)
        self.placement: Optional[EffectPlacementWorkspace] = None

        self.splitter.addWidget(library)
        self.splitter.addWidget(self.placement_holder)
        self.splitter.setStretchFactor(0, 29)
        self.splitter.setStretchFactor(1, 71)
        self.splitter.setSizes([380, 930])
        self.library_toggle.setChecked(True)

        self.caution = QLabel("Visual only  •  Approximate preview  •  Verify final fit in game")
        self.caution.setObjectName("effect_visual_caution")
        self.caution.setContentsMargins(8, 2, 8, 2)
        self.caution.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self.caution)
        status_row.addWidget(self.compatibility_label, 1)
        layout.addLayout(status_row)

        self._wire_controller()

    def _initialize_state(self, controller, placement_factory, host_factory, confirm_unreviewed) -> None:
        self._controller = controller
        self._placement_factory = placement_factory
        self._host_factory = host_factory
        self._confirm_unreviewed = confirm_unreviewed or self._default_unreviewed_confirmation
        self._committed = EffectWorkspaceState.from_draft(controller.draft)
        self._staged = self._committed
        self._syncing = False
        self._reset_view_next = True
        self._preview_template_key = controller.draft.template_key
        self._preview_dirty = True
        self._preview_retry_remaining = 1
        self._placement_position = self._committed.offset if self._committed.stem else None
        self._placement_root = Path(tempfile.mkdtemp(prefix="cdmw_effect_workspace_"))
        self._label_by_stem: dict[str, str] = {}
        self._library_rows: dict[str, EffectLibraryRow] = {}
        self._library_build = None
        self._library_snapshot = None
        self._library_closed = False
        self._library_dirty = False
        self._library_request_key = None
        self._library_build_lane = NewItemLookupLane(parent=self)
        self._library_build_lane.completed.connect(self._library_prepared)
        self._library_build_lane.failed.connect(self._library_failed)
        self._library_search_lane = NewItemLookupLane(parent=self)
        self._library_search_lane.completed.connect(self._library_filtered)
        self._library_search_lane.failed.connect(self._library_failed)

    def _configure_preview_timers(self) -> None:
        self._library_timer = QTimer(self)
        self._library_timer.setInterval(16)
        self._library_timer.timeout.connect(self._advance_library)
        self.selection_timer = QTimer(self)
        self.selection_timer.setSingleShot(True)
        self.selection_timer.setInterval(150)
        self.selection_timer.timeout.connect(self._rebuild_preview)
        self.look_timer = QTimer(self)
        self.look_timer.setSingleShot(True)
        self.look_timer.setInterval(250)
        self.look_timer.timeout.connect(self._rebuild_preview)
        self._initial_preview_timer = QTimer(self)
        self._initial_preview_timer.setSingleShot(True)
        self._initial_preview_timer.setInterval(0)
        self._initial_preview_timer.timeout.connect(self._rebuild_preview)

    def _build_character_fit_row(self) -> None:
        self.character_fit_row = QWidget(self.placement_holder)
        self.character_fit_row.setObjectName("effect_character_fit_row")
        character_fit_layout = QHBoxLayout(self.character_fit_row)
        character_fit_layout.setContentsMargins(0, 0, 0, 0)
        character_fit_layout.setSpacing(6)
        self.character_fit_choice = QComboBox()
        self.character_fit_choice.setObjectName("effect_character_fit_choice")
        self.character_fit_choice.setAccessibleName("Character")
        self.character_fit_choice.addItem("Auto", 0)
        self.character_fit_choice.addItem("Kliff", 1)
        self.character_fit_choice.addItem("Damian", 2)
        self.character_fit_choice.setToolTip(
            "The game's own character provides a size reference for the item and effect."
        )
        self.character_fit_choice.setEnabled(self._controller.draft.template_key is not None)
        self.character_fit_choice.currentIndexChanged.connect(self._character_fit_changed)
        character_fit_layout.addWidget(self.character_fit_choice)

    def _wire_controller(self) -> None:
        controller = self._controller
        controller.effect_catalogue_progress.connect(self._catalogue_progress)
        controller.effect_catalogue_ready.connect(self._catalogue_ready)
        controller.effect_catalogue_failed.connect(self._catalogue_failed)
        ready = getattr(controller, "effect_compatibility_ready", None)
        if ready is not None:
            ready.connect(self._refresh_compatibility)
        controller.effect_changed.connect(self._effect_committed_elsewhere)
        controller.template_changed.connect(self._source_changed)
        controller.model_import_changed.connect(self._source_changed)
        controller.model_changed.connect(self._source_changed)
        controller.model_placement_changed.connect(self._source_changed)
        self._preview_appearance = self._appearance_state()
        invalidated = getattr(controller, "plan_invalidated", None)
        if invalidated is not None:
            invalidated.connect(self._appearance_changed)
        snapshot_ready = getattr(controller, "snapshot_ready", None)
        if snapshot_ready is not None:
            snapshot_ready.connect(self._start_library)
        self._start_library()

    @property
    def staged_state(self) -> EffectWorkspaceState:
        return self._staged

    def has_staged_changes(self) -> bool:
        return self._staged.resolved_layers() != self._committed.resolved_layers()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if self._library_dirty:
            self._refresh_library()
        self._refresh_compatibility()
        needs_preview = (
            self._preview_dirty
            or self.placement is None
            or bool(getattr(self.placement, "_content_failed", False))
            or bool(getattr(self.placement, "_renderer_failed", False))
        )
        if self._controller.draft.template_key is not None and needs_preview:
            self._preview_retry_remaining = 1
            self.selection_timer.stop()
            self._initial_preview_timer.start()

    def choose_effect(self, stem: str, *, scale: float = 1.0) -> None:
        """Stage a shipped effect while keeping the current placement position."""

        clean = str(stem or "").strip()
        self._stage_source(clean)
        self._refresh_selection_detail(clean)
        self._refresh_library()
        self._select_stem(clean)
        self._sync_placement_from_state()
        self._refresh_compatibility()
        self._publish_dirty()
        self._schedule_preview()

    def apply_staged(self) -> bool:
        if not str(self._staged.stem or "").strip():
            self._staged = EffectWorkspaceState.defaults()
        if not self.has_staged_changes():
            self._publish_dirty()
            return True
        checks = [self._controller.effect_target_compatibility(layer.stem)
                  for layer in self._staged.resolved_layers() if layer.enabled]
        if any(value is None or not value.supported for value in checks):
            self._refresh_compatibility()
            return False
        placement = self.placement
        if placement is not None and getattr(placement, '_content_failed', False) and self._has_authored_emitters():
            return False
        reviewed = placement is not None and placement.host is not None and not getattr(placement, "_renderer_failed", False)
        if self._staged.stem and not reviewed:
            reason = "The resident renderer is unavailable."
            if placement is not None:
                reason = str(getattr(placement, "_host_error", "") or placement.status.text() or reason)
            if not self._confirm_unreviewed(reason):
                return False
        self._controller.commit_effect_workspace(self._staged)
        self._committed = EffectWorkspaceState.from_draft(self._controller.draft)
        self._staged = self._committed
        self._publish_dirty()
        self.applied.emit(self._committed)
        return True

    def discard_staged(self) -> None:
        self._staged = self._committed
        self._placement_position = self._committed.offset if self._committed.stem else None
        self._refresh_library()
        self._select_stem(self._staged.stem)
        self._sync_placement_from_state()
        self._refresh_compatibility()
        self._publish_dirty()
        self._schedule_preview()

    def _default_unreviewed_confirmation(self, reason: str) -> bool:
        answer = QMessageBox.warning(
            self,
            "Placement was not visually reviewed",
            f"{reason}\n\nApply these numeric placement values without a visual review?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _active_category(self) -> str:
        return str(self.category_choice.currentData() or "All")

    def _start_library(self, *_args) -> None:
        """Prepare a replacement catalogue without touching widgets on its worker."""
        if self._library_closed:
            return
        self._library_snapshot = getattr(self._controller, "snapshot", None)
        catalogue = getattr(self._controller, "effect_catalogue", None)
        stems = (catalogue.facts if catalogue else self._library_snapshot.effect_stems
                 if self._library_snapshot is not None else self._controller.effect_stems("", limit=None))
        facts = catalogue.get if catalogue else self._controller.effect_facts
        self._library_search_lane.cancel()
        self._library_request_key = None
        self._library_build = True
        def prepare(stop_event):
            rows, groups = {}, {}
            for index, stem in enumerate(stems):
                if index % 64 == 0:
                    raise_if_cancelled(stop_event)
                row = EffectLibraryRow.from_stem(stem, facts(stem))
                rows[stem] = row
                groups.setdefault(row.label.casefold(), []).append(stem)
            for grouped in groups.values():
                raise_if_cancelled(stop_event)
                if len(grouped) > 1:
                    for stem, label in _unique_effect_labels(tuple(grouped)).items():
                        rows[stem] = replace(rows[stem], label=label)
            return rows, {stem: row.label for stem, row in rows.items()}
        self._library_build_lane.request(id(self._library_snapshot), prepare)
        self.library_count.setText("Loading effects…")
        self._library_timer.start()

    def _library_prepared(self, _key, result):
        self._library_rows, self._label_by_stem = result
        self._library_build = None
        self._refresh_library(force=True)

    def _advance_library(self) -> None:
        if not self._library_build_lane.busy and not self._library_search_lane.busy:
            self._library_timer.stop()

    def _library_failed(self, _key, message):
        self._library_build = None
        self._library_request_key = None
        self.library_count.setText(f"Effects could not be loaded: {message}")

    def _refresh_library(self, *_args, force=False) -> None:
        if self._library_closed:
            return
        if not force and not self.isVisible():
            self._library_dirty = True
            return
        self._library_dirty = False
        selected = self._staged.stem
        terms = tuple(self.search.text().casefold().split())
        candidates = self._library_rows
        if selected and selected not in candidates:
            extra = EffectLibraryRow.from_stem(selected, self._controller.effect_facts(selected))
        else:
            extra = None
        category = self._active_category()
        loop_only = self.loop_only.isChecked()
        one_shot_only = self.one_shot_only.isChecked()
        favourites = frozenset(self.user_library.favourites) if self.favourites_only.isChecked() else None
        family = self._effect_family(selected) if self.family_only.isChecked() else None
        key = (id(candidates), selected, terms, category, loop_only, one_shot_only, favourites, family)
        if key == self._library_request_key:
            return
        self._library_request_key = key
        previous = self.library_model._rows
        family_of = self._effect_family
        def match_effect_library(stop_event):
            rows = {**candidates, selected: extra} if extra is not None else candidates
            return filter_effect_rows(rows, selected=selected, terms=terms, category=category,
                                      loop_only=loop_only, one_shot_only=one_shot_only, favourites=favourites,
                                      family=family, family_of=family_of, previous_rows=previous,
                                      no_effect=EffectLibraryRow("", "No effect", "Other", "Off"), stop_event=stop_event)
        self._library_search_lane.request(key, match_effect_library, delay_ms=0 if force else 150)
        self.library_count.setText("Searching effects…")
        self._library_timer.start()
        self.reset_filters.setVisible(bool(terms) or category != "All" or not self.behavior_all.isChecked() or self.favourites_only.isChecked() or self.family_only.isChecked())

    def _library_filtered(self, key, result):
        if key != self._library_request_key:
            return
        rows, stem_rows, matches = result
        self._syncing = True
        try:
            self.library_model.replace_rows(rows, stem_rows=stem_rows)
            self._select_stem(self._staged.stem)
            self._refresh_selection_detail(self._staged.stem)
        finally:
            self._syncing = False
        self.library_count.setText(self.tr("{count} effects").format(count=matches))
        self.empty_results.setVisible(matches == 0)

    def _reset_filters(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.behavior_all.setChecked(True)
        self.category_choice.blockSignals(True)
        self.category_choice.setCurrentIndex(0)
        self.category_choice.blockSignals(False)
        self.favourites_only.setChecked(False)
        self.family_only.setChecked(False)
        self._refresh_library()

    def _select_stem(self, stem: str) -> None:
        index = self.library_model.index_for_stem(stem)
        if index.isValid() and index != self.library_view.currentIndex():
            self.library_view.setCurrentIndex(index)
            self.library_view.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    def _library_selection_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._syncing or not current.isValid():
            return
        stem = str(current.data(EffectLibraryModel.StemRole) or "")
        self._refresh_selection_detail(stem)
        self._stage_source(stem)
        self._sync_placement_from_state()
        self._refresh_compatibility()
        self._publish_dirty()
        self._schedule_preview()

    def _refresh_selection_detail(self, stem: str) -> None:
        exact = str(stem or "").strip()
        index = self.library_model.index_for_stem(exact)
        tooltip = self.library_model.data(index, int(Qt.ItemDataRole.ToolTipRole)) if index.isValid() and exact else exact
        self.selection_detail.setText(exact)
        self.selection_detail.setToolTip(tooltip)
        self.selection_detail.setVisible(bool(exact))
        self.selected_effect_label.setText(self._label_by_stem.get(exact, effect_display_label(exact)) if exact else self.tr("No effect"))
        self.selected_effect_label.setToolTip(tooltip)
        self._sync_library_tools(exact)

    def _sync_placement_from_state(self) -> None:
        placement = self.placement
        if placement is None:
            return
        facts = self._controller.effect_facts(self._staged.stem)
        decoder_reason = facts.walk_note if facts is not None and facts.walk_note else ""
        if decoder_reason and (
            self._staged.color is not None
            or any(
                abs(value - 1.0) > 1e-9
                for value in (
                    self._staged.intensity,
                    self._staged.size,
                    self._staged.rate,
                    self._staged.lifetime,
                )
            )
        ):
            self._staged = replace(
                self._staged,
                color=None,
                intensity=1.0,
                size=1.0,
                rate=1.0,
                lifetime=1.0,
            )
        if self._staged.stem and self._placement_position is not None:
            self._placement_position = self._staged.offset
        position = self._placement_position if self._placement_position is not None else self._staged.offset
        was_syncing, self._syncing = self._syncing, True
        try:
            placement._set_numbers(position, self._staged.scale, self._staged.rotation)
        finally:
            self._syncing = was_syncing
        if self._staged.stem:
            self._staged = replace(self._staged, offset=placement.offset, scale=placement.scale, rotation=placement.rotation)
            if self._placement_position is not None:
                self._placement_position = placement.offset
        placement.set_look(
            color=self._staged.color,
            intensity=self._staged.intensity,
            particle_size=self._staged.size,
            spawn_rate=self._staged.rate,
            lifetime=self._staged.lifetime,
        )
        placement.set_decoder_reason(decoder_reason)
        self._sync_authoring()
        self._publish_dirty()

    def _placement_transform_changed(self) -> None:
        if self._syncing or self.placement is None:
            return
        placement = self.placement
        self._placement_position = tuple(float(value) for value in placement.offset)
        self._staged = replace(
            self._staged,
            scale=float(placement.scale),
            offset=tuple(float(value) for value in placement.offset),
            rotation=tuple(float(value) for value in placement.rotation),
        )
        self._publish_dirty()

    def _placement_look_changed(self) -> None:
        if self._syncing or self.placement is None:
            return
        placement = self.placement
        self._staged = replace(
            self._staged,
            color=placement.color,
            intensity=float(placement.intensity),
            size=float(placement.particle_size),
            rate=float(placement.spawn_rate),
            lifetime=float(placement.lifetime),
        )
        self._publish_dirty()
        self.thumbnail.setEnabled(False)
        self.look_timer.start()

    def _publish_dirty(self) -> None:
        dirty = self.has_staged_changes()
        if getattr(self, 'recipe_panel', None) is not None:
            self.recipe_panel.state = self._staged
        if self.placement is not None:
            self.placement.apply_button.setEnabled(dirty and bool(self._staged.stem or self._committed.stem))
            self.placement.discard_button.setEnabled(dirty)
            self.placement.staging_state.setText("Unapplied changes" if dirty else "No unapplied changes")
        self.staged_changed.emit(dirty)

    def _refresh_compatibility(self) -> None:
        if not self._staged.stem:
            self.compatibility_label.setText("")
            self.compatibility_label.setVisible(False)
            return
        self.compatibility_label.setVisible(True)
        compatibility = self._controller.effect_target_compatibility(self._staged.stem)
        if compatibility is None:
            self.compatibility_label.setText("Checking compatibility…" if self._controller.draft.template_key is not None
                                             else "Choose a template to check compatibility.")
        elif compatibility.supported:
            targets = getattr(compatibility, "target_prefabs", None)
            if targets is None:
                self.compatibility_label.setText(str(getattr(compatibility, "message", "Compatible")))
            else:
                count = len(targets)
                if count == 1:
                    self.compatibility_label.setText(f"Compatible  ·  {count} target")
                else:
                    self.compatibility_label.setText(f"Compatible  ·  {count} targets")
        else:
            self.compatibility_label.setText("\n".join(compatibility.errors))

    def _catalogue_progress(self, done: int, total: int, stem: str) -> None:
        self.compatibility_label.setVisible(True)
        if int(total) <= 0:
            self.compatibility_label.setText(str(stem))
            return
        self.compatibility_label.setText(f"Indexing effect metadata: {done:,} / {total:,} — {stem}")

    def _catalogue_ready(self) -> None:
        self._start_library()
        self._refresh_compatibility()
        self._sync_placement_from_state()

    def _catalogue_failed(self, message: str) -> None:
        self.compatibility_label.setVisible(True)
        self.compatibility_label.setText(f"Effect metadata could not be indexed: {message}")

    def _effect_committed_elsewhere(self, _state: object) -> None:
        was_dirty = self.has_staged_changes()
        self._committed = EffectWorkspaceState.from_draft(self._controller.draft)
        if not was_dirty:
            self._staged = self._committed
            self._placement_position = self._committed.offset if self._committed.stem else None
            self._refresh_library()
            self._sync_placement_from_state()
            self._refresh_compatibility()
            self._schedule_preview()
        self._publish_dirty()

    def _appearance_state(self):
        draft = self._controller.draft
        return (draft.model_source, draft.material_route, draft.glow_parts, draft.glow_color,
                draft.glow_intensity, draft.glow_animation, draft.glow_rgb, draft.translucency,
                draft.shader_controls, draft.template_transform, draft.variants)

    def _appearance_changed(self) -> None:
        if self._library_closed:
            return
        state = self._appearance_state()
        if state != self._preview_appearance:
            self._preview_appearance = state
            # Keep staged effects and camera; cancel only the obsolete material build.
            self._schedule_preview()

    def _source_changed(self, *_args) -> None:
        self._preview_appearance = self._appearance_state()
        self._committed = EffectWorkspaceState.from_draft(self._controller.draft)
        self._staged = self._committed
        self.character_fit_choice.setEnabled(self._controller.draft.template_key is not None)
        self._placement_position = self._committed.offset if self._committed.stem else None
        template_key = self._controller.draft.template_key
        self._reset_view_next = self._reset_view_next or template_key != self._preview_template_key
        self._preview_template_key = template_key
        self._preview_retry_remaining = 1
        if self._library_snapshot is not getattr(self._controller, "snapshot", None):
            self._start_library()
        self._refresh_library()
        self._refresh_compatibility()
        self._publish_dirty()
        self._schedule_preview()

    def _selected_character_rig(self) -> str:
        index = int(self.character_fit_choice.currentData() or 0)
        return _CHARACTER_RIGS[index] if 0 <= index < len(_CHARACTER_RIGS) else ""

    def _character_fit_changed(self, _index: int) -> None:
        # The choice changes only the reference body. Keep the reader's camera and stage
        # one immutable rig ID into the existing cancellable latest-wins package lane.
        self._schedule_preview()

    def _schedule_preview(self, delay_ms: int = 150) -> None:
        self._preview_dirty = True
        self.thumbnail.setEnabled(False)
        if self.placement is not None:
            self.placement.cancel_pending_content()
        self.selection_timer.start(delay_ms)

    def _rebuild_preview(self) -> None:
        if self._library_closed or not self.isVisible():
            return
        if self._controller.draft.template_key is None:
            self.placeholder.setText("Choose a template to prepare the resident placement viewport.")
            return
        item_builder = self._controller.item_effect_preview_source()
        stem = self._staged.stem
        model_source = getattr(self._controller, "model_import", None)
        model_source_usage = getattr(model_source, "acquire_usage", None)
        box_min, box_max = self._controller.effect_box(stem)
        preview_builder, texture_reader = self._controller.effect_preview_for_placement(stem, self._staged)
        character_rig = self._selected_character_rig()
        if character_rig:
            character_builder = partial(
                self._controller.character_holding_the_item,
                rig_model=character_rig,
            )
        else:
            character_builder = self._controller.character_holding_the_item
        if self.placement is None:
            kwargs = dict(
                item_mesh=None,
                item_mesh_builder=item_builder,
                box_min=box_min,
                box_max=box_max,
                offset=self._staged.offset,
                rotation=self._staged.rotation,
                scale=self._staged.scale,
                color=self._staged.color,
                intensity=self._staged.intensity,
                particle_size=self._staged.size,
                spawn_rate=self._staged.rate,
                lifetime=self._staged.lifetime,
                effect_label=stem,
                item_label="",
                output_root=self._placement_root,
                effect_preview=preview_builder,
                texture_reader=texture_reader,
                character_builder=character_builder,
                character_fit_control=self.character_fit_row,
                model_source_usage=model_source_usage if callable(model_source_usage) else None,
                render_settings=(getattr(self._controller, "_template_preview_context", None) or {}).get("render_settings"),
            )
            if self._host_factory is not None:
                kwargs["host_factory"] = self._host_factory
            self.placement = self._placement_factory(self.placement_holder, **kwargs)
            self.placement.item_mesh_ready.connect(self._item_mesh_ready)
            self.placement.transform_changed.connect(self._placement_transform_changed)
            self.placement.look_changed.connect(self._placement_look_changed)
            self.placement.apply_requested.connect(self.apply_staged)
            self.placement.discard_button.clicked.connect(self.discard_staged)
            self._attach_authoring()
            self.placeholder.setVisible(False)
            self.placement_layout.addWidget(self.placement, 1)
        else:
            self.placement.set_content(
                item_mesh=None,
                item_mesh_builder=item_builder,
                box_min=box_min,
                box_max=box_max,
                effect_label=stem,
                effect_preview=preview_builder,
                texture_reader=texture_reader,
                character_builder=character_builder,
                model_source_usage=model_source_usage if callable(model_source_usage) else None,
                reset_view=self._reset_view_next,
            )
        self._reset_view_next = False
        self._preview_dirty = False
        self._sync_placement_from_state()

    def _item_mesh_ready(self, mesh, _item_label):
        if mesh is None:
            self._preview_dirty = True
        if self._library_closed or not self.isVisible():
            return
        if mesh is None:
            if self._preview_retry_remaining > 0 and self.isVisible():
                self._preview_retry_remaining -= 1
                self._schedule_preview(300)
            return
        self._preview_retry_remaining = 1
        if self._placement_position is None:
            from cdmw.services.effect_placement_preview import effect_start_position, framing_bounds_for

            offset = getattr(self.placement, "default_offset", None)
            if offset is None:
                offset = effect_start_position(*framing_bounds_for(mesh))
            # Pick an initial point once per item. An explicit move to zero is
            # also a chosen position; later effect or texture loads must keep it.
            self._placement_position = offset
            if self._staged.stem:
                self._staged = replace(self._staged, offset=offset)
        self._sync_placement_from_state()

    def iter_shutdown_workers(self):
        placement = self.placement.iter_shutdown_workers() if self.placement is not None else ()
        return (*placement, *self._library_build_lane.iter_shutdown_workers(), *self._library_search_lane.iter_shutdown_workers())

    def request_shutdown(self) -> None:
        self._library_closed = True
        self._thumbnail_request = None
        self.thumbnail.setEnabled(False)
        self._library_build_lane.request_shutdown()
        self._library_search_lane.request_shutdown()
        self._thumbnail_timer.stop()
        self._library_timer.stop()
        self._library_build = None
        self._initial_preview_timer.stop()
        self.selection_timer.stop()
        self.look_timer.stop()
        if self.placement is not None:
            self.placement.request_shutdown()
        try:
            self._placement_root.rmdir()
        except OSError:
            pass
