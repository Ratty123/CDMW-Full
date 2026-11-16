"""The bridge's reads for B's pass: the dock's sharing and kept lines, floating it."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow

from cdmw.automation import bridge as bridge_module
from cdmw.ui.mesh_editor.texture_tools_dock import MeshEditorTextureTools

_APP = QApplication.instance() or QApplication([])


def test_the_dock_float_command_and_its_lines(monkeypatch, tmp_path):
    host = QMainWindow()
    tools = MeshEditorTextureTools(host)
    host.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, tools)
    host.show()
    keeper = SimpleNamespace(unkept_count=lambda: 2)
    tab = SimpleNamespace(_live_texture_keeping=keeper, _live_texture_draft_root=lambda: tmp_path)
    bridge = bridge_module.AutomationBridge.__new__(bridge_module.AutomationBridge)
    monkeypatch.setattr(bridge, "_texture_editor_window", lambda: tools, raising=False)
    monkeypatch.setattr(bridge, "_shown_mesh_tab", lambda: tab, raising=False)
    placed = []
    monkeypatch.setattr(bridge_module, "place_on_automation_screen", placed.append)
    try:
        assert bridge._texture_dock({"floating": True}) == {"exists": True, "floating": True, "visible": True}
        assert placed == [tools]
        assert bridge._texture_dock({"floating": False})["floating"] is False
        tools.set_kept_text("Texture edits are kept in this draft.")
        assert tools.kept_label.text() == "Texture edits are kept in this draft."
        assert bridge._unkept_texture_edits(tab) == 2
    finally:
        host.deleteLater()
