"""When the Mesh Editor's Textures panel and Texture Editor panel are shown.

Fredric, 2026-11-17: the panels are off until asked for ("it shouldn't be open per
default, but it should be a clear option to click"), and they go when the Mesh Editor
closes or loads another mesh.

One object decides, so no saved dock layout, tab switch or reload can show or hide a
panel on its own:

* the Textures panel shows when the user turned it on (the Textures button, remembered
  in the settings) and a mesh's textures are listed;
* the Texture Editor panel shows under the same rule once a texture was opened in it,
  and goes again when it is closed or the mesh is;
* hiding never drops an edit: the edits live with the document, not with the panels.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDockWidget, QWidget

#: Whether the user wants the Textures panel shown (off until they ask).
SHOWN_KEY = "mesh_editor/textures_panel_shown"

def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class TexturePanels(QObject):
    """Shows and hides the two texture panels of one Mesh Editor page."""

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
        session_shown = getattr(textures, "session_shown", None)
        if session_shown is not None:
            session_shown.connect(lambda _shown: self.apply())
        closed = getattr(textures, "close_requested", None)
        if closed is not None:
            closed.connect(lambda: self.set_wanted(False))
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

    def _on_texture_opened(self) -> None:
        self._texture_open = True
        # Opening a texture (a double-click in the list, or a command) asks for the panels.
        self.set_wanted(True)

    def _on_editor_emptied(self) -> None:
        self._texture_open = False
        self.apply()


__all__ = ["SHOWN_KEY", "TexturePanels"]
