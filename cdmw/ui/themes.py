from __future__ import annotations

from typing import Dict

from PySide6.QtGui import QColor, QPalette

from cdmw.constants import (
    DEFAULT_UI_DATA_FONT_SIZE,
    DEFAULT_UI_DENSITY,
    DEFAULT_UI_FONT_SIZE,
    DEFAULT_UI_THEME,
    MODEL_PREVIEW_BACKGROUND_COLOR,
)

from cdmw.ui.theme_schemes import UI_THEME_SCHEMES


def get_theme(key: str) -> Dict[str, str]:
    return UI_THEME_SCHEMES.get(key, UI_THEME_SCHEMES[DEFAULT_UI_THEME])


def _clamp_font_size(value: int, default: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(9, min(16, numeric))


def _density_metrics(density_key: str) -> Dict[str, int]:
    density = (density_key or DEFAULT_UI_DENSITY).strip().lower()
    if density == "comfortable":
        return {
            "menu_pad_y": 5,
            "menu_pad_x": 10,
            "menu_item_pad_y": 6,
            "menu_item_pad_x": 12,
            "group_margin_top": 18,
            "group_pad_top": 12,
            "group_title_pad_y": 1,
            "group_title_pad_x": 8,
            "section_pad_y": 8,
            "section_pad_x": 10,
            "field_pad_y": 6,
            "field_pad_x": 9,
            "list_pad_y": 4,
            "list_pad_x": 6,
            "header_pad_y": 6,
            "header_pad_x": 8,
            "button_pad_y": 7,
            "button_pad_x": 12,
            "button_min_h": 22,
            "progress_min_h": 24,
            "tab_pad_top": 8,
            "tab_pad_bottom": 9,
            "tab_pad_x": 14,
            "tab_min_h": 24,
        }
    if density == "normal":
        return {
            "menu_pad_y": 4,
            "menu_pad_x": 9,
            "menu_item_pad_y": 5,
            "menu_item_pad_x": 10,
            "group_margin_top": 15,
            "group_pad_top": 10,
            "group_title_pad_y": 0,
            "group_title_pad_x": 7,
            "section_pad_y": 6,
            "section_pad_x": 9,
            "field_pad_y": 5,
            "field_pad_x": 8,
            "list_pad_y": 3,
            "list_pad_x": 5,
            "header_pad_y": 5,
            "header_pad_x": 7,
            "button_pad_y": 5,
            "button_pad_x": 10,
            "button_min_h": 18,
            "progress_min_h": 20,
            "tab_pad_top": 6,
            "tab_pad_bottom": 7,
            "tab_pad_x": 12,
            "tab_min_h": 20,
        }
    return {
        "menu_pad_y": 3,
        "menu_pad_x": 8,
        "menu_item_pad_y": 4,
        "menu_item_pad_x": 9,
        "group_margin_top": 13,
        "group_pad_top": 8,
        "group_title_pad_y": 0,
        "group_title_pad_x": 6,
        "section_pad_y": 5,
        "section_pad_x": 8,
        "field_pad_y": 4,
        "field_pad_x": 7,
        "list_pad_y": 2,
        "list_pad_x": 5,
        "header_pad_y": 4,
        "header_pad_x": 6,
        "button_pad_y": 4,
        "button_pad_x": 8,
        "button_min_h": 16,
        "progress_min_h": 18,
        "tab_pad_top": 5,
        "tab_pad_bottom": 6,
        "tab_pad_x": 10,
        "tab_min_h": 18,
    }


def _scale_density_metrics(metrics: Dict[str, int], scale: float) -> Dict[str, int]:
    safe_scale = max(0.72, min(1.15, float(scale or 1.0)))
    scaled: Dict[str, int] = {}
    for key, value in metrics.items():
        minimum = 0 if "pad" in key or "margin" in key else 1
        if key in {"button_min_h", "progress_min_h", "tab_min_h"}:
            minimum = 12
        scaled[key] = max(minimum, int(round(int(value) * safe_scale)))
    return scaled


def build_app_palette(theme_key: str) -> QPalette:
    theme = get_theme(theme_key)
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(theme["window"]))
    palette.setColor(QPalette.WindowText, QColor(theme["text"]))
    palette.setColor(QPalette.Base, QColor(theme["field"]))
    palette.setColor(QPalette.AlternateBase, QColor(theme["field_alt"]))
    palette.setColor(QPalette.ToolTipBase, QColor(theme["surface"]))
    palette.setColor(QPalette.ToolTipText, QColor(theme["text_strong"]))
    palette.setColor(QPalette.Text, QColor(theme["text"]))
    palette.setColor(QPalette.Button, QColor(theme["button"]))
    palette.setColor(QPalette.ButtonText, QColor(theme["text_strong"]))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor(theme["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.PlaceholderText, QColor(theme["text_muted"]))
    palette.setColor(QPalette.Link, QColor(theme["accent"]))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(theme["button_disabled_text"]))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(theme["button_disabled_text"]))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(theme["button_disabled_text"]))
    return palette


def build_app_stylesheet(
    theme_key: str, *,
    base_font_size: int = DEFAULT_UI_FONT_SIZE,
    data_font_size: int = DEFAULT_UI_DATA_FONT_SIZE,
    density_key: str = DEFAULT_UI_DENSITY,
    layout_scale: float = 1.0,
) -> str:
    theme = get_theme(theme_key)
    metrics = _scale_density_metrics(_density_metrics(density_key), layout_scale)
    light_theme = QColor(theme["window"]).lightnessF() >= 0.55
    role_text = {
        "identity": "#b45309" if theme_key == "crimson_desert" else "#0369a1" if light_theme else "#7dd3fc",
        "dds": "#c56d43" if theme_key == "crimson_desert" else "#047857" if light_theme else "#86efac",
        "ncnn": "#d89a5f" if theme_key == "crimson_desert" else "#6d28d9" if light_theme else "#c4b5fd",
        "correction": "#e8b66d" if theme_key == "crimson_desert" else "#b45309" if light_theme else "#fbbf24",
    }
    return f"""
    QWidget {{
        color: {theme["text"]};
    }}
    QMainWindow, QWidget#AppRoot {{
        background: {theme["window"]};
    }}
    QMenuBar {{
        background: {theme["surface"]};
        color: {theme["text"]};
        border-bottom: 1px solid {theme["border"]};
        padding: 0 4px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: {metrics["menu_pad_y"]}px {metrics["menu_pad_x"]}px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background: {theme["button_hover"]};
    }}
    QMenu {{
        background: {theme["surface"]};
        color: {theme["text"]};
        border: 1px solid {theme["border_strong"]};
        padding: 4px;
    }}
    QMenu::item {{
        padding: {metrics["menu_item_pad_y"]}px 16px {metrics["menu_item_pad_y"]}px {metrics["menu_item_pad_x"]}px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: {theme["accent_soft"]};
        color: {theme["text_strong"]};
    }}
    QMenu::item:disabled {{
        color: {theme["button_disabled_text"]};
        background: transparent;
    }}
    QMenu::item:!enabled {{
        color: {theme["button_disabled_text"]};
        background: transparent;
    }}
    QMenu::item:selected:disabled {{
        color: {theme["button_disabled_text"]};
        background: {theme["surface_alt"]};
    }}
    QMenu::item:disabled:selected {{
        color: {theme["button_disabled_text"]};
        background: {theme["surface_alt"]};
    }}
    QMenu::item:selected:!enabled {{
        color: {theme["button_disabled_text"]};
        background: {theme["surface_alt"]};
    }}
    QMenu::item:!enabled:selected {{
        color: {theme["button_disabled_text"]};
        background: {theme["surface_alt"]};
    }}
    QLabel, QCheckBox, QToolButton {{
        background: transparent;
    }}
    QToolButton#ArchiveActionMenuButton {{
        background: {theme["button"]};
        color: {theme["text"]};
        border: 1px solid {theme["button_border"]};
        border-radius: 4px;
        padding: {metrics["button_pad_y"]}px {metrics["button_pad_x"]}px;
    }}
    QToolButton#ArchiveActionMenuButton:hover {{
        background: {theme["button_hover"]};
    }}
    QToolButton#ArchiveActionMenuButton:pressed {{
        background: {theme["button_pressed"]};
    }}
    QToolButton#ArchiveActionMenuButton:disabled {{
        color: {theme["button_disabled_text"]};
        background: {theme["button_disabled"]};
        border-color: {theme["border"]};
    }}
    QWidget#FlatSectionPanel {{
        background: {theme["surface"]};
    }}
    QWidget#FlatSectionHeader {{
        background: transparent;
    }}
    QLabel#FlatSectionTitle {{
        color: {theme["text_strong"]};
        font-weight: 600;
        background: transparent;
        padding: 0px {metrics["group_title_pad_x"] + 2}px 1px {metrics["group_title_pad_x"] + 2}px;
        border: none;
    }}
    QFrame#FlatSectionBody {{
        background: {theme["surface"]};
        border: 1px solid {theme["border"]};
        border-radius: 5px;
    }}
    QWidget#EmptyStatePanel {{
        background: {theme["preview_bg"]};
        border: 1px dashed {theme["border_strong"]};
        border-radius: 5px;
    }}
    QLabel#EmptyStateTitle {{
        color: {theme["text_strong"]};
        font-weight: 600;
        background: transparent;
    }}
    QLabel#EmptyStateDetail {{
        color: {theme["text_muted"]};
        background: transparent;
    }}
    QGroupBox {{
        border: 1px solid {theme["border"]};
        border-radius: 5px;
        margin-top: {max(18, metrics["group_margin_top"] + 5)}px;
        padding-top: {max(10, metrics["group_pad_top"] + 1)}px;
        font-weight: 600;
        background: {theme["surface"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 14px;
        top: 0px;
        margin: 0px;
        padding: 0px {metrics["group_title_pad_x"] + 2}px 1px {metrics["group_title_pad_x"] + 2}px;
        color: {theme["text_strong"]};
        background: transparent;
    }}
    QToolButton#SectionToggle {{
        text-align: left;
        background: {theme["surface_alt"]};
        color: {theme["text_strong"]};
        border: 1px solid {theme["border"]};
        border-radius: 4px;
        padding: {metrics["section_pad_y"]}px {metrics["section_pad_x"]}px;
        font-weight: 600;
    }}
    QToolButton#SectionToggle:hover {{
        background: {theme["button_hover"]};
    }}
    QToolButton#SectionToggle:checked {{
        background: {theme["button"]};
    }}
    QFrame#SectionBody {{
        border: 1px solid {theme["border"]};
        border-radius: 5px;
        background: {theme["surface"]};
    }}
    QFrame#WorkflowProfilePanel {{
        background: {theme["field_alt"]};
        border: 1px solid {theme["border"]};
        border-radius: 4px;
    }}
    QFrame#WorkflowProfilePanel[profileRole="identity"] {{
        border-left: 3px solid #38bdf8;
    }}
    QFrame#WorkflowProfilePanel[profileRole="dds"] {{
        border-left: 3px solid #22c55e;
    }}
    QFrame#WorkflowProfilePanel[profileRole="ncnn"] {{
        border-left: 3px solid #a78bfa;
    }}
    QFrame#WorkflowProfilePanel[profileRole="correction"] {{
        border-left: 3px solid #f59e0b;
    }}
    QLabel#WorkflowProfilePanelTitle {{
        font-weight: 700;
        background: transparent;
    }}
    QLabel#WorkflowProfilePanelTitle[profileRole="identity"] {{
        color: {role_text["identity"]};
    }}
    QLabel#WorkflowProfilePanelTitle[profileRole="dds"] {{
        color: {role_text["dds"]};
    }}
    QLabel#WorkflowProfilePanelTitle[profileRole="ncnn"] {{
        color: {role_text["ncnn"]};
    }}
    QLabel#WorkflowProfilePanelTitle[profileRole="correction"] {{
        color: {role_text["correction"]};
    }}
    QLabel#WorkflowProfileFieldLabel {{
        color: {theme["text_strong"]};
        background: transparent;
        font-weight: 600;
    }}
    QFrame#DdsFlowPanel {{
        background: {theme["field_alt"]};
        border: 1px solid {theme["border_strong"]};
        border-radius: 5px;
    }}
    QFrame#DdsFlowRow {{
        background: {theme["surface"]};
        border: 1px solid {theme["border"]};
        border-radius: 4px;
    }}
    QLabel#DdsFlowChip {{
        border-radius: 5px;
        background: {theme["text_muted"]};
    }}
    QLabel#DdsFlowChip[flowRole="source"] {{
        background: #38bdf8;
    }}
    QLabel#DdsFlowChip[flowRole="final"] {{
        background: #22c55e;
    }}
    QLabel#DdsFlowChip[flowRole="dds"] {{
        background: #f59e0b;
    }}
    QLabel#DdsFlowChip[flowRole="note"] {{
        background: #f87171;
    }}
    QLabel#DdsFlowTitle {{
        color: {theme["text_strong"]};
        background: transparent;
        font-weight: 700;
    }}
    QLabel#DdsFlowValue {{
        color: {theme["text"]};
        background: {theme["field"]};
        border: 1px solid {theme["border"]};
        border-radius: 4px;
        padding: 4px 6px;
    }}
    QFrame#GuidancePanel {{
        background: transparent;
        border: 1px solid {theme["border"]};
        border-radius: 4px;
    }}
    QFrame#GuidanceRow {{
        background: transparent;
        border: none;
        border-radius: 0px;
    }}
    QFrame#GuidanceRow[guidanceRole="warning"],
    QFrame#GuidanceRow[guidanceRole="override"] {{
        background: {theme["warning_bg"]};
        border: 1px solid {theme["warning_border"]};
        border-radius: 4px;
    }}
    QLabel#GuidanceChip {{
        border-radius: 5px;
        background: {theme["text_muted"]};
    }}
    QLabel#GuidanceChip[guidanceRole="summary"],
    QLabel#GuidanceChip[guidanceRole="scope"] {{
        background: #38bdf8;
    }}
    QLabel#GuidanceChip[guidanceRole="upscaled"],
    QLabel#GuidanceChip[guidanceRole="scale"] {{
        background: #22c55e;
    }}
    QLabel#GuidanceChip[guidanceRole="copied"],
    QLabel#GuidanceChip[guidanceRole="tile"] {{
        background: #a78bfa;
    }}
    QLabel#GuidanceChip[guidanceRole="rules"],
    QLabel#GuidanceChip[guidanceRole="correction"] {{
        background: #f59e0b;
    }}
    QLabel#GuidanceChip[guidanceRole="override"],
    QLabel#GuidanceChip[guidanceRole="warning"] {{
        background: #f87171;
    }}
    QLabel#GuidanceTitle {{
        color: {theme["text_strong"]};
        background: transparent;
        font-weight: 700;
    }}
    QLabel#GuidanceValue {{
        color: {theme["text"]};
        background: transparent;
        border: none;
        padding: 1px 0px;
    }}
    QFrame#GuidanceRow[guidanceRole="warning"] QLabel#GuidanceValue,
    QFrame#GuidanceRow[guidanceRole="override"] QLabel#GuidanceValue {{
        color: {theme["warning_text"]};
        background: transparent;
        border: none;
    }}
    QLineEdit, QPlainTextEdit, QTextBrowser, QComboBox, QSpinBox {{
        background: {theme["field"]};
        border: 1px solid {theme["border_strong"]};
        border-radius: 4px;
        padding: {metrics["field_pad_y"]}px {metrics["field_pad_x"]}px;
        selection-background-color: {theme["accent"]};
        selection-color: #ffffff;
    }}
    QComboBox {{
        padding-right: 24px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {theme["field"]};
        color: {theme["text"]};
        border: 1px solid {theme["border_strong"]};
        selection-background-color: {theme["accent_soft"]};
        selection-color: {theme["text_strong"]};
    }}
    QListWidget, QTreeWidget {{
        background: {theme["field"]};
        border: 1px solid {theme["border_strong"]};
        border-radius: 4px;
        padding: 2px;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QAbstractScrollArea {{
        background: transparent;
    }}
    QScrollArea#ArchiveControlsScroll,
    QWidget#ArchiveControlsViewport,
    QWidget#ArchiveControlsWrapper {{
        background: {theme["surface"]};
    }}
    QListWidget::item {{
        padding: {metrics["list_pad_y"] + 1}px {metrics["list_pad_x"]}px;
        border-radius: 3px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {theme["accent_soft"]};
        color: {theme["text_strong"]};
    }}
    QTreeWidget::item {{
        padding: {metrics["list_pad_y"]}px {metrics["list_pad_x"]}px;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus, QComboBox:focus, QSpinBox:focus,
    QListWidget:focus, QTreeWidget:focus {{
        border: 1px solid {theme["accent"]};
    }}
    QHeaderView::section {{
        background: {theme["surface_alt"]};
        color: {theme["text_muted"]};
        border: none;
        border-right: 1px solid {theme["border"]};
        padding: {metrics["header_pad_y"]}px {metrics["header_pad_x"]}px;
    }}
    QPushButton {{
        background: {theme["button"]};
        border: 1px solid {theme["button_border"]};
        border-radius: 4px;
        padding: {metrics["button_pad_y"]}px {metrics["button_pad_x"]}px;
        min-height: {metrics["button_min_h"]}px;
    }}
    QPushButton:hover {{
        background: {theme["button_hover"]};
    }}
    QPushButton:pressed {{
        background: {theme["button_pressed"]};
    }}
    QPushButton:checked {{
        color: #ffffff;
        background: #16803c;
        border-color: #2fbf64;
        font-weight: 600;
    }}
    QPushButton:checked:hover {{
        background: #1f9a4d;
    }}
    QPushButton:disabled {{
        color: {theme["button_disabled_text"]};
        background: {theme["button_disabled"]};
        border-color: {theme["border"]};
    }}
    QLabel#ArchiveCacheStatusChip {{
        color: {theme["text"]};
        background: {theme["field_alt"]};
        border: 1px solid {theme["border"]};
        border-radius: 4px;
        padding: 3px 6px;
    }}
    QLabel#HintLabel[healthState="healthy"] {{
        color: #2fbf64;
        border-color: #2fbf64;
        font-weight: 700;
    }}
    QLabel#HintLabel[healthState="building"] {{
        color: {theme["accent"]};
        border-color: {theme["accent"]};
        font-weight: 600;
    }}
    QLabel#HintLabel[healthState="missing"],
    QLabel#HintLabel[healthState="stale"] {{
        color: {theme["warning_text"]};
        border-color: {theme["warning_border"]};
        font-weight: 600;
    }}
    QLabel#HintLabel[healthState="unhealthy"] {{
        color: {theme["error"]};
        border-color: {theme["error"]};
        font-weight: 700;
    }}
    QCheckBox {{
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {theme["button_border"]};
        background: {theme["field"]};
    }}
    QCheckBox::indicator:checked {{
        background: {theme["accent"]};
        border: 1px solid {theme["accent"]};
    }}
    QProgressBar {{
        border: 1px solid {theme["border_strong"]};
        border-radius: 4px;
        background: {theme["field"]};
        color: #ffffff;
        font-weight: 600;
        text-align: center;
        min-height: {metrics["progress_min_h"]}px;
    }}
    QProgressBar::chunk {{
        border-radius: 3px;
        background: {theme["accent"]};
    }}
    QLabel#HintLabel {{
        color: {theme["text_muted"]};
        background: transparent;
    }}
    QLabel#SettingsPerformanceOverview {{
        color: {theme["text_strong"]};
        background: {theme["field_alt"]};
        border: 1px solid {theme["border"]};
        border-radius: 4px;
        padding: 6px 8px;
        font-weight: 600;
    }}
    QLabel#SettingsPerformanceField {{
        color: {theme["text_strong"]};
        background: transparent;
        font-weight: 600;
    }}
    QLabel#SettingsPerformanceNote {{
        color: {theme["text"]};
        background: transparent;
    }}
    QLabel#ArchivePreviewHealthLabel {{
        color: {theme["text_muted"]};
        background: transparent;
    }}
    QLabel#ArchivePreviewHealthLabel[attention="true"] {{
        color: {theme["warning_text"]};
        background: {theme["warning_bg"]};
        border: 1px solid {theme["warning_border"]};
        border-radius: 4px;
        padding: 2px 6px;
        font-weight: 600;
    }}
    QLabel#WarningBadge {{
        color: {theme["warning_text"]};
        background: {theme["warning_bg"]};
        border: 1px solid {theme["warning_border"]};
        border-radius: 4px;
        padding: 4px 8px;
        font-weight: 600;
    }}
    QLabel#WarningText {{
        color: {theme["warning_text"]};
        background: transparent;
    }}
    QLabel#StatusLabel {{
        color: {theme["text_muted"]};
        background: transparent;
    }}
    QLabel#StatusLabel[error="true"] {{
        color: {theme["error"]};
    }}
    QLabel#PreviewLabel {{
        border: 1px solid {theme["border_strong"]};
        border-radius: 5px;
        background: {MODEL_PREVIEW_BACKGROUND_COLOR};
        color: {theme["text_muted"]};
        padding: 8px;
    }}
    QTabWidget::pane {{
        border: 1px solid {theme["border"]};
        border-radius: 4px;
        background: {theme["surface"]};
        top: 0px;
    }}
    QTabBar::tab {{
        background: {theme["surface_alt"]};
        color: {theme["text_muted"]};
        padding: {metrics["tab_pad_top"]}px {metrics["tab_pad_x"]}px {metrics["tab_pad_bottom"]}px {metrics["tab_pad_x"]}px;
        min-height: {metrics["tab_min_h"]}px;
        border: 1px solid {theme["border"]};
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
        margin-right: 1px;
    }}
    QTabBar::tab:selected {{
        background: {theme["surface"]};
        color: {theme["text_strong"]};
        border-color: {theme["border_strong"]};
    }}
    QTabBar::tab:hover:!selected {{
        background: {theme["button_hover"]};
    }}
    QSplitter::handle {{
        background: {theme["surface_alt"]};
        width: 4px;
    }}
    QScrollBar:vertical {{
        background: {theme["field"]};
        width: 12px;
        margin: 1px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {theme["button_border"]};
        border: 1px solid {theme["border_strong"]};
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {theme["accent_soft"]};
        border: 1px solid {theme["accent"]};
    }}
    QScrollBar::handle:vertical:pressed {{
        background: {theme["accent"]};
        border: 1px solid {theme["accent"]};
    }}
    QScrollBar:horizontal {{
        background: {theme["field"]};
        height: 12px;
        margin: 1px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {theme["button_border"]};
        border: 1px solid {theme["border_strong"]};
        min-width: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {theme["accent_soft"]};
        border: 1px solid {theme["accent"]};
    }}
    QScrollBar::handle:horizontal:pressed {{
        background: {theme["accent"]};
        border: 1px solid {theme["accent"]};
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
        border-radius: 4px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        background: transparent;
        border: none;
        width: 0px;
        height: 0px;
    }}
    QToolTip {{
        background: {theme["surface_alt"]};
        color: {theme["text_strong"]};
        border: 1px solid {theme["border"]};
        padding: 6px 8px;
    }}
    """
