"""P11 step 2: one font range on every surface, with no literal floors of its own."""
from __future__ import annotations

import ast
from pathlib import Path

from cdmw.constants import UI_FONT_SIZE_MAX, UI_FONT_SIZE_MIN
from cdmw.ui.layout_metrics import (
    MIN_FONT_PIXELS, clamp_font_points, font_pixels, small_font_points, title_font_points,
)

ROOT = Path(__file__).resolve().parents[1]
_FONT_SETTERS = {"setPointSize", "setPointSizeF", "setPixelSize"}


def test_the_range_is_six_to_sixteen_points_and_small_text_stays_inside_it() -> None:
    assert (UI_FONT_SIZE_MIN, UI_FONT_SIZE_MAX) == (6, 16)
    assert clamp_font_points(3) == 6 and clamp_font_points(40) == 16 and clamp_font_points("x", 9) == 9
    assert small_font_points(10) == 9 and small_font_points(6) == 6
    assert title_font_points(10, 3) == 13 and title_font_points(2, 1) == 6
    assert font_pixels(9) == 12 and MIN_FONT_PIXELS == font_pixels(UI_FONT_SIZE_MIN)


def _literal_floors(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr in _FONT_SETTERS):
            continue
        for inner in ast.walk(call):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                    and inner.func.id in {"max", "min"}
                    and any(isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float))
                            and arg.value not in (0, 1) for arg in inner.args)):
                found.append(f"{path.relative_to(ROOT)}:{call.lineno}")
    return found


def test_no_ui_code_keeps_a_font_floor_of_its_own() -> None:
    offenders = [hit for path in sorted((ROOT / "cdmw" / "ui").rglob("*.py")) for hit in _literal_floors(path)]
    assert offenders == [], "use cdmw.ui.layout_metrics instead of a literal font floor: " + ", ".join(offenders)


def test_the_helper_s_pages_take_their_range_from_cdmw() -> None:
    src = ROOT / "tools" / "rust_mesh_lab" / "apps" / "cdmw_mesh_lab" / "src"
    editor = (src / "cdmw_ui.rs").read_text(encoding="utf-8")
    page = (src / "new_item_ui" / "view.rs").read_text(encoding="utf-8")
    mods = (src / "new_item_ui" / "mod_management.rs").read_text(encoding="utf-8")
    assert ".clamp(8.0, 18.0)" not in editor and ".max(9.0)" not in editor and "font_min_points" in editor
    assert ".clamp(8.0, 64.0)" not in page and "min_font_pixels" in page
    assert ".max(11.0)" not in mods


def test_the_mesh_editor_theme_sends_the_range_and_the_resolved_sizes(tmp_path) -> None:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from tests.test_mesh_rust_editor_selection import _dispose, _tab

    QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    try:
        settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("appearance/data_font_size", 40)  # out of range: clamped as everywhere else
        tab.settings = settings
        payload = tab._rust_theme_payload()
        assert payload["font_min_points"] == UI_FONT_SIZE_MIN and payload["font_max_points"] == UI_FONT_SIZE_MAX
        assert UI_FONT_SIZE_MIN <= payload["data_font_point_size"] <= UI_FONT_SIZE_MAX
        assert payload["density"] in {"compact", "normal", "comfortable"}
    finally:
        _dispose(tab)
