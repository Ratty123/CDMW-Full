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

**Translations can be produced, not only edited.** The panel could always rewrite a line
by hand, which is the wrong tool for 187,521 of them. "Translate with AI" sends the lines
you have filtered to a model on your own API key, checks the markup in every reply, and
writes the ones that came back intact into the same edit map as a hand edit -- so the
result is reviewable, revertable and exported by the same button.

Loading reads straight from the archives on a worker, because a language table is 16-25
MB and the UI thread must not stall on it. Listing the languages runs there too: the
sweep behind it is seconds long the first time on a given install (see
`language_index.py`), and it used to run inside this constructor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional

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
    default_game_root,
    export_packages,
    load_catalogue,
    read_language,
)
from .table_model import TEXT, TranslationTableModel

_NONE = "(none)"
#: Cap the rows a search returns. Nobody reads 90,000 hits, and building that view
#: costs more than the search itself.
_MAX_HITS = 5000

#: Worker threads outlive the widget that started them, deliberately. A `QThread` parented
#: to the tab is destroyed with it, and destroying a running one is an access violation --
#: which is exactly what closing or reloading the tab mid-scan would do. Holding them here
#: until they finish lets Qt sever the signal to the dead receiver and end the thread
#: cleanly instead.
_LIVE_THREADS: set = set()


def _run_detached(thread: QThread, worker: QObject, *, on_done) -> None:
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(on_done)
    worker.done.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(lambda: _LIVE_THREADS.discard(thread))
    thread.finished.connect(thread.deleteLater)
    _LIVE_THREADS.add(thread)
    thread.start()


class _LanguageWorker(QObject):
    """Lists the archives' languages off the UI thread.

    Cold, this walks all 33 package tables and takes seconds; warm, it is a `stat` each.
    It ran in the tab's constructor before, which is what made opening the tab lag.
    """

    done = Signal(object, str)

    def __init__(self, game_root: Optional[str]) -> None:
        super().__init__()
        self._game_root = game_root

    def run(self) -> None:
        try:
            root = Path(self._game_root) if self._game_root else None
            languages = available_languages(root)
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            self.done.emit(None, str(error))
            return
        self.done.emit(tuple(languages), "")


class _LoadWorker(QObject):
    done = Signal(object, object, str)

    def __init__(self, language: str, reference: str, game_root: Optional[str] = None) -> None:
        super().__init__()
        self._language = language
        self._reference = reference
        self._game_root = game_root

    def run(self) -> None:
        root = Path(self._game_root) if self._game_root else None
        try:
            data = read_language(self._language, root)
            reference = read_language(self._reference, root) if self._reference else None
        except Exception as error:  # noqa: BLE001 - report, never take the window down
            self.done.emit(None, None, str(error))
            return
        self.done.emit(data, reference, "")


class TranslationStudioTab(QWidget):
    """Search, retranslate and export the game's string tables."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        settings=None,
        window=None,
    ) -> None:
        super().__init__(parent)
        self._catalogue: Optional[TranslationCatalogue] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_LoadWorker] = None
        self._language_thread: Optional[QThread] = None
        self._language_worker: Optional[_LanguageWorker] = None
        self._settings = settings
        self._window = window
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
        self.ai_button = QPushButton("Translate with AI...")
        self.ai_button.setToolTip(
            "Send the lines you have filtered to a translation model on your own API key."
        )
        self.ai_button.clicked.connect(self._on_ai_translate)
        self.ai_button.setEnabled(False)
        actions.addWidget(self.ai_button)
        self.ai_settings_button = QPushButton("AI settings...")
        self.ai_settings_button.setToolTip("Choose a provider and paste an API key.")
        self.ai_settings_button.clicked.connect(self._on_ai_settings)
        actions.addWidget(self.ai_settings_button)
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

    def _game_root(self) -> str:
        """The archive root the user configured, read the way the app itself reads it.

        `MainWindow.settings` is a `QSettings`, not the `AppConfig` dataclass, so the
        live value lives on the Settings widget -- the same trap `PlacementStudioTab`
        documents. Empty means "wherever the corpus defaults to", which is what this
        panel used unconditionally before.
        """

        edit = getattr(self._window, "archive_package_root_edit", None)
        if edit is not None:
            try:
                text = str(edit.text() or "").strip()
            except Exception:  # noqa: BLE001 - a widget torn down mid-teardown
                text = ""
            if text:
                return text
        settings = self._settings
        getter = getattr(settings, "value", None) if settings is not None else None
        if callable(getter):
            for key in ("archive_package_root", "paths/archive_package_root"):
                text = str(getter(key, "") or "").strip()
                if text:
                    return text
        return ""

    def _populate_languages(self) -> None:
        """List the languages, on a worker unless the answer is already cached.

        Warm, this is one `stat` per package and worth no thread at all; cold it is a
        sweep of all 33 package tables, which is what used to run right here and made
        opening the tab lag. See `language_index.py`.
        """

        from .language_index import is_warm

        root = self._game_root() or None
        try:
            warm = is_warm(Path(root) if root else default_game_root())
        except Exception:  # noqa: BLE001 - an unreadable root is the worker's news to break
            warm = False
        if warm:
            worker = _LanguageWorker(root)
            worker.done.connect(self._on_languages)
            worker.run()
            return

        self.load_button.setEnabled(False)
        self.status_label.setText("Listing the languages in the archives (first time only)...")
        self._language_thread = QThread()
        self._language_worker = _LanguageWorker(root)
        _run_detached(self._language_thread, self._language_worker, on_done=self._on_languages)

    def _on_languages(self, languages, error: str) -> None:
        if error or languages is None:
            self.status_label.setText(f"Could not list languages: {error}")
            return
        languages = tuple(languages)
        if not languages:
            self.status_label.setText(
                "No string tables found in the archives. Check the game path under "
                "Settings -> Archive Locations."
            )
            return
        self.language_box.addItems(list(languages))
        self.reference_box.addItem(_NONE)
        self.reference_box.addItems(list(languages))
        if "eng" in languages:
            self.language_box.setCurrentIndex(languages.index("eng"))
        self.load_button.setEnabled(True)
        self.status_label.setText(f"{len(languages)} languages available.")

    def _on_load(self) -> None:
        language = self.language_box.currentText()
        reference = self.reference_box.currentText()
        reference = "" if reference in (_NONE, language) else reference
        if not language:
            return
        self.load_button.setEnabled(False)
        self.status_label.setText(f"Reading {language} from the archives...")
        self._thread = QThread()
        self._worker = _LoadWorker(language, reference, self._game_root() or None)
        _run_detached(self._thread, self._worker, on_done=self._on_loaded)

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

        for widget in (
            self.search_box,
            self.category_box,
            self.edited_only,
            self.reset_button,
            self.ai_button,
        ):
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

    # ---------------------------------------------------------------------- AI

    def _lines_for(self, indexes) -> list:
        """Entry indexes as the lines a model gets, with their group as context.

        The group label is worth the two extra words: "Item name" and "Quest dialogue"
        are translated differently, and the model cannot tell them apart from the text.
        """

        from .ai_translate import Line

        catalogue = self._catalogue
        if catalogue is None:
            return []
        categories = catalogue.categories()
        out = []
        for index in indexes:
            row = catalogue.row(index)
            if not row.text.strip():
                continue  # an empty line has nothing to translate
            out.append(
                Line(index=index, text=row.text, context=str(categories.get(row.category, "")))
            )
        return out

    def ai_scopes(self) -> list:
        """The choices the translate dialog offers, largest last and never preselected."""

        catalogue = self._catalogue
        if catalogue is None:
            return []
        scopes = []
        selected = self._selected_row()
        if selected >= 0:
            entry = self.model.entry_index(selected)
            if entry is not None:
                scopes.append(("The selected line", self._lines_for([entry])))

        shown = tuple(self.model.entry_index(row) for row in range(self.model.rowCount()))
        shown = tuple(index for index in shown if index is not None)
        scopes.append(("The lines shown below", self._lines_for(shown)))

        category = self.category_box.currentData()
        needle = self.search_box.text()
        if needle.strip() or category is not None:
            matching = catalogue.find(needle, category=category,
                                      edited_only=self.edited_only.isChecked())
            if len(matching) > len(shown):
                scopes.append(("Every line matching this search", self._lines_for(matching)))
        else:
            scopes.append(
                (f"Every line in {catalogue.language}", self._lines_for(range(len(catalogue))))
            )
        return scopes

    def apply_ai_translations(self, translations: Mapping[int, str]) -> int:
        """Fold a batch into the same edit map a hand edit uses. Returns lines changed."""

        catalogue = self._catalogue
        if catalogue is None:
            return 0
        applied = 0
        for index, text in translations.items():
            try:
                if catalogue.set_text(int(index), str(text)):
                    applied += 1
            except Exception:  # noqa: BLE001 - one bad index must not lose the batch
                continue
        if applied:
            self.model.refresh()
            self._refresh_pending()
        return applied

    def _on_ai_settings(self) -> None:
        from .ai_panel import ProviderSettingsDialog

        ProviderSettingsDialog(self).exec()

    def _on_ai_translate(self) -> None:
        from .ai_panel import TranslateDialog

        catalogue = self._catalogue
        if catalogue is None:
            return
        scopes = [(label, lines) for label, lines in self.ai_scopes() if lines]
        if not scopes:
            self.status_label.setText("Nothing to translate: no lines are in view.")
            return
        dialog = TranslateDialog(
            scopes=scopes,
            working_language=catalogue.language,
            apply_translations=self.apply_ai_translations,
            parent=self,
        )
        dialog.exec()
        self._refresh_view()

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
