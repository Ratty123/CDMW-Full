"""NPC Finder: name or ID -> appearance file -> every piece it lists.

The archive helper does the joins (``npc_catalog_v1``): CharacterInfo and
CharacterAppearanceIndexInfo give the appearance file, its ``<Armor>`` block
names prefabs, and each binary ``.prefab`` names the models with their slots.
This window shows the result and hands pieces to Browse Archives, Mesh Editor
and Create New Item with the same calls Item Finder and Body & Face Finder use.
"""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from cdmw.domain.archives.item_catalogue import BuildNameIndexResult
from cdmw.domain.archives.npc_catalogue import (
    BuildNpcCatalogResult, NpcCatalogSearchRequest, NpcCatalogSearchResult,
    NpcOutfitRequest, NpcOutfitResult, NpcWearersRequest, NpcWearersResult,
)
from cdmw.ui.shell.close_controller import register_transient_worker_controller
from cdmw.ui.wrapping_layout import WrappingLayout


PAGE_SIZE = 100
KIND_LABELS = (("all", "All types"), ("npc", "NPCs"), ("creature", "Creatures"), ("mount", "Mounts"),
               ("player", "Player families"), ("other", "Other"))
KIND_NAMES = {"npc": "NPC", "creature": "Creature", "mount": "Mount", "player": "Player family", "other": "Other"}
SECTION_LABELS = {"armor": "Armour", "body": "Body", "head": "Head", "hair": "Hair"}
RESOLUTION_NOTES = {
    "missing_prefab": "No .prefab file with this name is installed.",
    "unreadable_prefab": "The .prefab file could not be read.",
    "no_model": "This prefab lists no model.",
    "missing_model": "The model this prefab lists is not installed.",
    "unresolved": "No installed model was found for this entry.",
    "ambiguous": "More than one installed file matches; the first is shown.",
}
UNAVAILABLE_TEXT = ("NPC Finder requires an updated archive helper. Rebuild the archive worker or install a "
                    "current CDMW build, then reopen the archives.")


def _cell(text: object, *, tooltip: str = "", data: object = None, grey: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if tooltip:
        item.setToolTip(tooltip)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if grey:
        item.setForeground(Qt.GlobalColor.gray)
    return item


class NpcFinderDialog(QDialog):
    def __init__(self, window, *, query: str = ""):
        super().__init__(window)
        self._window = window
        self._service = window.archive.archive_catalogue_service
        self._bridge = window.archive.archive_remote_bridge
        session = self._bridge.current_session
        if session is None:
            raise ValueError("Scan the archives before opening NPC Finder.")
        self._session_id, self._fingerprint = session.session_id, session.fingerprint
        self._settings = getattr(window.shell, "settings", None)
        self._closing = False
        self._invalid = False
        self._requests: dict[str, str] = {}
        self._summary: BuildNpcCatalogResult | None = None
        self._rows = []
        self._outfit: NpcOutfitResult | None = None
        self._total = 0
        self._page_start = 0
        self._wearers_of = ""
        self._select_after_search = ""
        self._names_requested = False
        self._pending_mesh_path = ""
        self.setObjectName("NpcFinderDialog")
        self.setWindowTitle("NPC Finder")
        self.resize(1180, 720)
        self._build_ui()
        self._restore()
        if query:
            self._search_edit.setText(query)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self._search)
        self._mesh_timer = QTimer(self)
        self._mesh_timer.setInterval(150)
        self._mesh_timer.timeout.connect(self._open_mesh_when_selected)
        self._mesh_deadline = 0
        self._search_edit.textChanged.connect(self._query_changed)
        self._kind.currentIndexChanged.connect(self._query_changed)
        self._armor_only.toggled.connect(self._query_changed)
        self._results.currentCellChanged.connect(lambda *_args: self._selection_changed())
        self._variant.currentIndexChanged.connect(lambda *_args: (self._variant.setToolTip(self._variant.currentData() or ""), self._show_pieces()))
        self._pieces.currentCellChanged.connect(lambda *_args: self._buttons())
        self._pieces.cellDoubleClicked.connect(lambda *_args: self._show_piece())
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failed)
        self._service.progress.connect(self._progress)
        self._service.session_published.connect(self._session_changed)
        self._service.worker_crashed.connect(self._invalidate)
        register_transient_worker_controller(window, self)
        QTimer.singleShot(0, self._build)

    # UI ---------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("NpcFinderSearch")
        self._search_edit.setPlaceholderText("Search by name, ID, file or piece")
        self._search_edit.setToolTip("Matches display names in every language, internal names, character IDs, "
                                     "appearance files and the pieces an NPC wears.")
        self._search_edit.setClearButtonEnabled(True)
        self._kind = QComboBox()
        self._kind.setToolTip("Only show this type of character.")
        for value, label in KIND_LABELS:
            self._kind.addItem(label, value)
        self._armor_only = QCheckBox("Has armour")
        self._armor_only.setToolTip("Only show characters whose appearance lists armour pieces.")
        top.addWidget(self._search_edit, 1)
        top.addWidget(self._kind)
        top.addWidget(self._armor_only)
        layout.addLayout(top)
        self._banner = QPushButton()
        self._banner.setObjectName("NpcFinderWearersBanner")
        self._banner.setToolTip("Show every NPC again.")
        self._banner.setVisible(False)
        self._banner.clicked.connect(self._clear_wearers)
        layout.addWidget(self._banner, 0, Qt.AlignmentFlag.AlignLeft)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(10)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self._results = QTableWidget(0, 4)
        self._results.setObjectName("NpcFinderResults")
        self._results.setHorizontalHeaderLabels(["Name", "ID", "Type", "Pieces"])
        self._configure_table(self._results)
        header = self._results.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_layout.addWidget(self._results, 1)
        pager = QHBoxLayout()
        pager.setSpacing(6)
        self._previous = QPushButton("Previous")
        self._previous.clicked.connect(lambda: self._page(-1))
        self._next_button = QPushButton("Next")
        self._next_button.clicked.connect(lambda: self._page(1))
        self._count = QLabel()
        self._count.setObjectName("HintLabel")
        self._count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pager.addWidget(self._previous)
        pager.addWidget(self._count, 1)
        pager.addWidget(self._next_button)
        left_layout.addLayout(pager)
        left.setMinimumWidth(300)
        self._splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        heading_box = QWidget()
        heading = QVBoxLayout(heading_box)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(2)
        self._title = QLabel("Select an NPC.")
        self._title.setObjectName("NpcFinderTitle")
        self._title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        self._title.setWordWrap(True)
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        heading.addWidget(self._title)
        self._subtitle = QLabel()
        self._subtitle.setObjectName("HintLabel")
        self._subtitle.setWordWrap(True)
        self._subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        heading.addWidget(self._subtitle)
        right_layout.addWidget(heading_box)
        variant_row = QHBoxLayout()
        variant_row.setSpacing(6)
        appearance_label = QLabel("Appearance:")
        appearance_label.setToolTip("The appearance file that dresses this character. Some characters have several.")
        variant_row.addWidget(appearance_label)
        self._variant = QComboBox()
        self._variant.setObjectName("NpcFinderVariant")
        self._variant.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._variant.setMinimumContentsLength(20)
        variant_row.addWidget(self._variant, 1)
        self._copy_appearance = QPushButton("Copy")
        self._copy_appearance.setToolTip("Copy the appearance file's path.")
        self._copy_appearance.clicked.connect(self._copy_appearance_path)
        self._show_appearance = QPushButton("Show in Browse Archives")
        self._show_appearance.setToolTip("Scope Browse Archives to the appearance file.")
        self._show_appearance.clicked.connect(self._show_appearance_file)
        variant_row.addWidget(self._copy_appearance)
        variant_row.addWidget(self._show_appearance)
        right_layout.addLayout(variant_row)

        pieces_box = QGroupBox("Pieces in this appearance")
        pieces_box.setObjectName("NpcFinderPiecesGroup")
        pieces_box.setToolTip("A prefab lists every model it can show. A listed piece is not always visible in game.")
        pieces_layout = QVBoxLayout(pieces_box)
        pieces_layout.setSpacing(6)
        self._pieces = QTableWidget(0, 4)
        self._pieces.setObjectName("NpcFinderPieces")
        self._pieces.setHorizontalHeaderLabels(["Slot", "Piece", "Prefab", "Path"])
        self._configure_table(self._pieces)
        self._pieces.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._pieces.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pieces.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._pieces.horizontalHeader().setMinimumSectionSize(60)
        pieces_layout.addWidget(self._pieces, 1)
        piece_actions_box = QWidget()
        piece_actions = WrappingLayout(piece_actions_box)
        piece_actions.setSpacing(6)
        self._mesh_button = QPushButton("Open in Mesh Editor")
        self._mesh_button.setProperty("primaryAction", True)
        self._mesh_button.setToolTip("Open the selected piece in Mesh Editor.")
        self._mesh_button.clicked.connect(self._open_mesh)
        self._show_piece_button = QPushButton("Show in Browse Archives")
        self._show_piece_button.setToolTip("Scope Browse Archives to the selected piece.")
        self._show_piece_button.clicked.connect(self._show_piece)
        self._item_button = QPushButton("Use in Create New Item")
        self._item_button.clicked.connect(self._create_item)
        self._wearers_button = QPushButton("Worn by")
        self._wearers_button.setToolTip("List every NPC whose appearance lists the selected piece.")
        self._wearers_button.clicked.connect(self._find_wearers)
        self._copy_piece_button = QPushButton("Copy path")
        self._copy_piece_button.setToolTip("Copy the selected piece's path.")
        self._copy_piece_button.clicked.connect(self._copy_piece_path)
        for button in (self._mesh_button, self._show_piece_button, self._item_button, self._wearers_button,
                       self._copy_piece_button):
            piece_actions.addWidget(button)
        pieces_layout.addWidget(piece_actions_box)
        right_layout.addWidget(pieces_box, 1)

        outfit_actions_box = QWidget()
        outfit_actions = WrappingLayout(outfit_actions_box)
        outfit_actions.setSpacing(6)
        self._show_outfit_button = QPushButton("Show outfit in Browse Archives")
        self._show_outfit_button.setToolTip("Scope Browse Archives to every piece of this appearance, as a worn set.")
        self._show_outfit_button.clicked.connect(self._show_outfit)
        self._body_face_button = QPushButton("Open in Body & Face Finder".replace("&", "&&"))
        self._body_face_button.setToolTip("Look up this appearance's body, head and hair in Body & Face Finder.")
        self._body_face_button.clicked.connect(self._open_body_face)
        self._export_button = QPushButton("Export list…")
        self._export_button.setToolTip("Write this appearance's pieces to a CSV or text file.")
        self._export_button.clicked.connect(self._export)
        for button in (self._show_outfit_button, self._body_face_button, self._export_button):
            outfit_actions.addWidget(button)
        right_layout.addWidget(outfit_actions_box)
        self._details = QTextBrowser()
        self._details.setObjectName("NpcFinderDetails")
        self._details.setFrameShape(QFrame.Shape.NoFrame)
        self._details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._details.setMaximumHeight(64)
        self._details.setVisible(False)
        right_layout.addWidget(self._details)
        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 2)
        self._splitter.setStretchFactor(1, 3)
        self._splitter.setSizes([380, 780])
        layout.addWidget(self._splitter, 1)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._busy = QProgressBar()
        self._busy.setObjectName("NpcFinderBusy")
        self._busy.setRange(0, 0)
        self._busy.setTextVisible(False)
        self._busy.setFixedWidth(120)
        self._busy.setMaximumHeight(8)
        status_row.addWidget(self._busy)
        self._status = QLabel("Reading NPC appearances…")
        self._status.setObjectName("NpcFinderStatus")
        self._status.setWordWrap(True)
        status_row.addWidget(self._status, 1)
        layout.addLayout(status_row)
        self._buttons()

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

    def _restore(self) -> None:
        if self._settings is None:
            return
        kind = str(self._settings.value("ui/npc_finder/kind", "npc") or "npc")
        index = self._kind.findData(kind)
        self._kind.setCurrentIndex(max(0, index))
        self._armor_only.setChecked(str(self._settings.value("ui/npc_finder/has_armor", "false")).lower() == "true")
        geometry = self._settings.value("ui/npc_finder/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = self._settings.value("ui/npc_finder/splitter")
        if splitter:
            self._splitter.restoreState(splitter)

    def _save(self) -> None:
        if self._settings is None:
            return
        self._settings.setValue("ui/npc_finder/kind", self._kind.currentData())
        self._settings.setValue("ui/npc_finder/has_armor", "true" if self._armor_only.isChecked() else "false")
        self._settings.setValue("ui/npc_finder/geometry", self.saveGeometry())
        self._settings.setValue("ui/npc_finder/splitter", self._splitter.saveState())

    # Requests ---------------------------------------------------------
    def _generation(self) -> int:
        return self._bridge.controller.generation

    def _cancel(self, kind: str) -> None:
        request = self._requests.pop(kind, None)
        if request:
            self._service.cancel(request)

    def _submit(self, kind: str, start) -> None:
        self._cancel(kind)
        try:
            self._requests[kind] = start()
        except Exception as error:  # the service raises for a missing helper or closed session
            self._status.setText(str(error))
        self._buttons()

    def _build(self) -> None:
        if self._closing or self._invalid:
            return
        self._submit("build", lambda: self._service.build_npc_catalog(self._session_id, ui_generation=self._generation()))

    def _query_changed(self, *_args) -> None:
        self._page_start = 0
        if self._wearers_of:
            self._wearers_of = ""
            self._banner.setVisible(False)
        self._search_timer.start()

    def _search(self) -> None:
        if self._closing or self._invalid or "build" in self._requests or self._summary is None:
            return
        request = NpcCatalogSearchRequest(
            self._session_id, query=self._search_edit.text().strip(), kind=self._kind.currentData() or None,
            has_armor=self._armor_only.isChecked(), page_start=self._page_start, page_size=PAGE_SIZE)
        self._submit("search", lambda: self._service.search_npc_catalog(request, ui_generation=self._generation()))

    def _page(self, direction: int) -> None:
        self._page_start = max(0, self._page_start + direction * PAGE_SIZE)
        self._search()

    def _request_outfit(self, key: str) -> None:
        self._submit("outfit", lambda: self._service.get_npc_outfit(
            NpcOutfitRequest(self._session_id, key), ui_generation=self._generation()))

    def _result(self, request_id, _operation, result) -> None:
        if self._closing or self._invalid or getattr(result, "session_id", None) != self._session_id:
            return
        kind = next((kind for kind, token in self._requests.items() if token == request_id), None)
        if kind is None:
            return
        self._requests.pop(kind)
        if kind == "build" and isinstance(result, BuildNpcCatalogResult):
            self._summary = result
            self._search()
        elif kind == "search" and isinstance(result, NpcCatalogSearchResult):
            self._populate(result.rows, result.total_matches)
        elif kind == "wearers" and isinstance(result, NpcWearersResult):
            rows = list({wearer.row.key: wearer.row for wearer in result.wearers}.values())
            self._populate(rows, len(rows))
            more = f" (first {len(result.wearers):,} of {result.total_count:,})" if result.truncated else ""
            self._banner.setText(f"Worn by: {self._wearers_of}{more} · Show all results")
            self._banner.setVisible(True)
        elif kind == "outfit" and isinstance(result, NpcOutfitResult):
            if result.row.key == self._selected_key():
                self._show_outfit_result(result)
        elif kind == "names" and isinstance(result, BuildNameIndexResult):
            key = self._selected_key()
            if key:
                self._request_outfit(key)
        self._buttons()

    def _failed(self, request, error) -> None:
        kind = next((kind for kind, token in self._requests.items() if token == request), None)
        if kind is None or self._closing:
            return
        self._requests.pop(kind)
        message = str(getattr(error, "message", error))
        self._status.setText(("Item names are unavailable, so Use in Create New Item stays off. " + message)
                             if kind == "names" else message)
        self._buttons()

    def _progress(self, request, update) -> None:
        if request in self._requests.values() and not self._closing:
            self._status.setText((update.current_item or "Reading NPC appearances…") +
                                 (f" · {update.completed:,}/{update.total:,}" if update.total else ""))

    # Results ----------------------------------------------------------
    def _populate(self, rows, total: int) -> None:
        self._rows = list(rows)
        self._total = total
        self._results.blockSignals(True)
        self._results.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            name = row.display_name or row.internal_name or row.key
            grey = row.resolution == "unresolved"
            tooltip = "\n".join(value for value in (
                row.internal_name, row.appearance_path or "No installed appearance file links to this character.") if value)
            self._results.setItem(index, 0, _cell(name, tooltip=tooltip, data=row.key, grey=grey))
            self._results.setItem(index, 1, _cell(row.character_id or "", grey=grey))
            self._results.setItem(index, 2, _cell(KIND_NAMES.get(row.kind, row.kind), grey=grey))
            self._results.setItem(index, 3, _cell(row.piece_count, grey=grey))
        self._results.blockSignals(False)
        shown = f"{self._page_start + 1:,} to {self._page_start + len(self._rows):,} of {total:,}" if self._rows else "No matches"
        self._count.setText(shown)
        statistics = self._summary.statistics if self._summary else None
        if statistics is not None and not self._wearers_of:
            self._status.setText(
                f"{self._summary.npc_count:,} characters · {statistics.appearance_count:,} appearance files · "
                f"{statistics.armor_appearance_count:,} with armour · {statistics.resolved_prefab_count:,} of "
                f"{statistics.distinct_prefab_count:,} armour prefabs found")
        target = self._select_after_search or (self._rows[0].key if self._rows else "")
        self._select_after_search = ""
        self._select_key(target)
        if not self._rows:
            self._clear_outfit()

    def _select_key(self, key: str) -> None:
        for index in range(self._results.rowCount()):
            item = self._results.item(index, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
                self._results.setCurrentCell(index, 0)
                return

    def _selected_key(self) -> str:
        item = self._results.item(self._results.currentRow(), 0) if self._results.currentRow() >= 0 else None
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item is not None else ""

    def _selection_changed(self) -> None:
        key = self._selected_key()
        if not key:
            self._clear_outfit()
            return
        if self._outfit is not None and self._outfit.row.key == key:
            return
        self._outfit = None
        self._title.setText("Reading pieces…")
        self._subtitle.setText("")
        self._request_outfit(key)

    def _clear_outfit(self) -> None:
        self._outfit = None
        self._title.setText("Select an NPC.")
        self._subtitle.setText("")
        self._variant.blockSignals(True)
        self._variant.clear()
        self._variant.blockSignals(False)
        self._pieces.setRowCount(0)
        self._details.clear()
        self._details.setVisible(False)
        self._buttons()

    def _show_outfit_result(self, result: NpcOutfitResult) -> None:
        self._outfit = result
        row = result.row
        parts = []
        if row.character_id:
            parts.append(f"ID {row.character_id}")
        if row.internal_name and row.internal_name != row.display_name:
            parts.append(row.internal_name)
        parts.append(KIND_NAMES.get(row.kind, row.kind))
        self._title.setText(row.display_name or row.internal_name)
        self._subtitle.setText(" · ".join(parts))
        self._variant.blockSignals(True)
        self._variant.clear()
        for outfit in result.outfits:
            label = outfit.appearance_path.rsplit("/", 1)[-1] if outfit.appearance_path else "No installed appearance file"
            if outfit.variant >= 0:
                label = f"Variant {outfit.variant}: {label}"
            self._variant.addItem(label, outfit.appearance_path)
            self._variant.setItemData(self._variant.count() - 1, outfit.appearance_path, Qt.ItemDataRole.ToolTipRole)
        self._variant.blockSignals(False)
        self._variant.setToolTip(self._variant.currentData() or "")
        self._show_pieces()
        if not result.item_links_available and not self._names_requested and "names" not in self._requests:
            # Item Finder's name index links pieces to items for Create New Item.
            self._names_requested = True
            self._submit("names", lambda: self._service.build_name_index(self._session_id, ui_generation=self._generation()))

    def _current_outfit(self):
        if self._outfit is None or not self._outfit.outfits:
            return None
        index = max(0, self._variant.currentIndex())
        return self._outfit.outfits[min(index, len(self._outfit.outfits) - 1)]

    def _show_pieces(self) -> None:
        outfit = self._current_outfit()
        pieces = outfit.pieces if outfit is not None else ()
        self._pieces.setRowCount(len(pieces))
        for index, piece in enumerate(pieces):
            note = RESOLUTION_NOTES.get(piece.resolution, "")
            grey = not piece.has_model
            section = SECTION_LABELS.get(piece.section, piece.section.title())
            slot = piece.slot if piece.section == "armor" else section
            tooltip = "\n".join(value for value in (section, piece.preview and f"Preview: {piece.preview}", note) if value)
            self._pieces.setItem(index, 0, _cell(slot, tooltip=tooltip, data=index, grey=grey))
            self._pieces.setItem(index, 1, _cell(piece.file_name or note or "(none)", tooltip=note, grey=grey))
            self._pieces.setItem(index, 2, _cell(piece.prefab_name, tooltip=piece.prefab_path, grey=grey))
            self._pieces.setItem(index, 3, _cell(piece.model_path, tooltip=piece.model_path, grey=grey))
        for column, cap in ((0, 110), (1, 230), (2, 230)):
            self._pieces.resizeColumnToContents(column)
            self._pieces.setColumnWidth(column, min(self._pieces.columnWidth(column), cap))
        if pieces:
            self._pieces.setCurrentCell(0, 0)
        lines = []
        if self._outfit is not None and self._outfit.other_display_names:
            lines.append("<p>Also known as: " + escape(", ".join(self._outfit.other_display_names)) + "</p>")
        if outfit is not None:
            lines += [f"<p>{escape(line)}</p>" for line in outfit.evidence]
        self._details.setHtml("".join(lines))
        self._details.setVisible(bool(lines))
        self._buttons()

    def _current_piece(self):
        outfit = self._current_outfit()
        row = self._pieces.currentRow()
        if outfit is None or row < 0 or row >= len(outfit.pieces):
            return None
        return outfit.pieces[row]

    def _buttons(self) -> None:
        busy = bool(self._requests.get("build") or self._requests.get("search"))
        usable = not self._invalid and not self._closing
        if hasattr(self, "_busy"):
            self._busy.setVisible(usable and any(kind != "names" for kind in self._requests))
        outfit = self._current_outfit()
        piece = self._current_piece()
        models = [p for p in outfit.pieces if p.has_model] if outfit is not None else []
        self._previous.setEnabled(usable and not busy and not self._wearers_of and self._page_start > 0)
        self._next_button.setEnabled(usable and not busy and not self._wearers_of and self._page_start + PAGE_SIZE < self._total)
        has_appearance = usable and outfit is not None and outfit.appearance_entry_id >= 0
        self._copy_appearance.setEnabled(has_appearance)
        self._show_appearance.setEnabled(has_appearance)
        self._body_face_button.setEnabled(has_appearance)
        self._show_outfit_button.setEnabled(usable and bool(models))
        self._export_button.setEnabled(usable and outfit is not None and bool(outfit.pieces))
        self._show_piece_button.setEnabled(usable and piece is not None and (piece.has_model or piece.prefab_entry_id >= 0))
        self._mesh_button.setEnabled(usable and piece is not None and piece.has_model)
        self._wearers_button.setEnabled(usable and piece is not None and bool(piece.model_path or piece.prefab_name))
        self._copy_piece_button.setEnabled(usable and piece is not None and bool(piece.model_path or piece.prefab_path))
        can_create = usable and piece is not None and bool(piece.item_ids) and callable(getattr(self._window, "open_new_item_studio", None))
        self._item_button.setEnabled(can_create)
        if piece is not None and not piece.item_ids:
            self._item_button.setToolTip("No item uses this piece." if self._outfit and self._outfit.item_links_available
                                         else "Reading item names…")
        else:
            self._item_button.setToolTip("Start Create New Item from the item that uses this piece.")

    # Actions ----------------------------------------------------------
    def _label(self) -> str:
        row = self._outfit.row if self._outfit is not None else None
        return f"NPC Finder: {row.label}" if row is not None else "NPC Finder"

    def _session_current(self) -> bool:
        session = self._bridge.current_session
        return session is not None and session.session_id == self._session_id

    def show_outfit(self) -> bool:
        """Scope Browse Archives to every piece of the selected appearance, as Item Finder does for a worn set."""

        outfit = self._current_outfit()
        if outfit is None or not self._session_current():
            return False
        ids = [piece.model_entry_id for piece in outfit.pieces if piece.has_model]
        stems = [piece.prefab_name for piece in outfit.pieces if piece.section == "armor" and piece.prefab_name]
        if not ids or not self._bridge.apply_entry_id_scope(ids, label=self._label(), preferred_prefab_stems=stems, worn_set=True):
            return False
        self.accept()
        return True

    def _show_outfit(self) -> None:
        self.show_outfit()

    def show_piece(self) -> bool:
        piece = self._current_piece()
        if piece is None or not self._session_current():
            return False
        entry_id = piece.model_entry_id if piece.has_model else piece.prefab_entry_id
        if entry_id < 0 or not self._bridge.apply_entry_id_scope([entry_id], label=f"{self._label()} · {piece.file_name or piece.prefab_name}"):
            return False
        self.accept()
        return True

    def _show_piece(self) -> None:
        self.show_piece()

    def _show_appearance_file(self) -> None:
        outfit = self._current_outfit()
        if outfit is not None and outfit.appearance_entry_id >= 0 and self._session_current():
            if self._bridge.apply_entry_id_scope([outfit.appearance_entry_id], label=f"{self._label()} · appearance"):
                self.accept()

    def open_mesh(self) -> bool:
        """Scope to the selected piece, wait for Browse Archives to select it, then open Mesh Editor."""

        piece = self._current_piece()
        if piece is None or not piece.has_model or not self._session_current():
            return False
        if not self._bridge.apply_entry_id_scope([piece.model_entry_id], label=f"{self._label()} · {piece.file_name}"):
            return False
        self._pending_mesh_path = piece.model_path.replace("\\", "/").casefold()
        self._mesh_deadline = 80  # 12 s at 150 ms
        self.hide()
        self._mesh_timer.start()
        return True

    def _open_mesh(self) -> None:
        self.open_mesh()

    def _cancel_mesh_wait(self) -> None:
        self._mesh_timer.stop()
        self._pending_mesh_path = ""

    def _open_mesh_when_selected(self) -> None:
        archive = self._window.archive
        current = archive._current_archive_mesh_entry() if hasattr(archive, "_current_archive_mesh_entry") else None
        path = str(getattr(current, "path", "") or "").replace("\\", "/").casefold()
        button = getattr(archive, "archive_model_open_mesh_editor_button", None)
        if current is not None and path == self._pending_mesh_path and button is not None and button.isEnabled():
            self._mesh_timer.stop()
            self._pending_mesh_path = ""
            button.click()
            self.accept()
            return
        self._mesh_deadline -= 1
        if self._mesh_deadline <= 0:
            self._mesh_timer.stop()
            self._pending_mesh_path = ""
            status = getattr(getattr(self._window, "shell", None), "set_status_message", None)
            if callable(status):
                status("NPC Finder scoped Browse Archives to the piece. Select it and use Open in Mesh Editor.")
            self.accept()

    def create_item(self) -> bool:
        piece = self._current_piece()
        opener = getattr(self._window, "open_new_item_studio", None)
        if piece is None or not piece.item_ids or not callable(opener):
            return False
        opener(int(piece.item_ids[0]))
        self.accept()
        return True

    def _create_item(self) -> None:
        self.create_item()

    def find_wearers(self, piece_text: str = "") -> bool:
        piece = self._current_piece()
        text = piece_text or (piece.model_path or piece.prefab_name if piece is not None else "")
        if not text:
            return False
        self._wearers_of = text.replace("\\", "/").rsplit("/", 1)[-1]
        # The wearers are one list from its first row; a page of the search before must not offset its count.
        self._page_start = 0
        self._select_after_search = self._selected_key()
        self._submit("wearers", lambda: self._service.find_npc_wearers(
            NpcWearersRequest(self._session_id, text), ui_generation=self._generation()))
        return True

    def _find_wearers(self) -> None:
        self.find_wearers()

    def _clear_filters(self) -> None:
        self._wearers_of = ""
        self._banner.setVisible(False)
        self._search_edit.clear()
        self._armor_only.setChecked(False)
        self._kind.setCurrentIndex(max(0, self._kind.findData("all")))
        self._query_changed()

    def _clear_wearers(self) -> None:
        self._wearers_of = ""
        self._banner.setVisible(False)
        self._search()

    def open_body_face(self) -> bool:
        outfit = self._current_outfit()
        if outfit is None or not outfit.appearance_path:
            return False
        from cdmw.ui.character_finder.dialog import show_character_finder

        dialog = show_character_finder(self._window)
        if dialog is not None:
            view = dialog._view.findData("appearances")
            if view >= 0:
                dialog._view.setCurrentIndex(view)
            dialog._search_edit.setText(outfit.appearance_path)
        return True

    def _open_body_face(self) -> None:
        self.open_body_face()

    def _copy_appearance_path(self) -> None:
        outfit = self._current_outfit()
        if outfit is not None and outfit.appearance_path:
            QApplication.clipboard().setText(outfit.appearance_path)

    def _copy_piece_path(self) -> None:
        piece = self._current_piece()
        if piece is not None:
            QApplication.clipboard().setText(piece.model_path or piece.prefab_path)

    def export_outfit(self, path: str | Path) -> int:
        """Write the selected appearance's pieces to ``path`` (.csv, else plain text). Returns rows written."""

        outfit = self._current_outfit()
        if outfit is None or self._outfit is None:
            return 0
        target = Path(path)
        row = self._outfit.row
        columns = ("section", "slot", "piece", "prefab", "model_path", "prefab_path", "resolution")
        values = [(piece.section, piece.slot, piece.file_name, piece.prefab_name, piece.model_path, piece.prefab_path,
                   piece.resolution) for piece in outfit.pieces]
        if target.suffix.lower() == ".csv":
            with target.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(values)
        else:
            lines = [f"{row.label} (ID {row.character_id})" if row.character_id else row.label,
                     f"Appearance: {outfit.appearance_path}", ""]
            lines += [f"{slot}\t{model or '(' + resolution + ')'}\t{prefab}" for _section, slot, _piece, prefab, model, _pp, resolution in values]
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return len(values)

    def _export(self) -> None:
        default = ""
        if self._settings is not None:
            default = str(self._settings.value("ui/npc_finder/export_dir", "") or "")
        name = (self._outfit.row.internal_name or "npc") if self._outfit is not None else "npc"
        path, _filter = QFileDialog.getSaveFileName(self, "Export outfit list", str(Path(default) / f"{name}_pieces.csv"),
                                                     "CSV (*.csv);;Text (*.txt)")
        if not path:
            return
        try:
            count = self.export_outfit(path)
        except OSError as error:
            QMessageBox.warning(self, "NPC Finder", f"Could not write the list: {error}")
            return
        if self._settings is not None:
            self._settings.setValue("ui/npc_finder/export_dir", str(Path(path).parent))
        self._status.setText(f"Wrote {count:,} pieces to {path}.")

    # Lifetime ---------------------------------------------------------
    def _session_changed(self, session) -> None:
        if session.session_id != self._session_id or session.fingerprint != self._fingerprint:
            self._invalidate("The archive changed. Close and reopen NPC Finder for the current catalogue.")

    def _invalidate(self, message) -> None:
        self._invalid = True
        self._search_timer.stop()
        for kind in tuple(self._requests):
            self._cancel(kind)
        self._status.setText(str(message))
        self._buttons()

    def iter_shutdown_workers(self):
        return iter(())

    def request_shutdown(self) -> None:
        self.close()

    def _shutdown(self) -> None:
        if self._closing:
            return
        self._save()
        self._closing = True
        self._search_timer.stop()
        # A wait for Browse Archives must not outlive the window: it would press Open in Mesh Editor later.
        self._cancel_mesh_wait()
        for kind in tuple(self._requests):
            self._cancel(kind)
        for signal, slot in ((self._service.result_ready, self._result), (self._service.request_failed, self._failed),
                             (self._service.progress, self._progress), (self._service.session_published, self._session_changed),
                             (self._service.worker_crashed, self._invalidate)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        retained = getattr(self._window, "_npc_finder_dialogs", None)
        if retained is not None:
            retained.discard(self)

    def done(self, result) -> None:
        self._shutdown()
        super().done(result)
        QTimer.singleShot(0, self.deleteLater)

    def closeEvent(self, event) -> None:
        self._shutdown()
        super().closeEvent(event)
        QTimer.singleShot(0, self.deleteLater)


def npc_finder_dialog(window) -> NpcFinderDialog | None:
    """The open NPC Finder, if any."""

    for dialog in tuple(getattr(window, "_npc_finder_dialogs", None) or ()):
        if not dialog._closing:
            return dialog
    return None


def show_npc_finder(window, *, query: str = "") -> NpcFinderDialog | None:
    service = getattr(window.archive, "archive_catalogue_service", None)
    if service is None or not getattr(service, "npc_catalog_available", False):
        QMessageBox.information(window, "NPC Finder", UNAVAILABLE_TEXT)
        return None
    existing = npc_finder_dialog(window)
    if existing is not None and not existing._invalid:
        # Shown again while it waited, hidden, to open a piece in Mesh Editor: the user came back instead.
        existing._cancel_mesh_wait()
        if query:
            existing._search_edit.setText(query)
        existing.show()
        existing.raise_()
        existing.activateWindow()
        return existing
    retained = getattr(window, "_npc_finder_dialogs", None)
    if retained is None:
        retained = set()
        setattr(window, "_npc_finder_dialogs", retained)
    try:
        dialog = NpcFinderDialog(window, query=query)
    except ValueError as error:
        QMessageBox.information(window, "NPC Finder", str(error))
        return None
    retained.add(dialog)
    dialog.show()
    return dialog
