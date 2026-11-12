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

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QStackedWidget, QTabBar, QVBoxLayout, QWidget

#: Documents whose 3D view stays open at once (P15 step 3): past it the one shown
#: longest ago is parked (its view closes; its session, edit and history stay).
#: One constant; Settings states it.
MAX_LOADED_DOCUMENTS = 4
#: Documents open as tabs at once, parked or not.
MAX_OPEN_DOCUMENTS = 12
#: What a document's tab says while it has nothing open.
EMPTY_DOCUMENT_LABEL = "Mesh Editor"
#: Calls every document receives, not only the shown one.
_BROADCAST = frozenset({"set_theme", "sync_ui_font", "set_archive_selection"})
#: The view's own attributes; every other write goes to the shown document.
_OWN = frozenset({"_build_document", "_documents", "_shown", "_closing", "tab_bar", "stack"})


class MeshDocumentsView(QWidget):
    """A tab strip over the open Mesh Editor documents."""

    #: The shown document changed; the argument is its index.
    document_changed = Signal(int)

    def __init__(self, build_document: Callable[[], QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorDocuments")
        self._build_document = build_document
        self._documents: list[QWidget] = []
        #: Documents in the order they were last shown, newest last (for parking).
        self._shown: list[QWidget] = []
        #: Closed documents whose threads are still running; deleted when they end.
        self._closing: list[QWidget] = []
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
        if len(self._documents) >= MAX_OPEN_DOCUMENTS:
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
        if document in self._shown:
            self._shown.remove(document)
        self.stack.removeWidget(document)
        self.tab_bar.removeTab(index)
        self._closing.append(document)
        document.hide()
        self._delete_when_idle(document)
        self.set_active(min(index, len(self._documents) - 1))
        return True

    def _delete_when_idle(self, document: QWidget) -> None:
        """Delete a closed document once none of its threads runs (section 8.7 A6)."""

        if document not in self._closing:
            return
        if _running_threads(document):
            QTimer.singleShot(100, self, lambda current=document: self._delete_when_idle(current))
            return
        self._closing.remove(document)
        document.deleteLater()

    # ----- shutdown reaches every document (section 8.7 A9) -------------------
    def iter_shutdown_workers(self):
        workers = []
        for document in (*self._documents, *self._closing):
            iterator = getattr(document, "iter_shutdown_workers", None)
            if callable(iterator):
                workers.extend(tuple(iterator()))
        return tuple(workers)

    def request_shutdown(self) -> None:
        for document in (*self._documents, *self._closing):
            stop = getattr(document, "request_shutdown", None)
            if callable(stop):
                stop()

    def browse_document(self) -> QWidget | None:
        """The document whose edit is in Browse's view, shown or not (section 8.7 A5)."""

        return next((document for document in self._documents
                     if getattr(getattr(document, "live_edit", None), "viewport_binding", None) is not None), None)

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

    def loaded_documents(self) -> tuple[QWidget, ...]:
        """Documents with a session whose 3D view is not parked."""

        return tuple(document for document in self._documents
                     if _has_session(document) and not getattr(document, "standalone_rust_parked", False))

    def park_beyond_budget(self) -> list[QWidget]:
        """Park the documents shown longest ago until the budget holds (P15 step 3)."""

        parked: list[QWidget] = []
        active = self.active
        candidates = [document for document in self._shown if document is not active]
        candidates += [document for document in self._documents if document not in candidates and document is not active]
        while len(self.loaded_documents()) > MAX_LOADED_DOCUMENTS and candidates:
            document = candidates.pop(0)
            if document not in self.loaded_documents():
                continue
            park = getattr(document, "park_rust_editor", None)
            if callable(park) and park():
                parked.append(document)
        if parked:
            self.refresh_labels()
        return parked

    def __setattr__(self, name: str, value) -> None:
        # The shell also writes the Mesh Editor's state (material context, texture
        # reasons): a name this view does not own goes to the shown document.
        documents = self.__dict__.get("_documents")
        if name in _OWN or not documents or hasattr(type(self), name):
            object.__setattr__(self, name, value)
            return
        setattr(self.active, name, value)

    def _show_document(self, index: int) -> None:
        if 0 <= index < len(self._documents) and self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
        if 0 <= index < len(self._documents):
            document = self._documents[index]
            if document in self._shown:
                self._shown.remove(document)
            self._shown.append(document)
            unpark = getattr(document, "unpark_rust_editor", None)
            if getattr(document, "standalone_rust_parked", False) and callable(unpark):
                unpark()
            self.park_beyond_budget()
            _show_commands_of(document)
        self.refresh_labels()
        self.document_changed.emit(index)


def _show_commands_of(document: QWidget) -> None:
    """The palette offers the shown document's editor commands (section 8.7 E2)."""

    find = getattr(document, "_rust_command_registry", None)
    registry = find() if callable(find) else None
    if registry is None:
        return
    from cdmw.ui.mesh_editor.editor_commands import set_command_owner

    set_command_owner(registry, document)


def _broadcast(documents: list[QWidget], name: str):
    def call(*args, **kwargs):
        result = None
        for document in tuple(documents):
            method = getattr(document, name, None)
            if callable(method):
                result = method(*args, **kwargs)
        return result
    return call


def _running_threads(document: QWidget) -> bool:
    iterator = getattr(document, "iter_shutdown_workers", None)
    if not callable(iterator):
        return False
    for _name, thread, _worker in tuple(iterator()):
        running = getattr(thread, "isRunning", None)
        try:
            if callable(running) and running():
                return True
        except RuntimeError:
            continue
    return False


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

    label = f"{name} *" if has_pending_edit(document) else name
    # A parked document's view is closed; showing it opens the view again.
    return f"{label} (parked)" if getattr(document, "standalone_rust_parked", False) else label


def document_tooltip(document: QWidget) -> str:
    target = getattr(document, "_current_target_entry", None)
    try:
        entry = target() if callable(target) and _has_session(document) else None
    except (AttributeError, RuntimeError, TypeError):
        entry = None
    return str(getattr(entry, "path", "") or "")


__all__ = ["EMPTY_DOCUMENT_LABEL", "MAX_LOADED_DOCUMENTS", "MAX_OPEN_DOCUMENTS", "MeshDocumentsView",
           "document_label"]
