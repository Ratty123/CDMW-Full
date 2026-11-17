"""When the Mesh Editor's Textures panel and Texture Editor panel are shown, and how large.

Fredric, 2026-11-17: the panels are off until asked for ("it shouldn't be open per
default, but it should be a clear option to click"), they go when the Mesh Editor closes
or loads another mesh, and they open at a usable size instead of a crushed strip.

One object decides, so no saved dock layout, tab switch or reload can show or hide a
panel on its own:

* the Textures panel shows when the user turned it on (the Textures button, remembered
  in the settings) and a mesh's textures are listed;
* the Texture Editor panel shows under the same rule once a texture was opened in it,
  and goes again when it is closed or the mesh is;
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
SIZES_VERSION = 2

#: The Textures panel's share of the editor's width when it first shows.
LIST_WIDTH_SHARE = 0.26
#: The two panels' share of the editor's width once a texture is open beside the model.
EDITOR_WIDTH_SHARE = 0.45
#: The list's share of the panels' height while the Texture Editor is under it.
LIST_HEIGHT_SHARE = 0.3


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
        self._texture_open = False
        self._list_sized = False
        self._editor_sized = False
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
            tools.close_requested.connect(self._on_editor_emptied)
        self.apply()

    # ----- the user's choice ----------------------------------------------------
    def use_settings(self, settings: object) -> None:
        """Read the remembered choice; later changes are saved there."""

        self.settings = settings
        value = settings.value(SHOWN_KEY, None) if settings is not None else None
        self._wanted = _as_bool(value, False)
        self.wanted_changed.emit(self._wanted)
        self.apply()

    @property
    def wanted(self) -> bool:
        return self._wanted

    def set_wanted(self, wanted: bool) -> None:
        wanted = bool(wanted)
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

    def apply(self) -> None:
        """Show or hide both panels as the rule above says."""

        show_list = self._wanted and self.session_open
        show_editor = show_list and self._texture_open and self.tools is not None
        if self.tools is not None and self.tools.isHidden() == show_editor:
            self.tools.setVisible(show_editor)
        if self.textures.isHidden() == show_list:
            self.textures.setVisible(show_list)
        if show_list:
            # After the layout has placed the panels: sizes need the host's real size.
            QTimer.singleShot(0, self._fit_sizes)

    def _on_texture_opened(self) -> None:
        self._texture_open = True
        # Opening a texture (a double-click in the list, or a command) asks for the panels.
        self.set_wanted(True)

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
        except RuntimeError:
            pass  # the page went away before the timer ran

    def _fit_list(self) -> None:
        """The first time the list shows (or after a layout saved before the panels had
        minimum sizes), it takes a sensible share of the editor's width."""

        textures, host = self.textures, self.host
        if textures.isHidden() or textures.isFloating() or host.width() <= 0:
            return
        if self._sizes_are_current() or self._texture_open:
            return
        least = textures.minimumSizeHint().width()
        width = min(max(least, int(host.width() * LIST_WIDTH_SHARE)), max(least, scaled_px(520, textures)))
        host.resizeDocks([textures], [width], Qt.Orientation.Horizontal)
        self._list_sized = True
        if self.settings is not None:
            try:
                self.settings.setValue(SIZES_KEY, SIZES_VERSION)
            except RuntimeError:
                pass

    def _fit_editor(self) -> None:
        """The first texture opened in a run widens the panels for the canvas and gives
        the list its share of the height; after that the user's sizes stand."""

        tools, textures, host = self.tools, self.textures, self.host
        if tools is None or tools.isHidden() or tools.isFloating() or self._editor_sized or host.width() <= 0:
            return
        self._editor_sized = True
        width = max(scaled_px(560, tools), int(host.width() * EDITOR_WIDTH_SHARE))
        if tools.width() < width:
            host.resizeDocks([tools], [width], Qt.Orientation.Horizontal)
        if not textures.isHidden() and not textures.isFloating():
            total = textures.height() + tools.height()
            list_height = max(textures.minimumSizeHint().height(), int(total * LIST_HEIGHT_SHARE))
            host.resizeDocks([textures, tools], [list_height, max(1, total - list_height)],
                             Qt.Orientation.Vertical)


__all__ = ["SHOWN_KEY", "SIZES_KEY", "SIZES_VERSION", "TexturePanels"]
