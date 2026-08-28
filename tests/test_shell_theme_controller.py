from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QStyleOptionToolButton,
    QTableWidget,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.settings_tab import SettingsTab
from cdmw.ui.app_icon import resolve_app_icon_path
from cdmw.services.settings_service import create_settings
from cdmw.ui.shell.compact.config import COMPACT_SHELL_VARIANT, SHELL_VARIANT_SETTING
from cdmw.ui.shell.theme_controller import (
    ThemeChangeBusyOverlay,
    ThemeControllerMixin,
    apply_app_fonts,
    apply_app_theme,
    apply_window_ui_fonts,
)
from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_palette, build_app_stylesheet


ROOT = Path(__file__).resolve().parents[1]
ADDED_THEMES = {
    "desert_dawn": "Desert Dawn",
    "high_contrast": "High Contrast",
    "oled_black": "OLED Black",
}


def _relative_luminance(color: str) -> float:
    value = QColor(color)
    channels = (value.redF(), value.greenF(), value.blueF())
    linear = tuple(channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels)
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class _Settings:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def value(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


def _exercise_existing_styled_child_font_update() -> None:
    app = QApplication.instance() or QApplication([])
    previous_font = QFont(app.font())
    previous_style_sheet = app.styleSheet()
    parent = QWidget()
    label = QLabel("Label")
    button = QPushButton("Button")
    list_widget = QListWidget()
    layout = QVBoxLayout(parent)
    layout.addWidget(label)
    layout.addWidget(button)
    layout.addWidget(list_widget)
    try:
        app.setStyleSheet(build_app_stylesheet("graphite"))
        parent.show()
        app.processEvents()
        settings = _Settings(
            {
                "appearance/ui_font_family": previous_font.family(),
                "appearance/ui_font_size": 15,
                "appearance/data_font_size": 11,
                "appearance/ui_density": "comfortable",
            }
        )
        apply_app_fonts(app, settings, screen_width=4096, screen_height=2160)
        app.processEvents()
        assert label.font().pointSize() == 15
        assert button.font().pointSize() == 15
        assert list_widget.font().pointSize() == 11
    finally:
        parent.deleteLater()
        app.setFont(previous_font)
        for class_name in (
            "QWidget", "QListView", "QListWidget", "QTreeView",
            "QTreeWidget", "QTableView", "QTableWidget", "QHeaderView",
        ):
            app.setFont(previous_font, class_name)
        app.setStyleSheet(previous_style_sheet)


def _exercise_theme_replacement() -> None:
    app = QApplication.instance() or QApplication([])
    previous_font = QFont(app.font())
    previous_palette = QPalette(app.palette())
    previous_style_sheet = app.styleSheet()
    settings = _Settings({})
    initial_stylesheet = build_app_stylesheet("graphite")
    app.setStyleSheet(initial_stylesheet)
    calls: list[str] = []
    original_set_stylesheet = QApplication.setStyleSheet

    def record_set_stylesheet(target: QApplication, stylesheet: str) -> None:
        calls.append(stylesheet)
        original_set_stylesheet(target, stylesheet)

    try:
        with patch.object(QApplication, "setStyleSheet", record_set_stylesheet):
            apply_app_theme(app, settings, "crimson_desert", screen_width=1360, screen_height=840)
            first_apply_calls = tuple(calls)
            applied_stylesheet = app.styleSheet()
            assert app.property("_cdmw_theme_key") == "crimson_desert"
            calls.clear()
            apply_app_theme(app, settings, "crimson_desert", screen_width=1360, screen_height=840)
        assert first_apply_calls[0] == ""
        assert first_apply_calls[1] == applied_stylesheet
        assert calls == []
    finally:
        app.setStyleSheet(previous_style_sheet)
        app.setPalette(previous_palette)
        app.setFont(previous_font)


def _exercise_compact_font_sizes() -> None:
    app = QApplication.instance() or QApplication([])
    previous_font = QFont(app.font())
    previous_style_sheet = app.styleSheet()
    parent = QWidget()
    label = QLabel("Label")
    list_widget = QListWidget()
    layout = QVBoxLayout(parent)
    layout.addWidget(label)
    layout.addWidget(list_widget)
    settings = _Settings(
        {
            "appearance/ui_font_family": previous_font.family(),
            "appearance/ui_font_size": 10,
            "appearance/data_font_size": 10,
            "appearance/ui_density": "compact",
        }
    )
    try:
        parent.show()
        apply_app_fonts(app, settings, screen_width=1366, screen_height=1080)
        app.processEvents()
        configured_ten = (label.font().pointSize(), list_widget.font().pointSize())
        settings._values["appearance/ui_font_size"] = 8
        settings._values["appearance/data_font_size"] = 8
        apply_app_fonts(app, settings, screen_width=1366, screen_height=1080)
        app.processEvents()
        configured_eight = (label.font().pointSize(), list_widget.font().pointSize())
        assert configured_ten == (10, 10)
        assert configured_eight == (8, 8)
    finally:
        parent.deleteLater()
        app.setFont(previous_font)
        for class_name in (
            "QWidget", "QListView", "QListWidget", "QTreeView",
            "QTreeWidget", "QTableView", "QTableWidget", "QHeaderView",
        ):
            app.setFont(previous_font, class_name)
        app.setStyleSheet(previous_style_sheet)


class ShellThemeControllerTests(unittest.TestCase):
    def _run_isolated_probe(self, function_name: str) -> None:
        script = "\n".join(
            (
                "import os, sys",
                "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
                f"from tests.test_shell_theme_controller import {function_name}",
                f"{function_name}()",
                "sys.stdout.flush(); sys.stderr.flush(); os._exit(0)",
            )
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        self.assertEqual(
            0,
            result.returncode,
            f"Theme probe {function_name} failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

    def test_compact_styles_are_scoped_and_keep_structural_wrappers_flat(self) -> None:
        stylesheet = build_app_stylesheet("crimson_desert")

        self.assertIn('QWidget[compactPresentation="true"] QGroupBox {', stylesheet)
        self.assertIn('QWidget[compactPresentation="true"] QFrame#FlatSectionBody,', stylesheet)
        self.assertIn('QWidget[compactPresentation="true"] QGroupBox[compactStructural="true"] {', stylesheet)
        self.assertIn('QWidget[compactPresentation="true"] QWidget[compactFlatSurface="true"]', stylesheet)
        self.assertIn('QWidget[compactPresentation="true"] QToolButton#SectionToggle {', stylesheet)
        self.assertIn('QWidget[compactPresentation="true"] QToolButton#EditorToolButton {', stylesheet)
        self.assertIn('QWidget[compactPresentation="true"] QPushButton {', stylesheet)
        self.assertIn('QWidget[compactPresentation="true"] QListWidget#SettingsSectionNav {', stylesheet)
        compact_group_style = stylesheet.split(
            'QWidget[compactPresentation="true"] QGroupBox {', 1
        )[1].split("}", 1)[0]
        self.assertIn("border: none;", compact_group_style)
        self.assertNotIn("border-top:", compact_group_style)
        self.assertNotIn("font-size:", stylesheet)

    def test_settings_navigation_inherits_the_active_compact_theme(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_palette = QPalette(app.palette())
        previous_style_sheet = app.styleSheet()
        with tempfile.TemporaryDirectory(prefix="cdmw-settings-theme-") as temp_dir:
            settings = create_settings(settings_file_path=Path(temp_dir) / "settings.cfg")
            settings.setValue(SHELL_VARIANT_SETTING, COMPACT_SHELL_VARIANT)
            settings.setValue("appearance/theme", "graphite")
            app.setPalette(build_app_palette("crimson_desert"))
            app.setStyleSheet(build_app_stylesheet("crimson_desert"))
            tab = SettingsTab(settings=settings, theme_key="graphite")
            try:
                tab.resize(900, 700)
                tab.show()
                app.processEvents()

                self.assertTrue(bool(tab.property("compactPresentation")))
                self.assertEqual("graphite", tab.current_theme_key())
                self.assertEqual("", tab.section_nav_list.styleSheet())
                self.assertEqual(
                    UI_THEME_SCHEMES["crimson_desert"]["surface_alt"],
                    tab.section_nav_list.palette().color(QPalette.Base).name(),
                )
            finally:
                tab.deleteLater()
                app.processEvents()
                app.setStyleSheet(previous_style_sheet)
                app.setPalette(previous_palette)

    def test_appearance_steps_yield_without_a_per_step_idle_delay(self) -> None:
        app = QApplication.instance() or QApplication([])
        callbacks: list[str] = []

        class _Window(QWidget, ThemeControllerMixin):
            def __init__(self) -> None:
                super().__init__()
                self.current_theme_key = "crimson_desert"
                self.settings = _Settings({})
                self._pending_theme_key = None
                self._pending_appearance_change = {
                    "theme_key": "graphite",
                    "changed": ("theme",),
                    "requires_theme_apply": True,
                }
                self._appearance_apply_steps = deque()
                self._appearance_apply_app = None
                self._theme_change_in_progress = False
                self._theme_change_apply_timer = QTimer(self)
                self._appearance_apply_step_timer = QTimer(self)
                self._appearance_apply_step_timer.setSingleShot(True)
                self._appearance_apply_step_timer.setInterval(35)
                self._appearance_apply_step_timer.timeout.connect(self._run_next_appearance_apply_step)

            def _prepare_appearance_apply_steps(self, _payload: object, target_app: QApplication) -> None:
                self._appearance_apply_app = target_app
                self._appearance_apply_steps.extend(
                    (
                        ("one", lambda: callbacks.append("one")),
                        ("two", lambda: callbacks.append("two")),
                    )
                )

        window = _Window()
        try:
            window._apply_pending_theme_change()
            self.assertEqual(0, window._appearance_apply_step_timer.interval())
            deadline = 100
            while window._theme_change_in_progress and deadline > 0:
                QTest.qWait(1)
                deadline -= 1
            self.assertEqual(["one", "two"], callbacks)
            self.assertFalse(window._theme_change_in_progress)
        finally:
            if window._theme_change_in_progress:
                window._finish_appearance_apply_steps(delay_ms=0)
            window.deleteLater()
            app.processEvents()

    def test_theme_replacement_clears_the_old_qss_without_an_unstyled_event_turn(self) -> None:
        self._run_isolated_probe("_exercise_theme_replacement")

    def test_every_theme_keeps_text_selections_and_controls_visible(self) -> None:
        expected_roles = set(UI_THEME_SCHEMES["graphite"])
        self.assertIn("accent_text", expected_roles)
        for key, theme in UI_THEME_SCHEMES.items():
            with self.subTest(theme=key):
                if key in ADDED_THEMES:
                    self.assertEqual(ADDED_THEMES[key], theme["label"])
                self.assertEqual(expected_roles, set(theme))
                for role, value in theme.items():
                    if role != "label":
                        self.assertTrue(QColor(value).isValid(), f"{key}.{role}: {value}")

                for foreground in ("text", "text_muted", "text_strong"):
                    for background in ("window", "surface", "surface_alt", "field", "field_alt", "button"):
                        self.assertGreaterEqual(
                            _contrast_ratio(theme[foreground], theme[background]),
                            4.5,
                            f"{key}: {foreground} on {background}",
                        )
                for foreground in ("text", "text_strong"):
                    for background in ("button_hover", "button_pressed", "preview_bg"):
                        self.assertGreaterEqual(
                            _contrast_ratio(theme[foreground], theme[background]),
                            4.5,
                            f"{key}: {foreground} on {background}",
                        )
                for background in ("button_hover", "preview_bg"):
                    self.assertGreaterEqual(
                        _contrast_ratio(theme["text_muted"], theme[background]),
                        4.5,
                        f"{key}: text_muted on {background}",
                    )
                for foreground, background in (
                    ("button_disabled_text", "button_disabled"),
                    ("button_disabled_text", "surface"),
                    ("button_disabled_text", "surface_alt"),
                    ("text_strong", "accent_soft"),
                    ("warning_text", "warning_bg"),
                    ("warning_text", "surface"),
                    ("error", "window"),
                    ("error", "surface"),
                    ("accent", "window"),
                    ("accent", "surface"),
                    ("accent", "field"),
                    ("accent_text", "accent"),
                ):
                    self.assertGreaterEqual(
                        _contrast_ratio(theme[foreground], theme[background]),
                        4.5,
                        f"{key}: {foreground} on {background}",
                    )
                self.assertGreaterEqual(_contrast_ratio(theme["border_strong"], theme["field"]), 3.0, f"{key}: field border")
                self.assertGreaterEqual(_contrast_ratio(theme["button_border"], theme["button"]), 3.0, f"{key}: button border")
                self.assertGreaterEqual(
                    _contrast_ratio(theme["warning_border"], theme["warning_bg"]),
                    3.0,
                    f"{key}: warning border",
                )
                self.assertGreaterEqual(
                    _contrast_ratio(theme["accent"], theme["accent_soft"]),
                    3.0,
                    f"{key}: accent boundary",
                )

                palette = build_app_palette(key)
                self.assertEqual(theme["accent"], palette.color(QPalette.Highlight).name())
                self.assertEqual(theme["accent_text"], palette.color(QPalette.HighlightedText).name())
                stylesheet = build_app_stylesheet(key)
                self.assertIn(f"selection-color: {theme['accent_text']};", stylesheet)
                self.assertIn(f"background: {theme['preview_bg']};", stylesheet)

        desert_stylesheet = build_app_stylesheet("desert_dawn")
        self.assertIn("color: #0369a1;", desert_stylesheet)
        self.assertIn("color: #047857;", desert_stylesheet)

    def test_every_theme_renders_distinct_standard_button_states(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_palette = QPalette(app.palette())
        previous_style_sheet = app.styleSheet()
        parent = QWidget()
        parent.resize(320, 100)
        button = QPushButton("Theme action", parent)
        button.setCheckable(True)
        button.setGeometry(70, 28, 180, 38)

        def background_color(state: QStyle.StateFlag) -> str:
            image = QImage(button.size(), QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            option = QStyleOptionButton()
            option.initFrom(button)
            option.rect = button.rect()
            option.text = button.text()
            option.state = state
            painter = QPainter(image)
            button.style().drawControl(
                QStyle.ControlElement.CE_PushButton,
                option,
                painter,
                button,
            )
            painter.end()
            return image.pixelColor(8, button.height() // 2).name()

        try:
            parent.show()
            button.show()
            for theme_key, theme in UI_THEME_SCHEMES.items():
                with self.subTest(theme=theme_key):
                    app.setPalette(build_app_palette(theme_key))
                    app.setStyleSheet(build_app_stylesheet(theme_key))
                    app.processEvents()
                    enabled = QStyle.StateFlag.State_Enabled
                    normal = background_color(enabled)
                    hovered = background_color(enabled | QStyle.StateFlag.State_MouseOver)
                    pressed = background_color(enabled | QStyle.StateFlag.State_Sunken)
                    checked = background_color(enabled | QStyle.StateFlag.State_On)
                    checked_hover = background_color(
                        enabled | QStyle.StateFlag.State_On | QStyle.StateFlag.State_MouseOver
                    )
                    disabled = background_color(QStyle.StateFlag.State_None)

                    self.assertEqual(
                        (
                            theme["button"],
                            theme["button_hover"],
                            theme["button_pressed"],
                            theme["accent"],
                            theme["accent_soft"],
                            theme["button_disabled"],
                        ),
                        (normal, hovered, pressed, checked, checked_hover, disabled),
                    )
                    self.assertEqual(3, len({normal, hovered, pressed}))
                    self.assertNotEqual(checked, checked_hover)
                    self.assertNotEqual(normal, disabled)
                    self.assertGreaterEqual(
                        len({normal, hovered, pressed, checked, checked_hover, disabled}),
                        5,
                    )
        finally:
            parent.deleteLater()
            app.processEvents()
            app.setStyleSheet(previous_style_sheet)
            app.setPalette(previous_palette)

    def test_every_theme_renders_compact_editor_tool_checked_hover_feedback(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_palette = QPalette(app.palette())
        previous_style_sheet = app.styleSheet()
        parent = QWidget()
        parent.setProperty("compactPresentation", True)
        parent.resize(320, 100)
        button = QToolButton(parent)
        button.setObjectName("EditorToolButton")
        button.setText("Paint")
        button.setGeometry(70, 28, 180, 38)

        def background_color(state: QStyle.StateFlag) -> str:
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

        try:
            parent.show()
            button.show()
            for theme_key, theme in UI_THEME_SCHEMES.items():
                with self.subTest(theme=theme_key):
                    app.setPalette(build_app_palette(theme_key))
                    app.setStyleSheet(build_app_stylesheet(theme_key))
                    app.processEvents()
                    checked = background_color(
                        QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_On
                    )
                    checked_hover = background_color(
                        QStyle.StateFlag.State_Enabled
                        | QStyle.StateFlag.State_On
                        | QStyle.StateFlag.State_MouseOver
                    )
                    self.assertEqual(
                        (theme["accent_soft"], theme["accent"]),
                        (checked, checked_hover),
                    )
                    self.assertNotEqual(checked, checked_hover)
        finally:
            parent.deleteLater()
            app.processEvents()
            app.setStyleSheet(previous_style_sheet)
            app.setPalette(previous_palette)

    def test_mesh_editor_output_buttons_render_distinct_pointer_states(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_style_sheet = app.styleSheet()
        parent = QWidget()
        parent.resize(400, 100)
        object_names = (
            "MeshEditorRunValidationReportButton",
            "MeshEditorExportMeshFileButton",
            "MeshEditorBuildModButton",
            "MeshEditorInstallOverlayButton",
            "MeshEditorRestoreOverlayButton",
            "MeshEditorCloseSessionButton",
        )
        theme = UI_THEME_SCHEMES["graphite"]

        try:
            app.setStyleSheet(build_app_stylesheet("graphite"))
            parent.show()
            app.processEvents()

            for object_name in object_names:
                with self.subTest(button=object_name):
                    button = QToolButton(parent)
                    button.setObjectName(object_name)
                    button.setText("Mesh output")
                    button.setGeometry(100, 30, 180, 36)
                    button.show()
                    app.processEvents()

                    def background_color() -> str:
                        image = button.grab().toImage()
                        return image.pixelColor(button.width() - 8, button.height() // 2).name()

                    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                    button.update()
                    app.processEvents()
                    normal = background_color()
                    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
                    button.update()
                    app.processEvents()
                    hovered = background_color()
                    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
                    app.processEvents()
                    pressed = background_color()
                    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
                    button.setEnabled(False)
                    app.processEvents()
                    disabled = background_color()

                    self.assertEqual(
                        (theme["button"], theme["button_hover"], theme["accent_soft"], theme["button_disabled"]),
                        (normal, hovered, pressed, disabled),
                    )
                    self.assertEqual(4, len({normal, hovered, pressed, disabled}))
                    button.deleteLater()
        finally:
            parent.deleteLater()
            app.setStyleSheet(previous_style_sheet)

    def test_compact_archive_command_buttons_render_distinct_pointer_states(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_style_sheet = app.styleSheet()
        parent = QWidget()
        parent.setProperty("compactPresentation", True)
        parent.resize(520, 100)
        object_names = (
            "CompactArchiveSelectButton",
            "CompactArchiveActionsButton",
            "CompactArchiveMoreFiltersButton",
        )
        theme = UI_THEME_SCHEMES["graphite"]

        try:
            app.setStyleSheet(build_app_stylesheet("graphite"))
            parent.show()
            app.processEvents()

            for object_name in object_names:
                with self.subTest(button=object_name):
                    button = QToolButton(parent)
                    button.setObjectName(object_name)
                    button.setText("Archive command")
                    button.setGeometry(100, 30, 180, 36)
                    button.show()
                    app.processEvents()

                    def background_color() -> str:
                        image = button.grab().toImage()
                        return image.pixelColor(8, button.height() // 2).name()

                    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                    button.update()
                    app.processEvents()
                    normal = background_color()
                    button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
                    button.update()
                    app.processEvents()
                    hovered = background_color()
                    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
                    app.processEvents()
                    pressed = background_color()
                    QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=button.rect().center())
                    button.setEnabled(False)
                    app.processEvents()
                    disabled = background_color()

                    self.assertEqual(
                        (theme["button"], theme["button_hover"], theme["accent_soft"], theme["button_disabled"]),
                        (normal, hovered, pressed, disabled),
                    )
                    self.assertEqual(4, len({normal, hovered, pressed, disabled}))
                    if object_name != "CompactArchiveSelectButton":
                        button.setEnabled(True)
                        button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                        menu = QMenu(button)
                        menu.addAction("Archive action")
                        button.setMenu(menu)
                        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                        opened: dict[str, str] = {}

                        def capture_open_state() -> None:
                            opened["background"] = background_color()
                            menu.close()

                        QTimer.singleShot(10, capture_open_state)
                        button.showMenu()
                        self.assertEqual(theme["accent_soft"], opened.get("background"))
                    button.deleteLater()
        finally:
            parent.deleteLater()
            app.setStyleSheet(previous_style_sheet)

    def test_added_theme_icons_are_complete_visible_and_loadable(self) -> None:
        app = QApplication.instance() or QApplication([])
        icon_root = ROOT / "assets" / "theme_icons"
        for key in ADDED_THEMES:
            with self.subTest(theme=key):
                paths = {suffix: icon_root / f"cdmw_{key}{suffix}" for suffix in (".svg", ".png", ".ico")}
                for path in paths.values():
                    self.assertTrue(path.is_file(), path)
                    self.assertGreater(path.stat().st_size, 0, path)
                self.assertEqual(paths[".ico"].resolve(), resolve_app_icon_path(key))

                icon = QIcon(str(paths[".ico"]))
                self.assertFalse(icon.isNull())
                sizes = {(size.width(), size.height()) for size in icon.availableSizes()}
                self.assertTrue({(16, 16), (32, 32), (256, 256)}.issubset(sizes), sizes)

                image = QImage(str(paths[".png"]))
                self.assertFalse(image.isNull())
                self.assertEqual((1024, 1024), (image.width(), image.height()))
                samples = [image.pixelColor(x, y) for x, y in ((399, 399), (625, 399), (399, 625), (625, 625))]
                self.assertEqual(4, len({color.name() for color in samples}))
                luminances = [_relative_luminance(color.name()) for color in samples]
                self.assertGreaterEqual(max(luminances) - min(luminances), 0.30)

    def test_application_ui_font_change_refreshes_archive_controls_font(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_font = QFont(app.font())

        class _Window(QWidget, ThemeControllerMixin):
            def __init__(self) -> None:
                super().__init__()
                self.settings = _Settings(
                    {
                        "appearance/ui_font_family": previous_font.family(),
                        "appearance/ui_font_size": 14,
                        "appearance/data_font_size": 11,
                        "appearance/ui_density": "compact",
                    }
                )
                self.archive_controls_group = QWidget(self)

        window = _Window()
        try:
            stale_font = QFont(previous_font)
            stale_font.setPointSize(9)
            window.archive_controls_group.setFont(stale_font)

            ui_font = QFont(previous_font)
            ui_font.setPointSize(14)
            window._sync_archive_controls_font(ui_font)

            self.assertEqual(13, window.archive_controls_group.font().pointSize())
        finally:
            window.deleteLater()
            app.setFont(previous_font)

    def test_theme_change_busy_overlay_updates_state_and_timers(self) -> None:
        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        parent.resize(320, 180)
        parent.show()
        overlay = ThemeChangeBusyOverlay(parent)

        overlay.show_appearance_change("graphite", title="Applying Graphite", detail="Working")
        app.processEvents()

        self.assertEqual("ThemeChangeBusyOverlay", overlay.objectName())
        self.assertTrue(overlay.isVisible())
        self.assertEqual(parent.rect(), overlay.geometry())

        overlay.finish(0)
        app.processEvents()
        overlay.deleteLater()
        parent.deleteLater()

    def test_apply_app_fonts_updates_existing_styled_child_controls(self) -> None:
        self._run_isolated_probe("_exercise_existing_styled_child_font_update")

    def test_compact_layout_keeps_each_configured_font_size_distinct(self) -> None:
        self._run_isolated_probe("_exercise_compact_font_sizes")

    def test_apply_window_ui_fonts_updates_startup_widget_tree(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_font = QFont(app.font())
        previous_style_sheet = app.styleSheet()
        window = QWidget()
        try:
            window.settings = _Settings(  # type: ignore[attr-defined]
                {
                    "appearance/ui_font_family": previous_font.family(),
                    "appearance/ui_font_size": 15,
                    "appearance/data_font_size": 11,
                    "appearance/ui_density": "comfortable",
                }
            )
            label = QLabel("Label")
            list_widget = QListWidget()
            tree_widget = QTreeWidget()
            tree_widget.setColumnCount(2)
            tree_widget.setHeaderLabels(("Name", "Type"))
            table_widget = QTableWidget(1, 2)
            table_widget.setHorizontalHeaderLabels(("Name", "Type"))
            layout = QVBoxLayout(window)
            layout.addWidget(label)
            layout.addWidget(list_widget)
            layout.addWidget(tree_widget)
            layout.addWidget(table_widget)

            resolved_fonts = apply_window_ui_fonts(window, app)  # type: ignore[arg-type]

            self.assertIsNotNone(resolved_fonts)
            ui_font, data_font = resolved_fonts or (QFont(), QFont())
            self.assertEqual(ui_font.pointSize(), label.font().pointSize())
            self.assertEqual(data_font.pointSize(), list_widget.font().pointSize())
            self.assertEqual(data_font.pointSize(), tree_widget.font().pointSize())
            self.assertEqual(data_font.pointSize(), tree_widget.header().font().pointSize())
            self.assertEqual(data_font.pointSize(), table_widget.font().pointSize())
            self.assertEqual(data_font.pointSize(), table_widget.horizontalHeader().font().pointSize())
            self.assertEqual(data_font.pointSize(), table_widget.verticalHeader().font().pointSize())
        finally:
            window.deleteLater()
            app.setFont(previous_font)
            for class_name in (
                "QWidget",
                "QListView",
                "QListWidget",
                "QTreeView",
                "QTreeWidget",
                "QTableView",
                "QTableWidget",
                "QHeaderView",
            ):
                app.setFont(previous_font, class_name)
            app.setStyleSheet(previous_style_sheet)

    def test_custom_text_font_stays_out_of_global_font_sync(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_font = QFont(app.font())
        previous_style_sheet = app.styleSheet()
        window = QWidget()
        try:
            window.settings = _Settings(  # type: ignore[attr-defined]
                {
                    "appearance/ui_font_family": previous_font.family(),
                    "appearance/ui_font_size": 15,
                    "appearance/data_font_size": 11,
                    "appearance/ui_density": "comfortable",
                }
            )
            label = QLabel("Code")
            layout = QVBoxLayout(window)
            layout.addWidget(label)
            apply_window_ui_fonts(window, app)  # type: ignore[arg-type]

            custom_font = QFont(label.font())
            custom_font.setPointSize(7)
            ThemeControllerMixin._apply_single_text_widget_font(object(), label, custom_font)  # type: ignore[arg-type]
            window.settings = _Settings(  # type: ignore[attr-defined]
                {
                    "appearance/ui_font_family": previous_font.family(),
                    "appearance/ui_font_size": 12,
                    "appearance/data_font_size": 10,
                    "appearance/ui_density": "comfortable",
                }
            )
            apply_window_ui_fonts(window, app)  # type: ignore[arg-type]

            self.assertEqual(7, label.font().pointSize())
        finally:
            window.deleteLater()
            app.setFont(previous_font)
            for class_name in (
                "QWidget",
                "QListView",
                "QListWidget",
                "QTreeView",
                "QTreeWidget",
                "QTableView",
                "QTableWidget",
                "QHeaderView",
            ):
                app.setFont(previous_font, class_name)
            app.setStyleSheet(previous_style_sheet)

    def test_settings_appearance_payload_routes_font_changes_without_full_theme_apply(self) -> None:
        previous = {
            "theme": "graphite",
            "ui_font_family": "Segoe UI",
            "ui_density": "compact",
            "ui_font_size": 10,
            "data_font_size": 9,
            "log_font_family": "Consolas",
            "log_font_size": 10,
            "log_font_bold": True,
            "log_text_style": "rich",
            "log_color_scheme": "theme",
            "preview_color_scheme": "theme",
        }
        current = dict(previous)
        current["ui_font_size"] = 12

        payload = SettingsTab._appearance_change_payload(object(), previous, current)  # type: ignore[arg-type]

        self.assertEqual(("ui_font_size",), payload["changed"])
        self.assertFalse(payload["requires_theme_apply"])
        self.assertTrue(payload["requires_ui_fonts"])
        self.assertFalse(payload["requires_data_fonts"])
        self.assertFalse(payload["requires_text_colors"])

    def test_live_log_font_apply_routes_to_compact_activity_drawer(self) -> None:
        queued_steps: list[tuple[str, object]] = []
        applied_fonts: list[QFont] = []
        drawer = SimpleNamespace(apply_log_font=lambda font: applied_fonts.append(QFont(font)))
        owner = SimpleNamespace(
            settings=_Settings({"appearance/log_font_size": 16}),
            log_view=object(),
            archive_log_view=object(),
            archive_preview_text_edit=object(),
            archive_preview_info_edit=object(),
            archive_preview_details_edit=object(),
            log_highlighter=object(),
            archive_log_highlighter=object(),
            compact_workspace=SimpleNamespace(drawer=drawer),
            _queue_appearance_apply_step=lambda label, callback: queued_steps.append((label, callback)),
        )

        ThemeControllerMixin._queue_data_font_apply_steps(owner, schedule_column_autofit=False)  # type: ignore[arg-type]
        compact_callback = next(
            callback for label, callback in queued_steps if label == "Updating compact activity log font"
        )
        compact_callback()  # type: ignore[operator]

        self.assertEqual(1, len(applied_fonts))
        self.assertEqual(16, applied_fonts[0].pointSize())

    def test_settings_appearance_payload_keeps_theme_and_text_routes_separate(self) -> None:
        previous = {
            "theme": "graphite",
            "ui_font_family": "Segoe UI",
            "ui_density": "compact",
            "ui_font_size": 10,
            "data_font_size": 9,
            "log_font_family": "Consolas",
            "log_font_size": 10,
            "log_font_bold": True,
            "log_text_style": "rich",
            "log_color_scheme": "theme",
            "preview_color_scheme": "theme",
        }

        theme_current = dict(previous)
        theme_current["theme"] = "light"
        theme_payload = SettingsTab._appearance_change_payload(object(), previous, theme_current)  # type: ignore[arg-type]
        self.assertTrue(theme_payload["requires_theme_apply"])
        self.assertFalse(theme_payload["requires_ui_fonts"])

        log_current = dict(previous)
        log_current["log_font_size"] = 12
        log_payload = SettingsTab._appearance_change_payload(object(), previous, log_current)  # type: ignore[arg-type]
        self.assertFalse(log_payload["requires_theme_apply"])
        self.assertFalse(log_payload["requires_ui_fonts"])
        self.assertTrue(log_payload["requires_data_fonts"])

        color_current = dict(previous)
        color_current["log_color_scheme"] = "terminal"
        color_payload = SettingsTab._appearance_change_payload(object(), previous, color_current)  # type: ignore[arg-type]
        self.assertFalse(color_payload["requires_theme_apply"])
        self.assertFalse(color_payload["requires_ui_fonts"])
        self.assertFalse(color_payload["requires_data_fonts"])
        self.assertTrue(color_payload["requires_text_colors"])


if __name__ == "__main__":
    unittest.main()
