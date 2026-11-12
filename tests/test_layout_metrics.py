"""P11 step 4: spacing from one place for the Qt stylesheet and the helper's surfaces."""
from __future__ import annotations

from cdmw.ui.layout_metrics import font_pixels, layout_metrics, stylesheet_metrics

#: What the stylesheet used at Compact, 10 pt and 100 % before step 4.
_COMPACT_BEFORE = {
    "menu_pad_y": 3, "menu_pad_x": 8, "menu_item_pad_y": 4, "menu_item_pad_x": 9, "group_margin_top": 13,
    "group_pad_top": 8, "group_title_pad_y": 0, "group_title_pad_x": 6, "section_pad_y": 5, "section_pad_x": 8,
    "field_pad_y": 4, "field_pad_x": 7, "list_pad_y": 2, "list_pad_x": 5, "header_pad_y": 4, "header_pad_x": 6,
    "button_pad_y": 4, "button_pad_x": 8, "button_min_h": 16, "progress_min_h": 18, "tab_pad_top": 5,
    "tab_pad_bottom": 6, "tab_pad_x": 10, "tab_min_h": 18,
}


def test_compact_reproduces_the_stylesheet_it_replaced() -> None:
    assert stylesheet_metrics(layout_metrics("compact", 10, 1.0)) == _COMPACT_BEFORE


def test_comfortable_is_next_s_detailed_rule_and_text_stays_the_same() -> None:
    compact = layout_metrics("compact", 10, 1.0)
    comfortable = layout_metrics("comfortable", 10, 1.0)
    assert comfortable.font_pixels == compact.font_pixels
    assert comfortable.item_spacing == (9, 6) and comfortable.window_pad == (10, 9)  # 1.5 times
    assert comfortable.scrollbar == round(11 * 1.25) and comfortable.rounding == compact.rounding
    assert layout_metrics("unknown", 10).density == "compact"


def test_controls_follow_the_text_and_the_screen_is_bounded() -> None:
    small, large = layout_metrics("compact", 7), layout_metrics("compact", 14)
    assert small.control_height == font_pixels(7) + 2 * small.frame_pad[1]
    assert large.control_height > small.control_height
    assert layout_metrics("compact", 10, 0.1).window_pad == layout_metrics("compact", 10, 0.72).window_pad
    assert stylesheet_metrics(large)["button_min_h"] > stylesheet_metrics(small)["button_min_h"]


def test_the_stylesheet_takes_its_heights_from_the_text_size() -> None:
    from cdmw.ui.themes import build_app_stylesheet

    small = build_app_stylesheet("graphite", base_font_size=8)
    large = build_app_stylesheet("graphite", base_font_size=14)
    assert small != large
    assert f"min-height: {stylesheet_metrics(layout_metrics('compact', 14))['button_min_h']}px" in large


def test_the_helper_surfaces_get_the_same_metrics(tmp_path) -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from cdmw.ui.new_item.rust_ui_document import theme_snapshot
    from tests.test_mesh_rust_editor_selection import _dispose, _tab

    application = QApplication.instance() or QApplication([])
    application.setProperty("_cdmw_ui_density", "comfortable")
    tab = _tab(tmp_path)
    try:
        editor = tab._rust_theme_payload()["layout_metrics"]
        assert editor["density"] == editor["density"].lower() and editor["control_height"] > editor["font_pixels"]
        widget = QWidget()
        page = theme_snapshot(widget)["layout_metrics"]
        assert page["density"] == "comfortable" and page["item_spacing"] == [9, 6]
        widget.deleteLater()
    finally:
        application.setProperty("_cdmw_ui_density", None)
        _dispose(tab)
