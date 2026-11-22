"""When the Mesh Editor's Textures panel and Texture Editor panel are shown, and how large.

Fredric, 2026-11-17: the panels are off until asked for ("it shouldn't be open per
default, but it should be a clear option to click"), they go when the Mesh Editor closes
or loads another mesh, and they open at a usable size instead of a crushed strip. Later
the same day: "you can close only the texture list and keep the texture you opened/
editing open, so you get a bigger workspace".

One object decides, so no saved dock layout, tab switch or reload can show or hide a
panel on its own:

* the Textures panel shows when the user turned it on (the Textures button, remembered
  in the settings) and a mesh's textures are listed;
* the Texture Editor panel shows once a texture was opened in it while a mesh is open,
  whether the list shows or not, and goes again when it is closed or the mesh is;
* hiding never drops an edit: the edits live with the document, not with the panels.

Sizes are logical pixels that follow the font, so they hold at 100 % and 150 %.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QDockWidget, QWidget

from cdmw.ui.layout_utils import scaled_px

#: Whether the user wants the Textures panel shown (off until they ask).
SHOWN_KEY = "mesh_editor/textures_panel_shown"
#: The version of the default sizes last applied to this user's layout. A layout saved
#: before the panels had minimum sizes can hold a crushed strip; a newer version sizes
#: the panels once more.
SIZES_KEY = "mesh_editor/texture_panels_sizes"
SIZES_VERSION = 3

#: The Textures panel's default share and bounds (at 11pt reference; ~380-430px at 9-10pt).
LIST_WIDTH_SHARE = 0.25
LIST_MIN_DEFAULT_WIDTH = 440
LIST_MAX_DEFAULT_WIDTH = 490
LIST_MAX_WIDTH_SHARE = 0.34
#: The two panels' share of the editor's width once a texture is open beside the model.
EDITOR_WIDTH_SHARE = 0.45
#: The list's share of the panels' height while the Texture Editor is under it.
LIST_HEIGHT_SHARE = 0.3
#: The Texture Editor's share of the editor's width while the list is hidden: the canvas
#: is narrower than it is tall then, so the width is what draws the texture larger.
WIDE_WIDTH_SHARE = 0.5
#: The least width the 3D view keeps beside the wide Texture Editor (logical pixels).
VIEW_MIN_WIDTH = 480
#: The share of the editor's width the user dragged the wide Texture Editor to.
WIDE_KEY = "mesh_editor/texture_editor_wide_share"
#: How far the width may move by itself (layout rounding) before it counts as a drag.
DRAG_SLACK = 4


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class TexturePanels(QObject):
    """Shows, hides and sizes the two texture panels of one Mesh Editor page."""

    #: The user's choice changed (the Textures button follows it).
    wanted_changed = Signal(bool)

    def __init__(self, host: QWidget, textures: QDockWidget, tools: QDockWidget | None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent or host)
        self.host = host
        self.textures = textures
        self.tools = tools
        self.settings: object = None
        self._wanted = False
        self._suppressed = False
        self._texture_open = False
        self._list_sized = False
        self._editor_sized = False
        self._split_sized = False
        #: Which panels show: "both", "editor" (the list hidden), "list" or "".
        self._mode = ""
        #: The width fit the layout still owes for the mode just entered.
        self._pending_width = ""
        #: The side's width beside the list, given back when the list shows again.
        self._narrow_width = 0
        #: The Textures list width before opening the Texture Editor, restored on close.
        self._list_only_width = 0
        #: The Texture Editor + list width before closing the Texture Editor, restored on reopen.
        self._both_width = 0
        #: The wide width last set, to tell the user's drag from it.
        self._applied_wide = 0
        #: The share of the width the user dragged the wide side to (0: not dragged).
        self._wide_share = 0.0
        self._fit_sizes_timer = QTimer(self)
        self._fit_sizes_timer.setSingleShot(True)
        self._fit_sizes_timer.setInterval(0)
        self._fit_sizes_timer.timeout.connect(self._fit_sizes)
        session_shown = getattr(textures, "session_shown", None)
        if session_shown is not None:
            session_shown.connect(lambda _shown: self.apply())
        closed = getattr(textures, "close_requested", None)
        if closed is not None:
            closed.connect(lambda: self.set_wanted(False))
        # A dock's own show and hide action (the host's right-click menu) is off: only
        # this object shows a panel.
        for dock in (textures, tools):
            if dock is not None:
                dock.toggleViewAction().setVisible(False)
                dock.toggleViewAction().setEnabled(False)
        if tools is not None:
            tools.texture_opened.connect(self._on_texture_opened)
            tools.emptied.connect(self._on_editor_emptied)
            tools.close_requested.connect(self._on_editor_closed)
        self.apply()

    # ----- the user's choice ----------------------------------------------------
    def use_settings(self, settings: object) -> None:
        """Read the remembered choice; later changes are saved there."""

        self.settings = settings
        value = settings.value(SHOWN_KEY, None) if settings is not None else None
        self._wanted = _as_bool(value, False)
        try:
            share = float(settings.value(WIDE_KEY, 0) or 0) if settings is not None else 0.0
        except (TypeError, ValueError):
            share = 0.0
        self._wide_share = share if 0.1 <= share <= 0.9 else 0.0
        self.wanted_changed.emit(self._wanted)
        self.apply()

    @property
    def wanted(self) -> bool:
        return self._wanted

    def set_wanted(self, wanted: bool) -> None:
        wanted = bool(wanted)
        if wanted and self.tools is not None and getattr(self.tools, "_editor_factory", None) is None:
            from cdmw.ui.mesh_editor.texture_tools_dock import prewarm_texture_editor_imports

            prewarm_texture_editor_imports()
        if wanted != self._wanted:
            self._wanted = wanted
            if self.settings is not None:
                try:
                    self.settings.setValue(SHOWN_KEY, wanted)
                except RuntimeError:
                    pass  # the page is being torn down
            self.wanted_changed.emit(wanted)
        self.apply()

    # ----- what is shown --------------------------------------------------------
    @property
    def session_open(self) -> bool:
        return bool(getattr(self.textures, "has_session", False))

    @property
    def texture_open(self) -> bool:
        return self._texture_open

    @property
    def suppressed(self) -> bool:
        return self._suppressed

    def set_suppressed(self, suppressed: bool) -> None:
        """Temporarily suppress both panels (e.g. during Hair Tools) without altering ``wanted``."""

        suppressed = bool(suppressed)
        if suppressed != self._suppressed:
            self._suppressed = suppressed
            self.apply()

    def apply(self) -> None:
        """Show or hide both panels as the rule above says. Each goes on its own: with
        the list hidden, the Texture Editor has the whole side."""

        show_list = (not self._suppressed) and self._wanted and self.session_open
        show_editor = (not self._suppressed) and self.session_open and self._texture_open and self.tools is not None
        mode = "both" if show_list and show_editor else "editor" if show_editor else "list" if show_list else ""
        self._enter_mode(mode)
        if self.tools is not None and self.tools.isHidden() == show_editor:
            self.tools.setVisible(show_editor)
        if self.textures.isHidden() == show_list:
            self.textures.setVisible(show_list)
        if show_list or show_editor:
            # After the layout has placed the panels: sizes need the host's real size.
            if not self._fit_sizes_timer.isActive():
                self._fit_sizes_timer.start()

    def _on_texture_opened(self) -> None:
        # Shows the Texture Editor only: the list stays as the user left it, so a texture
        # Undo brings forward does not reopen a list they closed.
        self._texture_open = True
        self.apply()

    def _on_editor_closed(self) -> None:
        # Hidden, not emptied: the texture and its edits stay, and opening it shows them.
        self._texture_open = False
        self.apply()

    def _on_editor_emptied(self) -> None:
        self._texture_open = False
        self.apply()

    # ----- sizes ----------------------------------------------------------------
    def _sizes_are_current(self) -> bool:
        if self.settings is None:
            return self._list_sized
        try:
            return int(self.settings.value(SIZES_KEY, 0) or 0) >= SIZES_VERSION
        except (TypeError, ValueError):
            return False

    def _fit_sizes(self) -> None:
        try:
            self._fit_list()
            self._fit_editor()
            self._fit_width()
        except RuntimeError:
            pass  # the page went away before the timer ran

    # ----- the side's width with the list hidden --------------------------------
    def _docked_width(self) -> int:
        tools = self.tools
        if tools is None or tools.isHidden() or tools.isFloating():
            return 0
        return tools.width()

    def _list_docked_width(self) -> int:
        textures = self.textures
        if textures.isHidden() or textures.isFloating():
            return 0
        return textures.width()

    def _enter_mode(self, mode: str) -> None:
        """Note what the side's width must do when the panels shown change; the width
        itself is set once the layout has placed them (``_fit_width``)."""

        previous = self._mode
        if mode == previous:
            return
        self._mode = mode
        if previous == "editor":
            self._remember_drag()
            self._applied_wide = 0
            if mode != "both":
                self._narrow_width = 0  # nothing to give back to; the next run starts afresh
        if previous == "both" and mode == "editor":
            # The width beside the list, before the side widens.
            self._narrow_width = self._docked_width()
        elif previous == "list" and mode == "both":
            self._list_only_width = self._list_docked_width()
        elif previous == "both" and mode == "list":
            self._both_width = self._docked_width()
        elif mode == "":
            self._list_only_width = 0
            self._both_width = 0
        if mode in ("editor", "both", "list"):
            self._pending_width = mode

    def _remember_drag(self) -> None:
        """The user dragged the wide side to a width of their own: keep it, as a share of
        the editor's width so it suits another window size, here and after a restart."""

        width, host_width = self._docked_width(), self.host.width()
        if not self._applied_wide or not width or host_width <= 0 or self._pending_width:
            return
        if abs(width - self._applied_wide) <= DRAG_SLACK:
            return
        self._wide_share = width / host_width
        if self.settings is not None:
            try:
                self.settings.setValue(WIDE_KEY, round(self._wide_share, 4))
            except RuntimeError:
                pass

    def _wide_width(self) -> int:
        """Half the editor's width (or the user's own), never narrower than the side
        already is unless the user chose so, and leaving the 3D view a usable width."""

        tools, host_width = self.tools, self.host.width()
        if self._wide_share:
            width = int(host_width * self._wide_share)
        else:
            width = max(int(host_width * WIDE_WIDTH_SHARE), tools.width())
        return max(1, min(width, host_width - scaled_px(VIEW_MIN_WIDTH, self.host)))

    def _fit_width(self) -> None:
        """With the list hidden the side widens so the texture is drawn larger; with the
        list back it has the width it had beside it; closing the editor returns the list
        to its compact width."""

        pending, self._pending_width = self._pending_width, ""
        tools, host = self.tools, self.host
        if not pending or pending != self._mode or host.width() <= 0:
            return
        if pending == "list":
            width, self._list_only_width = self._list_only_width, 0
            if width > 0 and not self.textures.isHidden() and not self.textures.isFloating():
                host.resizeDocks([self.textures], [width], Qt.Orientation.Horizontal)
            return
        if not self._docked_width():
            return
        if pending == "editor":
            if not self._narrow_width:
                # A texture opened with the list hidden: the list, when it shows, gets
                # the side as it was before it widened.
                self._narrow_width = tools.width()
            width = self._wide_width()
            host.resizeDocks([tools], [width], Qt.Orientation.Horizontal)
            self._applied_wide = width
        elif self._narrow_width:
            width, self._narrow_width = self._narrow_width, 0
            if not self.textures.isFloating():
                host.resizeDocks([tools], [width], Qt.Orientation.Horizontal)
        elif self._both_width:
            width, self._both_width = self._both_width, 0
            if not self.textures.isFloating():
                host.resizeDocks([tools], [width], Qt.Orientation.Horizontal)

    def _fit_list(self) -> None:
        """The first time the list shows (or after a layout saved under an older sizes
        version), it opens at a compact, proportional width."""

        textures, host = self.textures, self.host
        if textures.isHidden() or textures.isFloating() or host.width() <= 0:
            return
        if self._sizes_are_current() or self._texture_open:
            return
        least = textures.minimumSizeHint().width()
        share_cap = max(least, int(host.width() * LIST_MAX_WIDTH_SHARE))
        preferred = max(
            scaled_px(LIST_MIN_DEFAULT_WIDTH, textures),
            int(host.width() * LIST_WIDTH_SHARE),
        )
        width = max(least, min(preferred, scaled_px(LIST_MAX_DEFAULT_WIDTH, textures), share_cap))
        if abs(textures.width() - width) > 2:
            host.resizeDocks([textures], [width], Qt.Orientation.Horizontal)
        self._list_sized = True
        if self.settings is not None:
            try:
                self.settings.setValue(SIZES_KEY, SIZES_VERSION)
            except RuntimeError:
                pass

    def _fit_editor(self) -> None:
        """The first texture opened in a run widens the panels for the canvas, and the
        first time both panels show together the list gets its share of the height;
        after that the user's sizes stand."""

        tools, textures, host = self.tools, self.textures, self.host
        if tools is None or tools.isHidden() or tools.isFloating() or host.width() <= 0:
            return
        if not self._editor_sized:
            self._editor_sized = True
            width = max(scaled_px(560, tools), int(host.width() * EDITOR_WIDTH_SHARE))
            if tools.width() < width:
                host.resizeDocks([tools], [width], Qt.Orientation.Horizontal)
        if not self._split_sized and not textures.isHidden() and not textures.isFloating():
            self._split_sized = True
            total = textures.height() + tools.height()
            list_height = max(textures.minimumSizeHint().height(), int(total * LIST_HEIGHT_SHARE))
            host.resizeDocks([textures, tools], [list_height, max(1, total - list_height)],
                             Qt.Orientation.Vertical)


__all__ = ["SHOWN_KEY", "SIZES_KEY", "SIZES_VERSION", "TexturePanels"]
