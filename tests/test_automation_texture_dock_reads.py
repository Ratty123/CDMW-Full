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


class _Slider:
    def __init__(self, maximum: int) -> None:
        self._maximum, self._value = maximum, 0

    def maximum(self) -> int:
        return self._maximum

    def setValue(self, value: int) -> None:  # noqa: N802 - Qt API
        self._value = int(value)

    def value(self) -> int:
        return self._value


def test_the_marker_is_one_solid_paint_stroke_across_the_centre():
    strokes, tools, synced = [], [], []
    color = SimpleNamespace(text="", setText=lambda value: setattr(color, "text", value))
    editor = SimpleNamespace(
        document=SimpleNamespace(width=1024, height=512),
        _set_active_tool=tools.append, paint_color_edit=color,
        brush_size_slider=_Slider(500), hardness_slider=_Slider(100), opacity_slider=_Slider(100),
        flow_slider=_Slider(100), _handle_tool_settings_changed=lambda: synced.append(True),
        canvas=SimpleNamespace(stroke_committed=SimpleNamespace(emit=strokes.append)))
    assert bridge_module.AutomationBridge._texture_marker(editor, {}) is True
    assert tools == ["paint"] and color.text == "#FF00FF" and synced == [True]
    assert editor.brush_size_slider.value() == 64
    assert editor.hardness_slider.value() == editor.opacity_slider.value() == editor.flow_slider.value() == 100
    (stroke,) = strokes
    assert stroke["tool"] == "paint"
    assert {y for _x, y in stroke["points"]} == {256}
    assert stroke["points"][0][0] == 512 - 64 and stroke["points"][-1][0] == 512 + 64
    editor.document = SimpleNamespace(width=0, height=0)
    assert bridge_module.AutomationBridge._texture_marker(editor, {}) is False


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


def test_the_window_read_reports_the_docks_texts_as_plain_strings(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QWidget

    from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget

    class _Editor(QWidget):
        history_index = 0

        def open_source_path(self, path, *, binding=None) -> None:
            pass

    tools = MeshEditorTextureTools(editor_factory=_Editor)
    game_path = "character/texture/belt.dds"
    tools.open_target(LiveTextureTarget(
        session_id="doc", source_path=str(tmp_path / "belt.dds"), source_sha256="ab" * 32, channel="base_color",
        display_name="belt.dds", game_path=game_path, users=("A", "B"), in_renderer=False))
    tools.set_sharing_text(game_path, "Checking whether other game files use this texture...")
    tools.set_kept_text("Texture edits are not kept yet: Finish keeps them in the draft.")
    tab = SimpleNamespace(standalone_rust_ready=False)
    bridge = bridge_module.AutomationBridge.__new__(bridge_module.AutomationBridge)
    monkeypatch.setattr(bridge, "_texture_editor_window", lambda: tools, raising=False)
    monkeypatch.setattr(bridge, "_shown_mesh_tab", lambda: tab, raising=False)
    try:
        tools.hide()  # hidden (say, behind another tab): the texts are reported all the same
        read = bridge._texture_window({})
        assert read["title"] == "belt.dds"
        assert read["notice"].startswith("This texture is shared. Edits change it on: A, B")
        assert "not shown on the model" in read["notice"]
        assert read["sharing_text"] == "Checking whether other game files use this texture..."
        assert read["kept_text"] == "Texture edits are not kept yet: Finish keeps them in the draft."
        tools.set_kept_text("")
        tools.set_sharing_text(game_path, "")
        read = bridge._texture_window({})
        assert read["kept_text"] == "" and read["sharing_text"] == ""
        assert all(isinstance(read[key], str) for key in ("notice", "sharing_text", "kept_text"))
    finally:
        tools.deleteLater()
