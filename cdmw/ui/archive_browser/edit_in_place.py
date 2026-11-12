"""Edit mesh where Browse Archives shows it (P4 V3).

"Open in Mesh Editor" on a model Browse already shows switches Browse's own
viewport into edit mode: the helper that draws the preview enters edit mode in
the same window, so the camera, the textures and the picture stay. The Mesh
Editor tab keeps the session, the undo history and Finish; only the viewport
is Browse's.

While editing:
- the controls and file list collapse to narrow strips that open while the
  pointer is over them, so the editor's panels get the room;
- the details, warnings and the preview's own view controls are hidden, since
  the editor's Inspector and view options replace them;
- a banner says which file is being edited. Selecting another file shows its
  details only; the banner then offers to preview it instead, which asks
  Finish, Discard or Keep editing first.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

#: Width of a collapsed pane while editing.
STRIP_WIDTH = 28
#: Idle time after a model shows before the Mesh Editor tab is created ahead of use.
_PREWARM_DELAY_MS = 1500
_HOVER_COLLAPSE_MS = 400


class _StripHover(QObject):
    """Open a collapsed pane while the pointer is over it."""

    def __init__(self, layout: "BrowseEditLayout") -> None:
        super().__init__()
        self._layout = layout
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(layout.collapse_strips)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        if kind == QEvent.Type.Enter:
            self._collapse_timer.stop()
            self._layout.open_strips()
        elif kind == QEvent.Type.Leave:
            self._collapse_timer.start(_HOVER_COLLAPSE_MS)
        return False


class BrowseEditLayout:
    """Browse Archives' layout while its viewport holds an edit."""

    def __init__(self, browser: QWidget) -> None:
        self.browser = browser
        self.active = False
        self.entry = None
        self._saved_sizes: list[int] = []
        self._saved_minimums: list[int] = []
        self._hidden: list[QWidget] = []
        self._hover = _StripHover(self)
        self.banner = self._build_banner()

    # ----- banner -------------------------------------------------------------
    def _build_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("ArchiveEditingBanner")
        row = QHBoxLayout(banner)
        row.setContentsMargins(8, 4, 8, 4)
        self.banner_label = QLabel("")
        self.banner_label.setObjectName("ArchiveEditingBannerLabel")
        self.preview_selected_button = QPushButton("Preview selected file instead")
        self.preview_selected_button.setObjectName("ArchiveEditingPreviewSelectedButton")
        self.preview_selected_button.setVisible(False)
        # P4 V5: the edit moves to the Mesh Editor tab as it is, without reopening.
        self.promote_button = QPushButton("Move to the Mesh Editor tab")
        self.promote_button.setObjectName("ArchiveEditingPromoteButton")
        row.addWidget(self.banner_label, stretch=1)
        row.addWidget(self.preview_selected_button)
        row.addWidget(self.promote_button)
        banner.setVisible(False)
        layout = getattr(self.browser, "archive_preview_main_layout", None)
        if layout is not None:
            layout.insertWidget(0, banner)
        return banner

    def set_status(self, message: str) -> None:
        label = getattr(self.entry, "basename", "") or getattr(self.entry, "path", "") or ""
        text = f"Editing {label}" if label else "Editing"
        if message:
            text = f"{text}: {message}"
        self.banner_label.setText(text)

    def selection_changed(self, selected_entry: object) -> None:
        """Another file is selected: offer to preview it instead of the edit."""

        if not self.active:
            return
        same = (selected_entry is None or self.entry is None
                or getattr(selected_entry, "identity", None) == getattr(self.entry, "identity", None))
        self.preview_selected_button.setVisible(not same)

    # ----- layout -------------------------------------------------------------
    def _strip_panes(self) -> list[QWidget]:
        splitter = getattr(self.browser, "archive_splitter", None)
        if splitter is None or splitter.count() < 3:
            return []
        return [splitter.widget(0), splitter.widget(1)]

    def enter(self, entry: object) -> None:
        if self.active:
            return
        self.active = True
        self.entry = entry
        splitter = getattr(self.browser, "archive_splitter", None)
        panes = self._strip_panes()
        if splitter is not None and panes:
            self._saved_sizes = list(splitter.sizes())
            self._saved_minimums = [pane.minimumWidth() for pane in panes]
            for pane in panes:
                pane.setMinimumWidth(STRIP_WIDTH)
                pane.installEventFilter(self._hover)
            self.collapse_strips()
        self._hidden = []
        for name in ("archive_preview_meta_label", "archive_preview_health_label",
                     "archive_preview_warning_label", "archive_item_set_components",
                     "archive_texture_refs_group", "archive_character_context_panel"):
            widget = getattr(self.browser, name, None)
            if isinstance(widget, QWidget) and widget.isVisible():
                widget.setVisible(False)
                self._hidden.append(widget)
        controls = getattr(self.browser, "archive_view_controls_layout", None)
        if controls is not None:
            for index in range(controls.count()):
                widget = controls.itemAt(index).widget()
                if widget is not None and widget.isVisible():
                    widget.setVisible(False)
                    self._hidden.append(widget)
        self.set_status("")
        self.preview_selected_button.setVisible(False)
        self.banner.setVisible(True)

    def leave(self) -> None:
        if not self.active:
            return
        self.active = False
        splitter = getattr(self.browser, "archive_splitter", None)
        for pane, minimum in zip(self._strip_panes(), self._saved_minimums):
            pane.removeEventFilter(self._hover)
            pane.setMinimumWidth(minimum)
        if splitter is not None and self._saved_sizes:
            splitter.setSizes(self._saved_sizes)
        for widget in self._hidden:
            try:
                widget.setVisible(True)
            except RuntimeError:
                pass
        self._hidden = []
        self.banner.setVisible(False)
        self.preview_selected_button.setVisible(False)
        self.entry = None

    def collapse_strips(self) -> None:
        splitter = getattr(self.browser, "archive_splitter", None)
        if not self.active or splitter is None or not self._saved_sizes:
            return
        total = sum(self._saved_sizes)
        splitter.setSizes([STRIP_WIDTH, STRIP_WIDTH, max(STRIP_WIDTH, total - 2 * STRIP_WIDTH)])

    def open_strips(self) -> None:
        splitter = getattr(self.browser, "archive_splitter", None)
        if not self.active or splitter is None or len(self._saved_sizes) < 3:
            return
        total = sum(self._saved_sizes)
        first, second = self._saved_sizes[0], self._saved_sizes[1]
        splitter.setSizes([first, second, max(STRIP_WIDTH, total - first - second)])


class BrowseEditInPlaceMixin:
    """The Archive Browser's half of editing in its own viewport."""

    def _archive_edit_layout(self) -> BrowseEditLayout:
        layout = getattr(self, "_edit_in_place_layout", None)
        if layout is None:
            layout = self._edit_in_place_layout = BrowseEditLayout(self)
            layout.preview_selected_button.clicked.connect(self._preview_selected_instead_of_edit)
            layout.promote_button.clicked.connect(self._promote_edit_to_tab)
            tree = getattr(self, "archive_tree", None)
            if tree is not None:
                tree.itemSelectionChanged.connect(self._edit_in_place_selection_changed)
        return layout

    def _schedule_mesh_editor_prewarm(self) -> None:
        """Create the Mesh Editor tab once, while Browse is idle after showing a model.

        Creating it took 0.6 s on the click that opened the first edit; done ahead,
        that click shows the edit at once (P4 V4). Never during a click's work: it
        waits until no preview load or texture request is running.
        """

        if getattr(self, "_mesh_editor_prewarm_scheduled", False):
            return
        self._mesh_editor_prewarm_scheduled = True
        QTimer.singleShot(_PREWARM_DELAY_MS, self._prewarm_mesh_editor_tab)

    def _prewarm_mesh_editor_tab(self) -> None:
        shell = getattr(self, "shell", None)
        tab = getattr(shell, "mesh_editor_tab", None)
        widget_if_created = getattr(tab, "widget_if_created", None)
        ensure = getattr(tab, "ensure_widget", None)
        if not callable(ensure) or (callable(widget_if_created) and widget_if_created() is not None):
            return
        busy = (getattr(self, "archive_preview_worker", None) is not None
                or bool(getattr(self, "_archive_texture_request_loading", False))
                or bool(getattr(self, "archive_preview_texture_upgrade_pending", False)))
        if busy:
            QTimer.singleShot(_PREWARM_DELAY_MS, self._prewarm_mesh_editor_tab)
            return
        try:
            ensure()
        except RuntimeError:
            pass

    def edit_in_place_blocker(self, entry: object) -> str:
        """Why Browse's viewport cannot hold an edit of ``entry`` now ("" when it can)."""

        host = getattr(self, "archive_d3d11_preview_host", None)
        controller = getattr(host, "controller", None)
        check = getattr(controller, "edit_in_place_blocker", None)
        if not callable(check):
            return "Browse's viewport cannot edit in place"
        if getattr(self, "archive_preview_stack", None) is not None:
            try:
                if self.archive_preview_stack.currentWidget() is not host:
                    return "Browse is not showing this model in 3D"
            except RuntimeError:
                return "Browse's viewport is closed"
        return str(check() or "")

    def begin_edit_in_place(self, entry: object):
        """A viewport binding for the Mesh Editor, or None to open the edit in its tab."""

        if self.edit_in_place_blocker(entry):
            return None
        from cdmw.ui.mesh_editor.live_edit.browse_viewport import BrowseViewportBinding

        binding = BrowseViewportBinding(self.archive_d3d11_preview_host,
                                        str(getattr(entry, "basename", "") or ""), self)
        layout = self._archive_edit_layout()
        binding.status.connect(self._edit_in_place_status)
        binding.ended.connect(self._edit_in_place_ended)
        layout.enter(entry)
        self._edit_in_place_binding = binding
        return binding

    def _promote_edit_to_tab(self) -> None:
        """Move the edit in Browse's viewport to the Mesh Editor tab (P4 V5)."""

        shell = getattr(self, "shell", None)
        tab = self._browse_edit_document()
        live = getattr(tab, "live_edit", None)
        if live is None or getattr(live, "viewport_binding", None) is None:
            return
        self._show_browse_edit_document(tab)
        activate = getattr(shell, "_activate_tool_key", None)
        if callable(activate):
            activate("mesh_editor")  # its host window exists and has its size first

        def promote() -> None:
            if not live.promote_to_tab():
                set_status = getattr(shell, "set_status_message", None)
                if callable(set_status):
                    set_status("The edit could not move to the Mesh Editor tab now.", error=True)

        QTimer.singleShot(0, promote)

    def _browse_edit_document(self):
        """The Mesh Editor document whose edit is in this viewport, not the one shown (8.7 A5)."""

        shell = getattr(self, "shell", None)
        owner = getattr(shell, "mesh_editor_tab", None)
        created = getattr(owner, "widget_if_created", None)
        view = created() if callable(created) else owner
        find = getattr(view, "browse_document", None)
        document = find() if callable(find) else None
        return document if document is not None else view

    def _show_browse_edit_document(self, document) -> None:
        shell = getattr(self, "shell", None)
        owner = getattr(shell, "mesh_editor_tab", None)
        created = getattr(owner, "widget_if_created", None)
        view = created() if callable(created) else owner
        index_of, set_active = getattr(view, "index_of", None), getattr(view, "set_active", None)
        if callable(index_of) and callable(set_active) and index_of(document) >= 0:
            set_active(index_of(document))

    @property
    def editing_in_place(self) -> bool:
        binding = getattr(self, "_edit_in_place_binding", None)
        return binding is not None and not binding.is_ended

    def _edit_in_place_status(self, kind: int, message: str) -> None:
        layout = self._archive_edit_layout()
        from cdmw.ui.mesh_editor.live_edit.browse_viewport import STATUS_EDITING

        layout.set_status("" if kind == STATUS_EDITING else message)

    def _edit_in_place_ended(self) -> None:
        self._edit_in_place_binding = None
        self._archive_edit_layout().leave()

    def _edit_in_place_selection_changed(self) -> None:
        layout = getattr(self, "_edit_in_place_layout", None)
        if layout is None or not layout.active:
            return
        current = getattr(self, "_current_archive_entry", None)
        layout.selection_changed(current() if callable(current) else None)

    def _preview_selected_instead_of_edit(self) -> None:
        """Preview the selected file: ask Finish, Discard or Keep editing first."""

        from cdmw.ui.mesh_editor.live_edit.end_edit_prompt import DISCARD, resolve_pending_edit

        tab = self._browse_edit_document()
        layout = self._archive_edit_layout()
        label = getattr(layout.entry, "basename", "") or ""
        answer = resolve_pending_edit(self, tab, file_label=label)
        if answer == DISCARD or answer == "none":
            binding = getattr(self, "_edit_in_place_binding", None)
            if binding is not None:
                binding.end()  # the newest selection loads once the viewport is free


__all__ = ["BrowseEditInPlaceMixin", "BrowseEditLayout", "STRIP_WIDTH"]
