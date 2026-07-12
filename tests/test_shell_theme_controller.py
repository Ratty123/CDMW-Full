from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QFont, QIcon, QImage
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.settings_tab import SettingsTab
from cdmw.ui.app_icon import resolve_app_icon_path
from cdmw.ui.shell.theme_controller import ThemeChangeBusyOverlay, ThemeControllerMixin, apply_app_fonts, apply_window_ui_fonts
from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_stylesheet


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


class ShellThemeControllerTests(unittest.TestCase):
    def test_added_themes_keep_text_selections_and_controls_visible(self) -> None:
        expected_roles = set(UI_THEME_SCHEMES["graphite"])
        for key, label in ADDED_THEMES.items():
            with self.subTest(theme=key):
                theme = UI_THEME_SCHEMES[key]
                self.assertEqual(label, theme["label"])
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
                for foreground, background in (
                    ("button_disabled_text", "button_disabled"),
                    ("text_strong", "accent_soft"),
                    ("warning_text", "warning_bg"),
                    ("error", "window"),
                    ("accent", "window"),
                ):
                    self.assertGreaterEqual(
                        _contrast_ratio(theme[foreground], theme[background]),
                        4.5,
                        f"{key}: {foreground} on {background}",
                    )
                self.assertGreaterEqual(_contrast_ratio("#ffffff", theme["accent"]), 4.5, f"{key}: selection text")
                self.assertGreaterEqual(_contrast_ratio(theme["border_strong"], theme["field"]), 3.0, f"{key}: field border")
                self.assertGreaterEqual(_contrast_ratio(theme["button_border"], theme["button"]), 3.0, f"{key}: button border")

        desert_stylesheet = build_app_stylesheet("desert_dawn")
        self.assertIn("color: #0369a1;", desert_stylesheet)
        self.assertIn("color: #047857;", desert_stylesheet)

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

            self.assertEqual(15, label.font().pointSize())
            self.assertEqual(15, button.font().pointSize())
            self.assertEqual(11, list_widget.font().pointSize())
        finally:
            parent.deleteLater()
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
            layout = QVBoxLayout(window)
            layout.addWidget(label)
            layout.addWidget(list_widget)

            resolved_fonts = apply_window_ui_fonts(window, app)  # type: ignore[arg-type]

            self.assertIsNotNone(resolved_fonts)
            ui_font, data_font = resolved_fonts or (QFont(), QFont())
            self.assertEqual(ui_font.pointSize(), label.font().pointSize())
            self.assertEqual(data_font.pointSize(), list_widget.font().pointSize())
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
