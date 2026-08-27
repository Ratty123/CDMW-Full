"""Runtime theme coverage for surfaces that can override the application palette."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage, QPainter, QPalette, QTextDocument
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyleOptionToolButton,
    QToolButton,
)

from cdmw.ui.mesh_editor.action_bar import MeshEditorActionBar
from cdmw.ui.archive_browser.hkx_xml_highlighter import HkxXmlHighlighter
from cdmw.ui.archive_browser.pac_xml_editor_source_view import PacXmlCodeEditor
from cdmw.ui.new_item.ui_kit import BLOCK, EDIT, OK, WARN, step_style, tone_color
from cdmw.ui.new_item.workflow_header import WorkflowHeader
from cdmw.ui.theme_schemes import UI_THEME_SCHEMES
from cdmw.ui.themes import build_app_palette, build_app_stylesheet
from tools.placement_studio.corpus import Baseline
from tools.placement_studio.window import PlacementStudioWindow


_APP = QApplication.instance() or QApplication([])


def _tool_button_background(button: QToolButton, state: QStyle.StateFlag) -> str:
    image = QImage(button.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    option = QStyleOptionToolButton()
    option.initFrom(button)
    option.rect = button.rect()
    option.text = button.text()
    option.state = state
    painter = QPainter(image)
    button.style().drawComplexControl(
        QStyle.ComplexControl.CC_ToolButton,
        option,
        painter,
        button,
    )
    painter.end()
    return image.pixelColor(8, button.height() // 2).name()


def test_real_placement_studio_controls_inherit_every_application_theme(tmp_path: Path) -> None:
    previous_palette = QPalette(_APP.palette())
    previous_stylesheet = _APP.styleSheet()
    previous_theme_key = _APP.property("_cdmw_theme_key")
    window = PlacementStudioWindow(Baseline(tmp_path / "empty-placement-baseline", {}))
    window.resize(1490, 900)
    window.show()
    disabled_button = window._nudge_buttons[0]
    disabled_button.setEnabled(False)
    enabled_button = window._new_socket_button
    enabled_button.setEnabled(True)
    try:
        assert window.styleSheet() == "", "Placement Studio must not replace the app theme"
        for theme_key, theme in UI_THEME_SCHEMES.items():
            _APP.setProperty("_cdmw_theme_key", theme_key)
            _APP.setPalette(build_app_palette(theme_key))
            _APP.setStyleSheet(build_app_stylesheet(theme_key))
            _APP.processEvents()

            assert disabled_button.palette().color(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Button,
            ).name() == theme["button_disabled"]
            assert disabled_button.palette().color(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.ButtonText,
            ).name() == theme["button_disabled_text"]
            assert enabled_button.palette().color(
                QPalette.ColorGroup.Active,
                QPalette.ColorRole.Button,
            ).name() == theme["button"]
            assert enabled_button.palette().color(
                QPalette.ColorGroup.Active,
                QPalette.ColorRole.ButtonText,
            ).name() == theme["text"]
            assert window._behaviour_badge.objectName() == "ActiveBadge"
            assert window._constraint_badge.objectName() == "WarningBadge"
            assert window._behaviour_disabled.objectName() == "WarningBadge"
    finally:
        window.close()
        window.deleteLater()
        _APP.processEvents()
        _APP.setProperty("_cdmw_theme_key", previous_theme_key)
        _APP.setStyleSheet(previous_stylesheet)
        _APP.setPalette(previous_palette)


def test_mesh_editor_checked_actions_use_every_theme_accent() -> None:
    previous_palette = QPalette(_APP.palette())
    previous_stylesheet = _APP.styleSheet()
    action_bar = MeshEditorActionBar()
    action_bar.show()
    button = action_bar.button_for_key("mode_object")
    assert button is not None
    button.setChecked(True)
    try:
        for theme_key, theme in UI_THEME_SCHEMES.items():
            _APP.setPalette(build_app_palette(theme_key))
            _APP.setStyleSheet(build_app_stylesheet(theme_key))
            _APP.processEvents()
            checked = _tool_button_background(
                button,
                QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On,
            )
            checked_hover = _tool_button_background(
                button,
                QStyle.StateFlag.State_Enabled
                | QStyle.StateFlag.State_On
                | QStyle.StateFlag.State_MouseOver,
            )
            assert checked == theme["accent"]
            assert checked_hover == theme["accent_soft"]
    finally:
        action_bar.close()
        action_bar.deleteLater()
        _APP.processEvents()
        _APP.setStyleSheet(previous_stylesheet)
        _APP.setPalette(previous_palette)


def test_archive_swap_banner_uses_every_theme_warning_roles() -> None:
    previous_palette = QPalette(_APP.palette())
    previous_stylesheet = _APP.styleSheet()
    banner = QFrame()
    banner.setObjectName("ArchiveSwapBanner")
    layout = QHBoxLayout(banner)
    label = QLabel("Swap source armed", banner)
    label.setObjectName("ArchiveSwapBannerLabel")
    layout.addWidget(label)
    banner.resize(260, 48)
    banner.show()
    try:
        for theme_key, theme in UI_THEME_SCHEMES.items():
            _APP.setPalette(build_app_palette(theme_key))
            _APP.setStyleSheet(build_app_stylesheet(theme_key))
            _APP.processEvents()
            image = banner.grab().toImage()
            assert image.pixelColor(3, 3).name() == theme["warning_bg"]
            assert label.palette().color(QPalette.ColorRole.WindowText).name() == theme["warning_text"]
    finally:
        banner.close()
        banner.deleteLater()
        _APP.processEvents()
        _APP.setStyleSheet(previous_stylesheet)
        _APP.setPalette(previous_palette)


def test_placement_studio_has_no_hardcoded_widget_chrome_colours() -> None:
    root = Path(__file__).resolve().parents[1] / "tools" / "placement_studio"
    declaration = re.compile(
        r"(?:color|background|border(?:-color)?)\s*:[^;\n]*#[0-9a-fA-F]{6,8}"
    )
    offenders: list[str] = []
    for path in sorted(root.glob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if declaration.search(line):
                offenders.append(f"{path.name}:{line_number}")
    assert not offenders, "Placement Studio forces theme-independent widget colours: " + ", ".join(offenders)


def test_ui_stylesheets_do_not_force_unscoped_literal_theme_colours() -> None:
    root = Path(__file__).resolve().parents[1]
    allowed_dynamic_markers = (
        "_theme_value(",
        "_splash_theme_value(",
        "highlight.name()",
    )
    offenders: list[str] = []
    for source_root in (root / "cdmw" / "ui", root / "tools"):
        for path in sorted(source_root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"setStyleSheet", "setDefaultStyleSheet"}
                ):
                    continue
                call_source = ast.get_source_segment(source, node) or ""
                if re.search(r"#[0-9a-fA-F]{6,8}", call_source) and not any(
                    marker in call_source for marker in allowed_dynamic_markers
                ):
                    offenders.append(f"{path.relative_to(root)}:{node.lineno}")
    assert not offenders, "Literal widget-theme overrides bypass the active palette: " + ", ".join(offenders)


def test_rich_text_does_not_force_theme_independent_foregrounds_or_opaque_backgrounds() -> None:
    root = Path(__file__).resolve().parents[1]
    allowed_content_colour_files = {
        Path("cdmw/ui/themes.py"),  # central theme-owned colour-only indicator chips
        Path("cdmw/ui/shell/help_dialogs.py"),  # translucent semantic callouts; text inherits
        Path("cdmw/ui/archive_browser/static_replacement_source_part_controls_state.py"),
        # An editable colour swatch with an explicitly paired contrast foreground.
    }
    declaration = re.compile(
        r"(?:color|background(?:-color)?)\s*:\s*#[0-9a-fA-F]{6,8}"
    )
    offenders: list[str] = []
    for source_root in (root / "cdmw" / "ui", root / "tools"):
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(root)
            if relative in allowed_content_colour_files:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if declaration.search(line):
                    offenders.append(f"{relative}:{line_number}")
    assert not offenders, "Theme-independent rich-text colours bypass the active palette: " + ", ".join(offenders)


def test_new_item_guided_workspace_uses_only_each_theme_palette() -> None:
    previous_palette = QPalette(_APP.palette())
    previous_theme_key = _APP.property("_cdmw_theme_key")
    header = WorkflowHeader()
    header.show()
    try:
        expected_roles = {
            OK: "text_strong",
            WARN: "warning_text",
            BLOCK: "error",
            EDIT: "accent",
        }
        for theme_key, theme in UI_THEME_SCHEMES.items():
            _APP.setProperty("_cdmw_theme_key", theme_key)
            palette = build_app_palette(theme_key)
            _APP.setPalette(palette)
            _APP.processEvents()
            header._refresh_palette()
            stylesheet = step_style(palette)
            used_colors = {value.lower() for value in re.findall(r"#[0-9a-fA-F]{6,8}", stylesheet)}
            theme_colors = {value.lower() for role, value in theme.items() if role != "label"}
            assert used_colors <= theme_colors, f"{theme_key}: {sorted(used_colors - theme_colors)}"
            for tone, role in expected_roles.items():
                assert tone_color(tone) == theme[role]
            assert header._active_color.name() == theme["accent"]
            assert header._active_text_color.name() == theme["accent_text"]
            assert header._warning_background.name() == theme["warning_bg"]
            assert header._warning_text.name() == theme["warning_text"]
    finally:
        header.close()
        header.deleteLater()
        _APP.processEvents()
        _APP.setProperty("_cdmw_theme_key", previous_theme_key)
        _APP.setPalette(previous_palette)


def test_archive_xml_editors_use_every_theme_text_roles() -> None:
    previous_palette = QPalette(_APP.palette())
    previous_theme_key = _APP.property("_cdmw_theme_key")
    try:
        for theme_key, theme in UI_THEME_SCHEMES.items():
            _APP.setProperty("_cdmw_theme_key", theme_key)
            _APP.setPalette(build_app_palette(theme_key))

            document = QTextDocument('<hkobject name="value"><!-- note --></hkobject>')
            highlighter = HkxXmlHighlighter(document)
            highlighter.rehighlight()
            assert highlighter.tag_format.foreground().color().name() == theme["accent"]
            assert highlighter.attribute_format.foreground().color().name() == theme["warning_text"]
            assert highlighter.string_format.foreground().color().name() == theme["text_strong"]
            assert highlighter.comment_format.foreground().color().name() == theme["text_muted"]

            editor = PacXmlCodeEditor('<root value="1"/>')
            assert editor.palette().color(QPalette.ColorRole.Base).name() == theme["field_alt"]
            assert editor.palette().color(QPalette.ColorRole.Text).name() == theme["text"]
            assert editor._theme_colors["tag"].name() == theme["accent"]
            assert editor._theme_colors["attribute"].name() == theme["warning_text"]
            editor.deleteLater()
        _APP.processEvents()
    finally:
        _APP.setProperty("_cdmw_theme_key", previous_theme_key)
        _APP.setPalette(previous_palette)
