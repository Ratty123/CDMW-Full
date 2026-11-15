"""The Scene panel beside any 3D preview, not only Browse Archives' (P5).

A preview host applies a package; the binding lists that package's files and
parts in a Scene panel beside it and sends the panel's ticks back to the host
as its hidden parts. The panel shows only while the host is shown and the model
has more than one part: a single part has nothing to tick.

Browse Archives keeps its own wiring (its Parts dropdown and prefab loading
share the panel's state); this binding is for the other previews, which load
no prefab components and cannot open the Mesh Editor, so the panel there
offers the visibility actions only.
"""

from __future__ import annotations

from pathlib import Path

import shiboken6

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QBoxLayout, QSplitter, QWidget

from cdmw.ui.archive_browser.item_set_components import ScenePanel, remember_scene_panel_width

#: Fewer parts than this and the panel stays hidden.
SCENE_PANEL_MIN_PARTS = 2


class ScenePanelBinding(QObject):
    def __init__(self, host: QWidget, panel: ScenePanel) -> None:
        super().__init__(panel)
        self.host = host
        self.panel = panel
        self.package_path: Path | None = None
        applied = getattr(getattr(host, "controller", None), "package_applied", None)
        if applied is not None:
            applied.connect(self._package_applied)
        panel.visibilityChanged.connect(self._visibility_changed)
        host.installEventFilter(self)

    def _parts_worth_showing(self) -> bool:
        return self.panel.active and len(self.panel._parts) >= SCENE_PANEL_MIN_PARTS

    def _follow_host(self) -> None:
        self.panel.setVisible(bool(self.host.isVisible() and self._parts_worth_showing()))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self.host and event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self._follow_host()
        return False

    def _package_applied(self, package_path: object, _generation: object = 0) -> None:
        self.show_package(Path(str(package_path)))

    def show_package(self, package_path: Path) -> None:
        """List the files and parts of the package the host now shows."""

        self.package_path = Path(package_path)
        from cdmw.ui.preview.part_manifest import read_part_manifest

        manifest = read_part_manifest(self.package_path) or {}
        batches = manifest.get("batches") if isinstance(manifest, dict) else None
        self.panel.set_parts(list(batches) if isinstance(batches, list) else [])
        hidden = self.panel.hidden_indices
        if hidden:  # ticks kept for the same files across a reload
            self._send_hidden(hidden)
        self._follow_host()

    def _visibility_changed(self, _hidden: object = ()) -> None:
        self._send_hidden(self.panel.hidden_indices)

    def _send_hidden(self, hidden: object) -> None:
        send = getattr(self.host, "set_hidden_source_submeshes", None)
        if callable(send):
            send(sorted(int(index) for index in hidden))


def attach_scene_panel(host: QWidget, anchor: QWidget | None = None) -> ScenePanelBinding | None:
    """Put a Scene panel to the right of ``anchor`` (the host, or the stack that holds it).

    ``anchor`` must already sit in a box layout or a splitter; it is moved into a
    row with the panel in its place. Elsewhere the preview simply has no panel.
    """

    anchor = anchor if anchor is not None else host
    parent = anchor.parentWidget()
    owner = parent.layout() if parent is not None and not isinstance(parent, QSplitter) else None
    if not isinstance(parent, QSplitter) and (not isinstance(owner, QBoxLayout) or owner.indexOf(anchor) < 0):
        return None  # a preview laid out otherwise simply has no panel
    # A splitter, so the panel's width can be dragged (and is remembered).
    row = QSplitter(Qt.Orientation.Horizontal, parent)
    row.setObjectName("ScenePanelRow")
    if isinstance(parent, QSplitter):
        index = parent.indexOf(anchor)
        parent.replaceWidget(index, row)
    else:
        stretch = owner.stretch(owner.indexOf(anchor))
        replaced = owner.replaceWidget(anchor, row)
        if replaced is not None:
            shiboken6.delete(replaced)  # the layout gives the old item back to be deleted
        owner.setStretchFactor(row, stretch)
    row.addWidget(anchor)
    panel = ScenePanel(row, opens_editor=False)
    row.addWidget(panel)
    remember_scene_panel_width(row, panel)
    return ScenePanelBinding(host, panel)


__all__ = ["SCENE_PANEL_MIN_PARTS", "ScenePanelBinding", "attach_scene_panel"]
