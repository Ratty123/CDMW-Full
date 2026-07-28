"""Translation Studio: retranslate the game, one searchable line at a time.

`.paloc` has been readable and writable for a while, but there was no way to reach it
from the app, so the one format where an edit provably cannot corrupt anything was also
the one nobody could use. This is that missing half.

What the shape of the data dictates:

**Search first, browse never.** 187,521 lines is not a list anyone scrolls. The window
opens on a search box, and the table is a virtualised model so filtering 187,521 rows
stays instant.

**A reference language beside the working one.** Translating from English into Polish
means reading the English; proofreading a fan translation means reading the Korean
original. One key-to-text mapping is enough for that, and far cheaper than a second
editable table.

**Edits are visible and cheap to undo.** A pass touches a handful of lines, so edited
rows are highlighted, "Edited only" isolates them, and both a single-row revert and a
whole-pass reset are one click. The shipped text stays in the tooltip.

Loading reads straight from the archives on a worker, because a language table is 16-25
MB and the UI thread must not stall on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .catalogue import (
    TranslationCatalogue,
    attach_reference,
    available_languages,
    export_packages,
    load_catalogue,
    read_language,
)
from .table_model import TEXT, TranslationTableModel

_NONE = "(none)"
#: Cap the rows a search returns. Nobody reads 90,000 hits, and building that view
#: costs more than the search itself.
_MAX_HITS = 5000


class _LoadWorker(QObject):
    done = Signal(object, object, str)

    def __init__(self, language: str, reference: str) -> None:
        super().__init__()
        self._language = language
        self._reference = reference

    def run(self) -> None:
        try:
            data = read_language(self._language)
            reference = read_language(self._reference) if self._reference else None
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            self.done.emit(None, None, str(error))
            return
        self.done.emit(data, reference, "")


class TranslationStudioTab(QWidget):
    """Search, retranslate and export the game's string tables."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._catalogue: Optional[TranslationCatalogue] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_LoadWorker] = None
        self._build_ui()
        self._populate_languages()

    # ------------------------------------------------------------------ widgets

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        picker = QHBoxLayout()
        picker.addWidget(QLabel("Language"))
        self.language_box = QComboBox()
        self.language_box.setMinimumContentsLength(10)
        picker.addWidget(self.language_box)
        picker.addWidget(QLabel("Show alongside"))
        self.reference_box = QComboBox()
        self.reference_box.setMinimumContentsLength(10)
        picker.addWidget(self.reference_box)
        self.load_button = QPushButton("Load")
        self.load_button.clicked.connect(self._on_load)
        picker.addWidget(self.load_button)
        self.status_label = QLabel("Pick a language and load it.")
        self.status_label.setWordWrap(True)
        picker.addWidget(self.status_label, 1)
        outer.addLayout(picker)

        search = QHBoxLayout()
        search.addWidget(QLabel("Find"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Text or key, e.g. Greymane or questdialog_main")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._refresh_view)
        self.search_box.setEnabled(False)
        search.addWidget(self.search_box, 2)
        search.addWidget(QLabel("Group"))
        self.category_box = QComboBox()
        self.category_box.setMinimumContentsLength(14)
        self.category_box.currentIndexChanged.connect(self._refresh_view)
        self.category_box.setEnabled(False)
        search.addWidget(self.category_box, 1)
        self.edited_only = QCheckBox("Edited only")
        self.edited_only.toggled.connect(self._refresh_view)
        self.edited_only.setEnabled(False)
        search.addWidget(self.edited_only)
        self.hits_label = QLabel("")
        search.addWidget(self.hits_label)
        outer.addLayout(search)

        self.model = TranslationTableModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 260)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)
        outer.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.revert_button = QPushButton("Revert line")
        self.revert_button.setToolTip("Put the selected line back to what the game ships.")
        self.revert_button.clicked.connect(self._on_revert)
        self.revert_button.setEnabled(False)
        actions.addWidget(self.revert_button)
        self.reset_button = QPushButton("Reset all")
        self.reset_button.clicked.connect(self._on_reset)
        self.reset_button.setEnabled(False)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        self.hint_label = QLabel(
            "Double-click a line in Text to retranslate it. Nothing in this format is "
            "offset-addressed, so a longer or shorter line is safe."
        )
        self.hint_label.setWordWrap(True)
        actions.addWidget(self.hint_label, 2)
        outer.addLayout(actions)

        outer.addWidget(self._build_export())

    def _build_export(self) -> QWidget:
        box = QGroupBox("Export as a mod")
        layout = QVBoxLayout(box)
        self.pending_label = QLabel("No changes.")
        self.pending_label.setWordWrap(True)
        layout.addWidget(self.pending_label)
        form = QFormLayout()
        self.mod_name = QLineEdit("Translation tweak")
        form.addRow("Mod name", self.mod_name)
        self.mod_author = QLineEdit()
        form.addRow("Author", self.mod_author)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.export_button = QPushButton("Build mod packages")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._on_export_clicked)
        row.addWidget(self.export_button)
        self.export_note = QLabel("")
        self.export_note.setWordWrap(True)
        row.addWidget(self.export_note, 1)
        layout.addLayout(row)
        return box

    # ------------------------------------------------------------------ loading

    def _populate_languages(self) -> None:
        try:
            languages = available_languages()
        except Exception as error:  # noqa: BLE001
            self.status_label.setText(f"Could not list languages: {error}")
            return
        if not languages:
            self.status_label.setText("No string tables found in the archives.")
            self.load_button.setEnabled(False)
            return
        self.language_box.addItems(list(languages))
        self.reference_box.addItem(_NONE)
        self.reference_box.addItems(list(languages))
        if "eng" in languages:
            self.language_box.setCurrentIndex(languages.index("eng"))
        self.status_label.setText(f"{len(languages)} languages available.")

    def _on_load(self) -> None:
        language = self.language_box.currentText()
        reference = self.reference_box.currentText()
        reference = "" if reference in (_NONE, language) else reference
        if not language:
            return
        self.load_button.setEnabled(False)
        self.status_label.setText(f"Reading {language} from the archives...")
        self._thread = QThread(self)
        self._worker = _LoadWorker(language, reference)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_loaded)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    def _on_loaded(self, data, reference, error: str) -> None:
        self.load_button.setEnabled(True)
        if error or data is None:
            self.status_label.setText(f"Load failed: {error}")
            return
        language = self.language_box.currentText()
        try:
            catalogue = load_catalogue(bytes(data), language)
            if reference is not None:
                attach_reference(catalogue, bytes(reference), self.reference_box.currentText())
        except Exception as err:  # noqa: BLE001
            self.status_label.setText(f"Could not read {language}: {err}")
            return
        self._catalogue = catalogue
        self.model.set_catalogue(catalogue)

        self.category_box.blockSignals(True)
        self.category_box.clear()
        self.category_box.addItem("All groups", None)
        for code, label in sorted(catalogue.categories().items(), key=lambda kv: kv[1]):
            self.category_box.addItem(f"{label} ({code})", code)
        self.category_box.blockSignals(False)

        for widget in (self.search_box, self.category_box, self.edited_only, self.reset_button):
            widget.setEnabled(True)
        reference_note = (
            f", showing {catalogue.reference_language} alongside"
            if catalogue.reference_language else ""
        )
        self.status_label.setText(f"{len(catalogue):,} lines in {language}{reference_note}.")
        self._refresh_view()

    # ---------------------------------------------------------------- filtering

    def _refresh_view(self) -> None:
        catalogue = self._catalogue
        if catalogue is None:
            return
        category = self.category_box.currentData()
        hits = catalogue.find(
            self.search_box.text(),
            category=category,
            edited_only=self.edited_only.isChecked(),
            limit=_MAX_HITS,
        )
        self.model.set_view(hits)
        capped = " (first 5,000)" if len(hits) >= _MAX_HITS else ""
        self.hits_label.setText(f"{len(hits):,} line(s){capped}")
        # `setModel` replaces the selection model, so the connection is made there and
        # not here: reconnecting per filter stacked a duplicate slot on every keystroke.
        self.revert_button.setEnabled(False)
        self._refresh_pending()

    def _on_selection(self, *_args) -> None:
        self.revert_button.setEnabled(bool(self.table.selectionModel().selectedRows()))

    # ------------------------------------------------------------------- edits

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return rows[0].row() if rows else -1

    def _on_revert(self) -> None:
        row = self._selected_row()
        if row >= 0:
            self.model.revert_row(row)
            self._refresh_pending()

    def _on_reset(self) -> None:
        if self._catalogue is None:
            return
        self._catalogue.reset()
        self.model.refresh()
        self._refresh_pending()

    def _refresh_pending(self) -> None:
        catalogue = self._catalogue
        if catalogue is None or not catalogue.edit_count:
            self.pending_label.setText("No changes.")
            self.export_button.setEnabled(False)
            return
        lines = catalogue.describe_changes()
        more = "" if catalogue.edit_count <= len(lines) else f" (+{catalogue.edit_count - len(lines)} more)"
        self.pending_label.setText(
            f"{catalogue.edit_count} line(s) changed: " + "; ".join(lines) + more
        )
        self.export_button.setEnabled(True)

    # ------------------------------------------------------------------ export

    def mod_files(self) -> dict:
        return dict(self._catalogue.changed_files()) if self._catalogue else {}

    def export_mod(self, out_root) -> str:
        catalogue = self._catalogue
        if catalogue is None or not catalogue.edit_count:
            return "Nothing to export: no lines have been changed."
        try:
            results = export_packages(
                catalogue,
                out_root=Path(out_root),
                name=self.mod_name.text().strip() or "Translation tweak",
                author=self.mod_author.text().strip(),
            )
        except Exception as error:  # noqa: BLE001
            return f"Export failed: {error}"
        return f"Wrote {len(results)} package(s) to {out_root}"

    def _on_export_clicked(self) -> None:
        out_root = QFileDialog.getExistingDirectory(self, "Where should the packages go?")
        if out_root:
            self.export_note.setText(self.export_mod(out_root))
