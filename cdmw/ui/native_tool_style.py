"""Shared native workbench surface styling."""
from typing import Dict

_NATIVE_TOOL_QSS = """
    QWidget#FlatSectionPanel,
    QWidget#FlatSectionHeader,
    QWidget#EmptyStatePanel,
    QWidget[compactFlatSurface="true"],
    QFrame[compactFlatSurface="true"],
    QGroupBox[compactFlatSurface="true"],
    QFrame#FlatSectionBody,
    QFrame#SectionBody,
    QFrame#WorkflowProfilePanel,
    QFrame#DdsFlowPanel,
    QFrame#DdsFlowRow,
    QFrame#GuidancePanel,
    QFrame#GuidanceRow,
    QFrame#EditorSectionBody,
    QFrame#EditorActionPane,
    QWidget#EditorLeftSidebar,
    QWidget#EditorInspectorSidebar,
    QWidget#EditorCanvasPane {{
        background: transparent;
        border: none;
        border-radius: 0px;
    }}
    QGroupBox {{
        background: transparent;
        border: none;
        border-radius: 0px;
        margin-top: 10px;
        padding-top: 4px;
    }}
    QGroupBox::title {{
        left: 2px;
        top: 0px;
        margin: 0px;
        padding: 0px 2px;
    }}
    QWidget[compactStructural="true"],
    QFrame[compactStructural="true"],
    QGroupBox[compactStructural="true"] {{
        background: transparent;
        border: none;
        border-radius: 0px;
        margin-top: 0px;
        padding-top: 0px;
    }}
    QToolButton#SectionToggle {{
        background: transparent;
        color: {text_strong};
        border: none;
        border-radius: 0px;
        text-align: left;
        font-weight: 600;
    }}
    QToolButton#SectionToggle:hover {{
        background: {button_hover};
    }}
    QToolButton#SectionToggle:checked {{
        background: {surface_alt};
    }}
    QToolButton#EditorToolButton {{
        background: transparent;
        border: none;
        border-radius: 0px;
        text-align: left;
    }}
    QToolButton#EditorToolButton:hover {{
        background: {button_hover};
    }}
    QToolButton#EditorToolButton:checked {{
        background: {accent_soft};
        color: {text_strong};
        border: none;
        border-left: 2px solid {accent};
    }}
    QToolButton#EditorToolButton:checked:hover {{
        background: {accent};
        color: {accent_text};
    }}
    QToolButton[effectChip="true"],
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QTextBrowser,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QListWidget,
    QListView,
    QTreeWidget,
    QTreeView,
    QTableView,
    QTableWidget,
    QScrollArea,
    QGraphicsView,
    QCheckBox::indicator,
    QProgressBar,
    QProgressBar::chunk,
    QListWidget::item,
    QTreeWidget::item,
    QLabel#PreviewLabel,
    QLabel#DdsFlowChip,
    QLabel#DdsFlowValue,
    QLabel#GuidanceChip,
    QLabel#GuidanceValue,
    QLabel#SettingsPerformanceOverview,
    QLabel#ArchivePreviewHealthLabel[attention="true"],
    QLabel#WarningBadge {{
        border-radius: 0px;
    }}
    QTabWidget::pane {{
        border: none;
        border-radius: 0px;
    }}
    QTabBar::tab {{
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
    }}
    QScrollBar:vertical,
    QScrollBar:horizontal,
    QScrollBar::handle:vertical,
    QScrollBar::handle:horizontal,
    QScrollBar::add-page,
    QScrollBar::sub-page {{
        border-radius: 0px;
    }}
    QListWidget#SettingsSectionNav,
    QListWidget#SettingsSectionNav::item {{
        border-radius: 0px;
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
    QFrame#GuidanceRow[guidanceRole="warning"],
    QFrame#GuidanceRow[guidanceRole="override"] {{
        background: {warning_bg};
        border: 1px solid {warning_border};
        border-radius: 0px;
    }}

    QToolButton#SectionToggle {{
        padding: 4px 2px;
    }}
    QToolButton#EditorToolButton {{
        padding: 3px 4px;
    }}
    QPushButton {{
        border-radius: 0px;
        padding: 3px 4px;
        min-height: 16px;
    }}
    QToolButton {{
        border-radius: 0px;
        padding: 2px 4px;
    }}
    QToolButton#CompactArchiveSelectButton,
    QToolButton#CompactArchiveActionsButton,
    QToolButton#CompactArchiveMoreFiltersButton {{
        background: {button};
        color: {text};
        border: 1px solid {button_border};
        border-radius: 0px;
        padding: 3px 8px;
        min-height: 20px;
    }}
    QToolButton#CompactArchiveActionsButton,
    QToolButton#CompactArchiveMoreFiltersButton {{
        padding-right: 18px;
    }}
    QToolButton#CompactArchiveSelectButton:hover:enabled,
    QToolButton#CompactArchiveActionsButton:hover:enabled,
    QToolButton#CompactArchiveMoreFiltersButton:hover:enabled {{
        background: {button_hover};
        border-color: {accent};
    }}
    QToolButton#CompactArchiveSelectButton:pressed:enabled,
    QToolButton#CompactArchiveActionsButton:pressed:enabled,
    QToolButton#CompactArchiveMoreFiltersButton:pressed:enabled,
    QToolButton#CompactArchiveActionsButton:open:enabled,
    QToolButton#CompactArchiveMoreFiltersButton:open:enabled {{
        background: {accent_soft};
        color: {text_strong};
        border-color: {accent};
    }}
    QToolButton#CompactArchiveSelectButton:focus,
    QToolButton#CompactArchiveActionsButton:focus,
    QToolButton#CompactArchiveMoreFiltersButton:focus {{
        outline: none;
        border-color: {accent};
    }}
    QToolButton#CompactArchiveSelectButton:disabled,
    QToolButton#CompactArchiveActionsButton:disabled,
    QToolButton#CompactArchiveMoreFiltersButton:disabled {{
        color: {button_disabled_text};
        background: {button_disabled};
        border-color: {border};
    }}
    QToolButton#CompactArchiveActionsButton::menu-indicator,
    QToolButton#CompactArchiveMoreFiltersButton::menu-indicator {{
        subcontrol-position: right center;
        right: 5px;
    }}
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QTextBrowser,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox {{
        border-radius: 0px;
        padding: 3px 6px;
    }}
    QListWidget,
    QListView,
    QTreeWidget,
    QTreeView,
    QTableView,
    QTableWidget,
    QScrollArea,
    QGraphicsView {{
        border-radius: 0px;
        padding: 1px;
    }}
    QCheckBox {{
        spacing: 6px;
    }}
    QCheckBox::indicator,
    QProgressBar,
    QProgressBar::chunk {{
        border-radius: 0px;
    }}
    QTabWidget::pane {{
        border: none;
        border-radius: 0px;
    }}
    QTabBar::tab {{
        border-top-left-radius: 0px;
        border-top-right-radius: 0px;
        padding: 4px 8px 5px 8px;
        min-height: 16px;
    }}
    QWidget#SettingsSectionNavPanel {{
        background: {surface_alt};
    }}
    QListWidget#SettingsSectionNav {{
        background: {surface_alt};
        border: none;
        border-right: 1px solid {border};
        border-radius: 0px;
        padding: 4px 3px;
    }}
    QListWidget#SettingsSectionNav::item {{
        border-radius: 0px;
        margin: 0px;
        padding: 4px 7px;
    }}
        """


def native_tool_stylesheet(theme: Dict[str, str]) -> str:
    return _NATIVE_TOOL_QSS.format_map(theme)
