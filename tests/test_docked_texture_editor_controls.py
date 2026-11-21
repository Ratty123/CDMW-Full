"""The Mesh Editor's docked Texture Editor has every control the AI texture tools work.

The dock shows only the tools, their settings and the canvas, but the texture tools
(``textures_select``, ``textures_derive``, ``textures_layer``, ``textures_export`` ...)
press the editor's other controls too, for the docked editor as for the Textures tool.
A docked editor built without them answered those calls with an AttributeError.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.texture_editor_tab import TextureEditorTab
from tests.test_mesh_editor_texture_panel_sizes import _open_real_texture, _real_page, _settle

CONTROL = re.compile(r"^[a-z][a-z0-9_]*_(button|combo|checkbox|slider|spin|edit|list)$")
ROOT = Path(__file__).resolve().parents[1]


def _control_names_the_texture_tools_use() -> set[str]:
    names: set[str] = set()
    for source in sorted((ROOT / "cdmw" / "mcp").glob("texture_*.py")):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and CONTROL.match(node.attr):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and CONTROL.match(node.value):
                names.add(node.value)
    return names


def test_the_docked_editor_has_the_controls_the_texture_tools_work(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    full = TextureEditorTab(settings=QSettings(str(tmp_path / "full.ini"), QSettings.Format.IniFormat),
                            base_dir=tmp_path, get_png_root=lambda: "")
    page = _real_page(1280, 720, tmp_path)
    try:
        _open_real_texture(page, tmp_path, side=64)
        docked = page.texture_tools_dock.editor
        assert isinstance(docked, TextureEditorTab)
        wanted = {name for name in _control_names_the_texture_tools_use() if hasattr(full, name)}
        assert len(wanted) > 60, "the scan no longer finds the tools' controls"
        missing = sorted(name for name in wanted if getattr(docked, name, None) is None)
        assert missing == [], f"the docked Texture Editor lacks controls the AI tools work: {missing}"
    finally:
        page.textures_dock.shutdown()
        page.deleteLater()
        full.deleteLater()
        _settle(2)
        app.processEvents()
