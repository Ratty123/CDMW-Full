"""Document tabs in the Mesh Editor (P15 step 2).

Each open document is a Mesh Editor of its own: an archive model under edit, a
mesh from disk or a draft, with its session, its pending edit, its history and
the viewport that shows it. A tab strip above them switches which one shows;
every document stays loaded meanwhile. Finish and Discard act on the shown
document, and closing a document's tab with an unfinished edit asks Finish,
Discard or Keep editing, as replacing an edit does.

The shell keeps talking to "the Mesh Editor": this view answers for the shown
document (attribute access falls through to it), and passes theme, text size
and archive selection changes to every document.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QTabBar, QVBoxLayout, QWidget

#: Documents kept loaded at once (P15 step 3: past it the oldest inactive one is
#: parked). One constant; Settings states it.
MAX_LOADED_DOCUMENTS = 4
#: What a document's tab says while it has nothing open.
EMPTY_DOCUMENT_LABEL = "Mesh Editor"
#: Calls every document receives, not only the shown one.
_BROADCAST = frozenset({"set_theme", "sync_ui_font", "set_archive_selection"})


class MeshDocumentsView(QWidget):
    """A tab strip over the open Mesh Editor documents."""

    #: The shown document changed; the argument is its index.
    document_changed = Signal(int)

    def __init__(self, build_document: Callable[[], QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorDocuments")
        self._build_document = build_document
        self._documents: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tab_bar = QTabBar(self)
        self.tab_bar.setObjectName("MeshEditorDocumentTabs")
        self.tab_bar.setDocumentMode(True)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.currentChanged.connect(self._show_document)
        self.tab_bar.tabCloseRequested.connect(self.close_document)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.tab_bar)
        layout.addWidget(self.stack, 1)
        self.add_document()

    # ----- the documents ------------------------------------------------------
    @property
    def documents(self) -> tuple[QWidget, ...]:
        return tuple(self._documents)

    @property
    def active(self) -> QWidget:
        index = self.stack.currentIndex()
        return self._documents[index if 0 <= index < len(self._documents) else 0]

    def add_document(self) -> QWidget:
        """Open an empty document and show it."""

        document = self._build_document()
        self._documents.append(document)
        self.stack.addWidget(document)
        self.tab_bar.addTab(EMPTY_DOCUMENT_LABEL)
        signal = getattr(document, "status_message_requested", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(lambda *_args: self.refresh_labels())
        self.set_active(len(self._documents) - 1)
        return document

    def set_active(self, index: int) -> None:
        if 0 <= index < len(self._documents):
            self.tab_bar.setCurrentIndex(index)
            self._show_document(index)

    def index_of(self, document: QWidget) -> int:
        return self._documents.index(document) if document in self._documents else -1

    def open_new_document(self) -> QWidget | None:
        """A new document for another mesh, or None when the budget is full.

        The shown document keeps its edit; only an empty one is reused.
        """

        empty = next((document for document in self._documents if not _has_session(document)), None)
        if empty is not None:
            self.set_active(self.index_of(empty))
            return empty
        if len(self._documents) >= MAX_LOADED_DOCUMENTS:
            return None
        return self.add_document()

    def close_document(self, index: int) -> bool:
        """Close one document; an unfinished edit asks Finish, Discard or Keep editing."""

        from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import DISCARD, NONE, resolve_pending_edit

        if not 0 <= index < len(self._documents):
            return False
        document = self._documents[index]
        self.set_active(index)
        answer = resolve_pending_edit(self, document)
        if answer not in (DISCARD, NONE):
            return False  # Finish runs first, or the user keeps editing
        close = getattr(document, "close_standalone_session", None)
        if callable(close) and _has_session(document):
            close()
        if len(self._documents) == 1:
            show_empty = getattr(document, "show_empty_state", None)
            if callable(show_empty):
                show_empty()
            self.refresh_labels()
            return True
        self._documents.pop(index)
        self.stack.removeWidget(document)
        self.tab_bar.removeTab(index)
        document.deleteLater()
        self.set_active(min(index, len(self._documents) - 1))
        return True

    def pending_documents(self) -> tuple[QWidget, ...]:
        """Documents with an unfinished edit, for the close guard."""

        from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import has_pending_edit

        return tuple(document for document in self._documents if has_pending_edit(document))

    def refresh_labels(self) -> None:
        for index, document in enumerate(self._documents):
            self.tab_bar.setTabText(index, document_label(document))
            self.tab_bar.setTabToolTip(index, document_tooltip(document))
        self.tab_bar.setVisible(len(self._documents) > 1)

    # ----- the shell talks to the shown document ------------------------------
    def __getattr__(self, name: str):
        # Only reached for names this view does not have itself.
        if name.startswith("__") or name in {"_documents", "stack", "tab_bar", "_build_document"}:
            raise AttributeError(name)
        try:
            documents = object.__getattribute__(self, "_documents")
        except AttributeError:
            raise AttributeError(name) from None
        if not documents:
            raise AttributeError(name)
        if name in _BROADCAST:
            return _broadcast(documents, name)
        return getattr(self.active, name)

    def _show_document(self, index: int) -> None:
        if 0 <= index < len(self._documents) and self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
        self.refresh_labels()
        self.document_changed.emit(index)


def _broadcast(documents: list[QWidget], name: str):
    def call(*args, **kwargs):
        result = None
        for document in tuple(documents):
            method = getattr(document, name, None)
            if callable(method):
                result = method(*args, **kwargs)
        return result
    return call


def _has_session(document: QWidget) -> bool:
    has = getattr(document, "has_active_standalone_session", None)
    try:
        return bool(has()) if callable(has) else False
    except (AttributeError, RuntimeError, TypeError):
        return False


def document_label(document: QWidget) -> str:
    """The tab's text: the file the document edits."""

    target = getattr(document, "_current_target_entry", None)
    try:
        entry = target() if callable(target) and _has_session(document) else None
    except (AttributeError, RuntimeError, TypeError):
        entry = None
    name = str(getattr(entry, "basename", "") or "")
    if not name:
        return EMPTY_DOCUMENT_LABEL
    from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import has_pending_edit

    return f"{name} *" if has_pending_edit(document) else name


def document_tooltip(document: QWidget) -> str:
    target = getattr(document, "_current_target_entry", None)
    try:
        entry = target() if callable(target) and _has_session(document) else None
    except (AttributeError, RuntimeError, TypeError):
        entry = None
    return str(getattr(entry, "path", "") or "")


__all__ = ["EMPTY_DOCUMENT_LABEL", "MAX_LOADED_DOCUMENTS", "MeshDocumentsView", "document_label"]
