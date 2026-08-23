"""Guided Step 5 visual-effect library, staging, placement and look controls."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.effect_catalogue import EffectFacts
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from cdmw.ui.new_item.state import EffectWorkspaceState

__all__ = [
    "CATEGORY_RULES",
    "EffectLibraryModel",
    "GuidedEffectsWorkspace",
    "effect_category",
    "effect_display_label",
]


CATEGORY_RULES = (
    ("Fire", ("fire", "flame", "ember", "burn")),
    ("Frost", ("ice", "frost", "frozen", "freeze")),
    ("Lightning", ("lightning", "electric", "shock", "thunder")),
    ("Glow", ("glow", "emissive")),
    ("Aura", ("aura",)),
    ("Trail", ("trail",)),
    ("Sparks", ("spark",)),
)

CATEGORY_GLYPHS = {
    "Fire": "♨",
    "Frost": "❄",
    "Lightning": "ϟ",
    "Glow": "◉",
    "Aura": "◎",
    "Trail": "↝",
    "Sparks": "✦",
    "Other": "◇",
}


def effect_category(stem: str, authoring_name: str = "") -> str:
    """Deterministic first-match category using the product's fixed token rules."""

    text = f"{stem} {authoring_name}".casefold()
    for category, tokens in CATEGORY_RULES:
        if any(token in text for token in tokens):
            return category
    return "Other"


def effect_display_label(stem: str, authoring_name: str = "") -> str:
    """A neutral mechanical label; the exact stem remains visible underneath it."""

    source = str(authoring_name or stem or "").replace("\\", "/").rsplit("/", 1)[-1]
    source = re.sub(r"\.(?:level\.)?effect$", "", source, flags=re.I)
    tokens = re.findall(r"[A-Za-z]+|\d+[A-Za-z]*", source)
    while tokens and tokens[0].casefold() in {"fx", "pafx", "vfx", "effect", "cdem"}:
        tokens.pop(0)
    if not tokens:
        return str(stem or "No effect")
    return " ".join(token.upper() if token.isupper() else token.capitalize() for token in tokens)


@dataclass(frozen=True, slots=True)
class EffectLibraryRow:
    stem: str
    label: str
    category: str
    behavior: str
    facts: Optional[EffectFacts] = None

    @classmethod
    def from_stem(cls, stem: str, facts: Optional[EffectFacts]) -> "EffectLibraryRow":
        name = facts.name if facts is not None else ""
        loops = (
            bool(facts.loops) or (bool(facts.walk_note) and "loop" in stem.casefold())
            if facts is not None
            else "loop" in stem.casefold()
        )
        behavior = "Loop" if loops else "One-shot"
        return cls(
            stem=stem,
            label=effect_display_label(stem, name),
            category=effect_category(stem, name),
            behavior=behavior,
            facts=facts,
        )


class EffectLibraryModel(QAbstractListModel):
    StemRole = int(Qt.ItemDataRole.UserRole) + 1
    LabelRole = StemRole + 1
    CategoryRole = StemRole + 2
    BehaviorRole = StemRole + 3
    GlyphRole = StemRole + 4

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: tuple[EffectLibraryRow, ...] = (
            EffectLibraryRow("", "No effect", "Other", "Off"),
        )

    def replace_rows(self, rows: tuple[EffectLibraryRow, ...]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._rows)

    def row(self, index: int) -> Optional[EffectLibraryRow]:
        return self._rows[index] if 0 <= int(index) < len(self._rows) else None

    def index_for_stem(self, stem: str) -> QModelIndex:
        wanted = str(stem or "")
        for row, item in enumerate(self._rows):
            if item.stem == wanted:
                return self.index(row, 0)
        return QModelIndex()

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)):  # noqa: D401
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        item = self._rows[index.row()]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return item.label
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return item.stem or "Clear the visual effect and all placement/look tuning."
        if role == int(Qt.ItemDataRole.AccessibleTextRole):
            return f"{item.label}; {item.stem or 'no effect'}; {item.behavior}"
        if role == int(Qt.ItemDataRole.SizeHintRole):
            return QSize(0, 52)
        if role == self.StemRole:
            return item.stem
        if role == self.LabelRole:
            return item.label
        if role == self.CategoryRole:
            return item.category
        if role == self.BehaviorRole:
            return item.behavior
        if role == self.GlyphRole:
            return CATEGORY_GLYPHS.get(item.category, CATEGORY_GLYPHS["Other"])
        return None


class EffectLibraryDelegate(QStyledItemDelegate):
    """Two-line, virtualized 52 px library row with glyph and behavior badge."""

    def sizeHint(self, option, index):  # noqa: N802 - Qt override
        return QSize(max(300, option.rect.width()), 52)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:  # noqa: D401
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        palette = option.palette
        background = palette.highlight().color() if selected else palette.base().color()
        painter.fillRect(option.rect, background)

        foreground = palette.highlightedText().color() if selected else palette.text().color()
        muted = QColor(foreground)
        muted.setAlpha(155)
        rect = option.rect.adjusted(12, 4, -10, -4)
        glyph = str(index.data(EffectLibraryModel.GlyphRole) or "◇")
        painter.setPen(foreground)
        glyph_font = painter.font()
        glyph_font.setPointSize(max(glyph_font.pointSize() + 5, 14))
        painter.setFont(glyph_font)
        painter.drawText(QRect(rect.left(), rect.top(), 32, rect.height()), Qt.AlignmentFlag.AlignCenter, glyph)

        badge = str(index.data(EffectLibraryModel.BehaviorRole) or "")
        badge_width = max(48, painter.fontMetrics().horizontalAdvance(badge) + 18)
        badge_rect = QRect(rect.right() - badge_width, rect.top() + 10, badge_width, 24)
        badge_colour = palette.mid().color()
        badge_colour.setAlpha(110)
        painter.setBrush(badge_colour)
        painter.setPen(palette.mid().color())
        painter.drawRoundedRect(badge_rect, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        text_left = rect.left() + 44
        text_right = badge_rect.left() - 10
        label_rect = QRect(text_left, rect.top() + 2, max(10, text_right - text_left), 22)
        stem_rect = QRect(text_left, rect.top() + 25, max(10, text_right - text_left), 18)
        label_font = option.font
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.setPen(foreground)
        label = painter.fontMetrics().elidedText(
            str(index.data(EffectLibraryModel.LabelRole) or ""),
            Qt.TextElideMode.ElideRight,
            label_rect.width(),
        )
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, label)
        stem_font = option.font
        stem_font.setPointSize(max(7, stem_font.pointSize() - 1))
        painter.setFont(stem_font)
        painter.setPen(muted)
        stem = painter.fontMetrics().elidedText(
            str(index.data(EffectLibraryModel.StemRole) or "No shipped effect"),
            Qt.TextElideMode.ElideRight,
            stem_rect.width(),
        )
        painter.drawText(stem_rect, Qt.AlignmentFlag.AlignVCenter, stem)
        painter.setFont(option.font)
        painter.setPen(foreground)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge)
        painter.restore()


class _CategoryChipPanel(QWidget):
    resized = Signal(int)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.resized.emit(self.width())


class GuidedEffectsWorkspace(QWidget):
    """The complete resident Effects tab; edits stay staged until Apply placement."""

    staged_changed = Signal(bool)
    applied = Signal(object)

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
        self._controller = controller
        self._placement_factory = placement_factory
        self._host_factory = host_factory
        self._confirm_unreviewed = confirm_unreviewed or self._default_unreviewed_confirmation
        self._committed = EffectWorkspaceState.from_draft(controller.draft)
        self._staged = self._committed
        self._syncing = False
        self._reset_view_next = True
        self._preview_retry_remaining = 1
        self._placement_root = Path(tempfile.mkdtemp(prefix="cdmw_effect_workspace_"))

        self.selection_timer = QTimer(self)
        self.selection_timer.setSingleShot(True)
        self.selection_timer.setInterval(150)
        self.selection_timer.timeout.connect(self._rebuild_preview)
        self.look_timer = QTimer(self)
        self.look_timer.setSingleShot(True)
        self.look_timer.setInterval(250)
        self.look_timer.timeout.connect(self._rebuild_preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("effect_workspace_splitter")
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

        library = QFrame()
        library.setObjectName("effect_library_panel")
        library.setMinimumWidth(300)
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(14, 12, 12, 10)
        library_layout.setSpacing(10)
        title = QLabel("Effect Library")
        title.setObjectName("effect_library_heading")
        library_layout.addWidget(title)
        self.search = QLineEdit()
        self.search.setObjectName("effect_search")
        self.search.setPlaceholderText("Search effects…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh_library)
        library_layout.addWidget(self.search)
        self.compatibility_label = QLabel("Choose a template to check compatibility.")
        self.compatibility_label.setObjectName("effect_compatibility")
        self.compatibility_label.setWordWrap(True)
        library_layout.addWidget(self.compatibility_label)

        self.category_panel = _CategoryChipPanel()
        self.category_layout = QGridLayout(self.category_panel)
        self.category_layout.setContentsMargins(0, 0, 0, 0)
        self.category_layout.setHorizontalSpacing(5)
        self.category_layout.setVerticalSpacing(5)
        self._category_columns = 0
        self.category_group = QButtonGroup(self)
        self.category_group.setExclusive(True)
        self.category_buttons: dict[str, QToolButton] = {}
        for category in ("All", *(name for name, _tokens in CATEGORY_RULES)):
            button = QToolButton()
            button.setText(category)
            button.setCheckable(True)
            button.setProperty("effectChip", True)
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(category) + 18)
            button.clicked.connect(self._refresh_library)
            self.category_group.addButton(button)
            self.category_buttons[category] = button
        self.category_buttons["All"].setChecked(True)
        self.category_panel.resized.connect(self._reflow_category_chips)
        library_layout.addWidget(self.category_panel)
        QTimer.singleShot(0, lambda: self._reflow_category_chips(self.category_panel.width()))
        self.loop_only = QToolButton()
        self.loop_only.setText("Loop")
        self.loop_only.setCheckable(True)
        self.loop_only.setProperty("effectChip", True)
        self.loop_only.clicked.connect(self._refresh_library)
        library_layout.addWidget(self.loop_only, alignment=Qt.AlignmentFlag.AlignLeft)

        self.library_model = EffectLibraryModel(self)
        self.library_view = QListView()
        self.library_view.setObjectName("effect_library")
        self.library_view.setModel(self.library_model)
        self.library_view.setItemDelegate(EffectLibraryDelegate(self.library_view))
        self.library_view.setUniformItemSizes(True)
        self.library_view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.library_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.library_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.library_view.setSpacing(0)
        self.library_view.selectionModel().currentChanged.connect(self._library_selection_changed)
        library_layout.addWidget(self.library_view, 1)

        self.placement_holder = QWidget()
        self.placement_holder.setMinimumWidth(820)
        self.placement_layout = QVBoxLayout(self.placement_holder)
        self.placement_layout.setContentsMargins(0, 0, 0, 0)
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

        self.caution = QLabel("Visual only  •  Approximate preview  •  Verify final fit in game")
        self.caution.setObjectName("effect_visual_caution")
        self.caution.setContentsMargins(14, 8, 14, 8)
        layout.addWidget(self.caution)

        controller.effect_catalogue_progress.connect(self._catalogue_progress)
        controller.effect_catalogue_ready.connect(self._catalogue_ready)
        controller.effect_catalogue_failed.connect(self._catalogue_failed)
        controller.effect_changed.connect(self._effect_committed_elsewhere)
        controller.template_changed.connect(self._source_changed)
        controller.model_import_changed.connect(self._source_changed)
        controller.model_changed.connect(self._source_changed)
        controller.model_placement_changed.connect(self._source_changed)
        self._refresh_library()
        QTimer.singleShot(0, self._rebuild_preview)

    @property
    def staged_state(self) -> EffectWorkspaceState:
        return self._staged

    def has_staged_changes(self) -> bool:
        return self._staged != self._committed

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if self.placement is None and self._controller.draft.template_key is not None:
            self._preview_retry_remaining = 1
            self.selection_timer.start()

    def choose_effect(self, stem: str, *, scale: float = 1.0) -> None:
        """Compatibility entry point: stage an exact shipped stem at neutral defaults."""

        clean = str(stem or "").strip()
        if clean == self._committed.stem:
            self._staged = self._committed
        else:
            self._staged = EffectWorkspaceState.defaults(clean)
        self._refresh_library()
        self._select_stem(clean)
        self._sync_placement_from_state()
        self._refresh_compatibility()
        self._publish_dirty()
        self.selection_timer.start()

    def apply_staged(self) -> bool:
        if not str(self._staged.stem or "").strip():
            self._staged = EffectWorkspaceState.defaults()
        if not self.has_staged_changes():
            self._publish_dirty()
            return True
        compatibility = self._controller.effect_target_compatibility(self._staged.stem)
        if self._staged.stem and (compatibility is None or not compatibility.supported):
            self._refresh_compatibility()
            return False
        placement = self.placement
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
        self._refresh_library()
        self._select_stem(self._staged.stem)
        self._sync_placement_from_state()
        self._refresh_compatibility()
        self._publish_dirty()
        self.selection_timer.start()

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
        for category, button in self.category_buttons.items():
            if button.isChecked():
                return category
        return "All"

    def _reflow_category_chips(self, width: int) -> None:
        buttons = tuple(self.category_buttons.values())
        available = max(1, int(width))
        spacing = self.category_layout.horizontalSpacing()
        columns = 1
        for candidate in range(len(buttons), 0, -1):
            column_widths = [0] * candidate
            for index, button in enumerate(buttons):
                column = index % candidate
                required = button.fontMetrics().horizontalAdvance(button.text()) + 18
                column_widths[column] = max(column_widths[column], button.sizeHint().width(), required)
            if sum(column_widths) + spacing * (candidate - 1) <= available:
                columns = candidate
                break
        if columns == self._category_columns:
            return
        self._category_columns = columns
        while self.category_layout.count():
            self.category_layout.takeAt(0)
        for index, button in enumerate(buttons):
            self.category_layout.addWidget(button, index // columns, index % columns)

    def _refresh_library(self, *_args) -> None:
        selected = self._staged.stem
        stems = list(self._controller.effect_stems(self.search.text(), limit=None))
        if selected and selected not in stems:
            stems.insert(0, selected)
        category = self._active_category()
        rows = []
        for stem in stems:
            facts = self._controller.effect_facts(stem)
            row = EffectLibraryRow.from_stem(stem, facts)
            if stem != selected and category != "All" and row.category != category:
                continue
            if stem != selected and self.loop_only.isChecked() and row.behavior != "Loop":
                continue
            rows.append(row)
        rows.sort(key=lambda item: item.stem.casefold())
        self._syncing = True
        try:
            self.library_model.replace_rows((EffectLibraryRow("", "No effect", "Other", "Off"), *rows))
            self._select_stem(selected)
        finally:
            self._syncing = False

    def _select_stem(self, stem: str) -> None:
        index = self.library_model.index_for_stem(stem)
        if index.isValid():
            self.library_view.setCurrentIndex(index)
            self.library_view.scrollTo(index, QListView.ScrollHint.EnsureVisible)

    def _library_selection_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if self._syncing or not current.isValid():
            return
        stem = str(current.data(EffectLibraryModel.StemRole) or "")
        self._staged = self._committed if stem == self._committed.stem else EffectWorkspaceState.defaults(stem)
        self._sync_placement_from_state()
        self._refresh_compatibility()
        self._publish_dirty()
        self.selection_timer.start()

    def _sync_placement_from_state(self) -> None:
        placement = self.placement
        if placement is None:
            return
        facts = self._controller.effect_facts(self._staged.stem)
        decoder_reason = facts.walk_note if facts is not None and facts.walk_note else ""
        look_normalized = False
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
            look_normalized = True
        placement._set_numbers(self._staged.offset, self._staged.scale, self._staged.rotation)
        placement.set_look(
            color=self._staged.color,
            intensity=self._staged.intensity,
            particle_size=self._staged.size,
            spawn_rate=self._staged.rate,
            lifetime=self._staged.lifetime,
        )
        placement.set_decoder_reason(decoder_reason)
        placement.apply_button.setEnabled(self.has_staged_changes() and bool(self._staged.stem or self._committed.stem))
        if look_normalized:
            self._publish_dirty()

    def _placement_transform_changed(self) -> None:
        if self._syncing or self.placement is None:
            return
        placement = self.placement
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
        self.look_timer.start()

    def _publish_dirty(self) -> None:
        dirty = self.has_staged_changes()
        if self.placement is not None:
            self.placement.apply_button.setEnabled(dirty and bool(self._staged.stem or self._committed.stem))
        self.staged_changed.emit(dirty)

    def _refresh_compatibility(self) -> None:
        if not self._staged.stem:
            self.compatibility_label.setText("No effect will be added to this item.")
            return
        compatibility = self._controller.effect_target_compatibility(self._staged.stem)
        if compatibility is None:
            self.compatibility_label.setText("Choose a template to check compatibility.")
        elif compatibility.supported:
            self.compatibility_label.setText(compatibility.message)
        else:
            self.compatibility_label.setText("\n".join(compatibility.errors))

    def _catalogue_progress(self, done: int, total: int, stem: str) -> None:
        if int(total) <= 0:
            self.compatibility_label.setText(str(stem))
            return
        self.compatibility_label.setText(f"Indexing effect metadata: {done:,} / {total:,} — {stem}")

    def _catalogue_ready(self) -> None:
        self._refresh_library()
        self._refresh_compatibility()
        self._sync_placement_from_state()

    def _catalogue_failed(self, message: str) -> None:
        self.compatibility_label.setText(f"Effect metadata could not be indexed: {message}")

    def _effect_committed_elsewhere(self, _state: object) -> None:
        was_dirty = self.has_staged_changes()
        self._committed = EffectWorkspaceState.from_draft(self._controller.draft)
        if not was_dirty:
            self._staged = self._committed
            self._refresh_library()
            self._sync_placement_from_state()
            self._refresh_compatibility()
            self.selection_timer.start()
        self._publish_dirty()

    def _source_changed(self, *_args) -> None:
        self._committed = EffectWorkspaceState.from_draft(self._controller.draft)
        self._staged = self._committed
        self._reset_view_next = True
        self._preview_retry_remaining = 1
        self._refresh_library()
        self._refresh_compatibility()
        self._publish_dirty()
        self.selection_timer.start()

    def _rebuild_preview(self) -> None:
        mesh, item_label = self._controller.item_mesh_as_planned()
        if mesh is None:
            if self._controller.draft.template_key is None:
                self.placeholder.setText("Choose a template to prepare the resident placement viewport.")
                self._preview_retry_remaining = 1
            else:
                self.placeholder.setText("Preparing the viewport...")
                if self._preview_retry_remaining > 0 and self.isVisible():
                    self._preview_retry_remaining -= 1
                    self.selection_timer.start(300)
            return
        self._preview_retry_remaining = 1
        stem = self._staged.stem
        box_min, box_max = self._controller.effect_box(stem)
        preview, texture_reader = self._controller.effect_preview_for_placement(stem, self._staged)
        if preview is not None and self._controller.effect_facts(stem) is None:
            box_min, box_max = preview.box_min, preview.box_max
        if self.placement is None:
            kwargs = dict(
                item_mesh=mesh,
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
                item_label=item_label,
                output_root=self._placement_root,
                effect_preview=preview,
                texture_reader=texture_reader,
                character_builder=self._controller.character_holding_the_item,
            )
            if self._host_factory is not None:
                kwargs["host_factory"] = self._host_factory
            self.placement = self._placement_factory(self.placement_holder, **kwargs)
            self.placement.transform_changed.connect(self._placement_transform_changed)
            self.placement.look_changed.connect(self._placement_look_changed)
            self.placement.apply_requested.connect(self.apply_staged)
            self.placeholder.setVisible(False)
            self.placement_layout.addWidget(self.placement, 1)
        else:
            self.placement.set_content(
                item_mesh=mesh,
                box_min=box_min,
                box_max=box_max,
                effect_label=stem,
                effect_preview=preview,
                texture_reader=texture_reader,
                character_builder=self._controller.character_holding_the_item,
                reset_view=self._reset_view_next,
            )
        self._reset_view_next = False
        self._sync_placement_from_state()

    def iter_shutdown_workers(self):
        return self.placement.iter_shutdown_workers() if self.placement is not None else ()

    def request_shutdown(self) -> None:
        self.selection_timer.stop()
        self.look_timer.stop()
        if self.placement is not None:
            self.placement.request_shutdown()
        try:
            self._placement_root.rmdir()
        except OSError:
            pass
