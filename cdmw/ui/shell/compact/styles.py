from __future__ import annotations

from typing import Dict

def _compact_tool_shape_override_stylesheet(theme: Dict[str, str]) -> str:
    """Override tool-owned QSS at its higher Qt cascade level without changing sizing."""
    return f"""
    QWidget[compactPresentation="true"] QWidget#FlatSectionPanel,
    QWidget[compactPresentation="true"] QWidget#FlatSectionHeader,
    QWidget[compactPresentation="true"] QWidget#EmptyStatePanel,
    QWidget[compactPresentation="true"] QWidget[compactFlatSurface="true"],
    QWidget[compactPresentation="true"] QFrame[compactFlatSurface="true"],
    QWidget[compactPresentation="true"] QGroupBox[compactFlatSurface="true"],
    QWidget[compactPresentation="true"] QFrame#FlatSectionBody,
    QWidget[compactPresentation="true"] QFrame#SectionBody,
    QWidget[compactPresentation="true"] QFrame#WorkflowProfilePanel,
    QWidget[compactPresentation="true"] QFrame#DdsFlowPanel,
    QWidget[compactPresentation="true"] QFrame#DdsFlowRow,
    QWidget[compactPresentation="true"] QFrame#GuidancePanel,
    QWidget[compactPresentation="true"] QFrame#GuidanceRow,
    QWidget[compactPresentation="true"] QFrame#EditorSectionBody,
    QWidget[compactPresentation="true"] QFrame#EditorActionPane,
    QWidget[compactPresentation="true"] QWidget#EditorLeftSidebar,
    QWidget[compactPresentation="true"] QWidget#EditorInspectorSidebar,
    QWidget[compactPresentation="true"] QWidget#EditorCanvasPane {{
        background: transparent;
        border: none;
        border-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QGroupBox {{
        background: transparent;
        border: none;
        border-radius: 0px;
        margin-top: 10px;
        padding-top: 4px;
    }}
    QWidget[compactPresentation="true"] QGroupBox::title {{
        left: 2px;
        top: 0px;
        margin: 0px;
        padding: 0px 2px;
    }}
    QWidget[compactPresentation="true"] QWidget[compactStructural="true"],
    QWidget[compactPresentation="true"] QFrame[compactStructural="true"],
    QWidget[compactPresentation="true"] QGroupBox[compactStructural="true"] {{
        background: transparent;
        border: none;
        border-radius: 0px;
        margin-top: 0px;
        padding-top: 0px;
    }}
    QWidget[compactPresentation="true"] QToolButton#SectionToggle {{
        background: transparent;
        color: {theme["text_strong"]};
        border: none;
        border-radius: 0px;
        text-align: left;
        font-weight: 600;
    }}
    QWidget[compactPresentation="true"] QToolButton#SectionToggle:hover {{
        background: {theme["button_hover"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#SectionToggle:checked {{
        background: {theme["surface_alt"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#EditorToolButton {{
        background: transparent;
        border: none;
        border-radius: 0px;
        text-align: left;
    }}
    QWidget[compactPresentation="true"] QToolButton#EditorToolButton:hover {{
        background: {theme["button_hover"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#EditorToolButton:checked {{
        background: {theme["accent_soft"]};
        color: {theme["text_strong"]};
        border: none;
        border-left: 2px solid {theme["accent"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#EditorToolButton:checked:hover {{
        background: {theme["accent"]};
        color: {theme["accent_text"]};
    }}
    QWidget[compactPresentation="true"] QToolButton[effectChip="true"],
    QWidget[compactPresentation="true"] QLineEdit,
    QWidget[compactPresentation="true"] QTextEdit,
    QWidget[compactPresentation="true"] QPlainTextEdit,
    QWidget[compactPresentation="true"] QTextBrowser,
    QWidget[compactPresentation="true"] QComboBox,
    QWidget[compactPresentation="true"] QSpinBox,
    QWidget[compactPresentation="true"] QDoubleSpinBox,
    QWidget[compactPresentation="true"] QListWidget,
    QWidget[compactPresentation="true"] QListView,
    QWidget[compactPresentation="true"] QTreeWidget,
    QWidget[compactPresentation="true"] QTreeView,
    QWidget[compactPresentation="true"] QTableView,
    QWidget[compactPresentation="true"] QTableWidget,
    QWidget[compactPresentation="true"] QScrollArea,
    QWidget[compactPresentation="true"] QGraphicsView,
    QWidget[compactPresentation="true"] QCheckBox::indicator,
    QWidget[compactPresentation="true"] QProgressBar,
    QWidget[compactPresentation="true"] QProgressBar::chunk,
    QWidget[compactPresentation="true"] QListWidget::item,
    QWidget[compactPresentation="true"] QTreeWidget::item,
    QWidget[compactPresentation="true"] QLabel#PreviewLabel,
    QWidget[compactPresentation="true"] QLabel#DdsFlowChip,
    QWidget[compactPresentation="true"] QLabel#DdsFlowValue,
    QWidget[compactPresentation="true"] QLabel#GuidanceChip,
    QWidget[compactPresentation="true"] QLabel#GuidanceValue,
    QWidget[compactPresentation="true"] QLabel#SettingsPerformanceOverview,
    QWidget[compactPresentation="true"] QLabel#ArchivePreviewHealthLabel[attention="true"],
    QWidget[compactPresentation="true"] QLabel#WarningBadge {{
        border-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QTabWidget::pane {{
        border: none;
        border-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QTabBar::tab {{
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QScrollBar:vertical,
    QWidget[compactPresentation="true"] QScrollBar:horizontal,
    QWidget[compactPresentation="true"] QScrollBar::handle:vertical,
    QWidget[compactPresentation="true"] QScrollBar::handle:horizontal,
    QWidget[compactPresentation="true"] QScrollBar::add-page,
    QWidget[compactPresentation="true"] QScrollBar::sub-page {{
        border-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QListWidget#SettingsSectionNav,
    QWidget[compactPresentation="true"] QListWidget#SettingsSectionNav::item {{
        border-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QFrame#WorkflowProfilePanel[profileRole="identity"] {{
        border-left: 3px solid #38bdf8;
    }}
    QWidget[compactPresentation="true"] QFrame#WorkflowProfilePanel[profileRole="dds"] {{
        border-left: 3px solid #22c55e;
    }}
    QWidget[compactPresentation="true"] QFrame#WorkflowProfilePanel[profileRole="ncnn"] {{
        border-left: 3px solid #a78bfa;
    }}
    QWidget[compactPresentation="true"] QFrame#WorkflowProfilePanel[profileRole="correction"] {{
        border-left: 3px solid #f59e0b;
    }}
    QWidget[compactPresentation="true"] QFrame#GuidanceRow[guidanceRole="warning"],
    QWidget[compactPresentation="true"] QFrame#GuidanceRow[guidanceRole="override"] {{
        background: {theme["warning_bg"]};
        border: 1px solid {theme["warning_border"]};
        border-radius: 0px;
    }}
    """
def _compact_workspace_stylesheet(theme: Dict[str, str]) -> str:
    return f"""
    {_compact_tool_shape_override_stylesheet(theme)}
    QWidget[compactPresentation="true"] QToolButton#SectionToggle {{
        padding: 4px 2px;
    }}
    QWidget[compactPresentation="true"] QToolButton#EditorToolButton {{
        padding: 3px 4px;
    }}
    QWidget[compactPresentation="true"] QPushButton {{
        border-radius: 0px;
        padding: 3px 4px;
        min-height: 16px;
    }}
    QWidget[compactPresentation="true"] QToolButton {{
        border-radius: 0px;
        padding: 2px 4px;
    }}
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveSelectButton,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton {{
        background: {theme["button"]};
        color: {theme["text"]};
        border: 1px solid {theme["button_border"]};
        border-radius: 0px;
        padding: 3px 8px;
        min-height: 20px;
    }}
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton {{
        padding-right: 18px;
    }}
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveSelectButton:hover:enabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton:hover:enabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton:hover:enabled {{
        background: {theme["button_hover"]};
        border-color: {theme["accent"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveSelectButton:pressed:enabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton:pressed:enabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton:pressed:enabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton:open:enabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton:open:enabled {{
        background: {theme["accent_soft"]};
        color: {theme["text_strong"]};
        border-color: {theme["accent"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveSelectButton:focus,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton:focus,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton:focus {{
        outline: none;
        border-color: {theme["accent"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveSelectButton:disabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton:disabled,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton:disabled {{
        color: {theme["button_disabled_text"]};
        background: {theme["button_disabled"]};
        border-color: {theme["border"]};
    }}
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveActionsButton::menu-indicator,
    QWidget[compactPresentation="true"] QToolButton#CompactArchiveMoreFiltersButton::menu-indicator {{
        subcontrol-position: right center;
        right: 5px;
    }}
    QWidget[compactPresentation="true"] QLineEdit,
    QWidget[compactPresentation="true"] QTextEdit,
    QWidget[compactPresentation="true"] QPlainTextEdit,
    QWidget[compactPresentation="true"] QTextBrowser,
    QWidget[compactPresentation="true"] QComboBox,
    QWidget[compactPresentation="true"] QSpinBox,
    QWidget[compactPresentation="true"] QDoubleSpinBox {{
        border-radius: 0px;
        padding: 3px 6px;
    }}
    QWidget[compactPresentation="true"] QListWidget,
    QWidget[compactPresentation="true"] QListView,
    QWidget[compactPresentation="true"] QTreeWidget,
    QWidget[compactPresentation="true"] QTreeView,
    QWidget[compactPresentation="true"] QTableView,
    QWidget[compactPresentation="true"] QTableWidget,
    QWidget[compactPresentation="true"] QScrollArea,
    QWidget[compactPresentation="true"] QGraphicsView {{
        border-radius: 0px;
        padding: 1px;
    }}
    QWidget[compactPresentation="true"] QCheckBox {{
        spacing: 6px;
    }}
    QWidget[compactPresentation="true"] QCheckBox::indicator,
    QWidget[compactPresentation="true"] QProgressBar,
    QWidget[compactPresentation="true"] QProgressBar::chunk {{
        border-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QTabWidget::pane {{
        border: none;
        border-radius: 0px;
    }}
    QWidget[compactPresentation="true"] QTabBar::tab {{
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
        padding: 4px 8px 5px 8px;
        min-height: 16px;
    }}
    QWidget[compactPresentation="true"] QListWidget#SettingsSectionNav {{
        background: {theme["surface_alt"]};
        border: none;
        border-right: 1px solid {theme["border"]};
        border-radius: 0px;
        padding: 4px 3px;
    }}
    QWidget[compactPresentation="true"] QListWidget#SettingsSectionNav::item {{
        border-radius: 0px;
        margin: 0px;
        padding: 4px 7px;
    }}
    """
