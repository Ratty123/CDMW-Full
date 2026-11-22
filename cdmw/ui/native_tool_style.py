"""Shared native workbench surface styling."""
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Dict

_CHEVRON_CACHE: dict[str, str] = {}
_SPLITTER_LINE_CACHE: dict[tuple[str, int, int, int], str] = {}


def _solid_rgba_png_bytes(width: int, height: int, r: int, g: int, b: int, a: int) -> bytes:
    """Encode a tiny solid-color RGBA PNG without invoking Qt/SVG at repaint time."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    row = b"\x00" + bytes((r, g, b, a)) * width
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def _hex_to_rgb(color_hex: str, fallback: tuple[int, int, int] = (128, 128, 128)) -> tuple[int, int, int]:
    raw = str(color_hex or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return fallback
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return fallback


def _rgba_css(color_hex: str, alpha: int) -> str:
    r, g, b = _hex_to_rgb(color_hex)
    return f"rgba({r}, {g}, {b}, {max(0, min(255, int(alpha)))})"


def _is_light_hex(color_hex: str) -> bool:
    r, g, b = _hex_to_rgb(color_hex, (24, 24, 24))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) >= 145.0


def _chevron_svg_url(color_hex: str) -> str:
    color = str(color_hex or "#9ca3af").strip()
    cached = _CHEVRON_CACHE.get(color)
    if cached and Path(cached).exists():
        return Path(cached).as_posix()
    tag = "".join(ch for ch in color if ch.isalnum()) or "default"
    folder = Path(tempfile.gettempdir()) / "cdmw_qss_icons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"chevron_down_{tag}.svg"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 8">'
        f'<path d="M2 2.2 L6 6.2 L10 2.2" fill="none" stroke="{color}" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        f"</svg>"
    )
    if not path.exists() or path.read_text(encoding="utf-8") != svg:
        path.write_text(svg, encoding="utf-8")
    _CHEVRON_CACHE[color] = str(path)
    return path.as_posix()


def _splitter_line_png_url(
    color_hex: str,
    *,
    width: int,
    height: int,
    opacity_pct: int = 100,
) -> str:
    color = str(color_hex or "#4b5563").strip()
    pct = max(0, min(100, int(opacity_pct)))
    key = (color, int(width), int(height), pct)
    cached = _SPLITTER_LINE_CACHE.get(key)
    if cached and Path(cached).exists():
        return Path(cached).as_posix()
    tag = "".join(ch for ch in color if ch.isalnum()) or "default"
    folder = Path(tempfile.gettempdir()) / "cdmw_qss_icons"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"splitter_{width}x{height}_{tag}_{pct}.png"
        r, g, b = _hex_to_rgb(color)
        alpha = max(0, min(255, int(round(255 * pct / 100.0))))
        png = _solid_rgba_png_bytes(int(width), int(height), r, g, b, alpha)
        if not path.exists() or path.read_bytes() != png:
            path.write_bytes(png)
    except OSError:
        return ""
    _SPLITTER_LINE_CACHE[key] = str(path)
    return path.as_posix()


def _bg_image_rule(url: str, repeat: str) -> str:
    if not url:
        return ""
    return f"background-image: url({url}); background-repeat: {repeat}; background-position: center;"

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
        background: {surface};
        border: 1px solid {border};
        border-radius: 6px;
        margin-top: 0px;
        padding: 22px 6px 6px 6px;
        font-weight: 400;
    }}
    QGroupBox::title {{
        subcontrol-origin: padding;
        subcontrol-position: top left;
        left: 8px;
        top: 5px;
        margin: 0px;
        padding: 0px 2px;
        color: {text_muted};
        background: transparent;
        font-weight: 600;
    }}
    QWidget[compactStructural="true"],
    QFrame[compactStructural="true"],
    QGroupBox[compactStructural="true"] {{
        background: transparent;
        border: none;
        border-radius: 0px;
        margin-top: 0px;
        padding: 0px;
    }}
    QFrame#CompactNavigationColumn {{
        background: {field_alt};
        border: none;
        border-right: 1px solid {border};
    }}
    QFrame#CompactBottomStatusStrip {{
        background: {surface};
        border: none;
        border-top: 1px solid {border};
        border-radius: 0px;
    }}
    QPushButton#CompactActivityToggle {{
        background: transparent;
        color: {text};
        border: 1px solid transparent;
        border-radius: 4px;
        padding: 2px 8px;
        min-height: 18px;
        font-weight: 400;
    }}
    QPushButton#CompactActivityToggle:hover:enabled {{
        background: {button_hover};
        border-color: {border};
        color: {text_strong};
    }}
    QPushButton#CompactActivityToggle:checked {{
        background: {accent_soft};
        color: {text_strong};
        border: 1px solid {accent};
        padding: 2px 8px;
        min-height: 18px;
        font-weight: 600;
    }}
    QPushButton#CompactActivityToggle:checked:hover {{
        background: {accent_soft};
        color: {text_strong};
        border-color: {accent};
    }}
    QFrame#CompactActivityDrawer {{
        background: {field_alt};
        border: none;
        border-top: 1px solid {border};
        border-radius: 0px;
    }}
    QLabel#CompactDrawerTitle,
    QLabel#SectionHeader {{
        color: {text_strong};
        font-weight: 600;
        background: transparent;
    }}
    QFrame[surfaceCard="true"],
    QFrame[commandBar="true"],
    QFrame[footerBar="true"],
    QFrame#CompactArchiveCommandStrip {{
        background: {surface};
        border: 1px solid {border};
        border-radius: 6px;
    }}
    QFrame[highlightRow="true"] {{
        background: {field_alt};
        border: 1px solid {border};
        border-radius: 4px;
    }}
    QToolButton#SectionToggle {{
        background: transparent;
        color: {text_strong};
        border: none;
        border-radius: 4px;
        text-align: left;
        font-weight: 600;
        padding: 4px 4px;
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
        border-radius: 4px;
        text-align: left;
        padding: 3px 6px;
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
    QToolButton,
    QToolButton[effectChip="true"] {{
        border-radius: 4px;
        padding: 3px 6px;
    }}
    QToolButton#CompactArchiveSelectButton,
    QToolButton#CompactArchiveActionsButton,
    QToolButton#CompactArchiveMoreFiltersButton {{
        background: {button};
        color: {text};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 4px 10px;
        min-height: 22px;
        font-weight: 400;
    }}
    QToolButton#CompactArchiveActionsButton,
    QToolButton#CompactArchiveMoreFiltersButton {{
        padding-right: 20px;
    }}
    QToolButton#CompactArchiveSelectButton:hover:enabled,
    QToolButton#CompactArchiveActionsButton:hover:enabled,
    QToolButton#CompactArchiveMoreFiltersButton:hover:enabled {{
        background: {button_hover};
        border-color: {border_strong};
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
        right: 6px;
    }}
    QPushButton,
    QFrame#MeshEditorEntryBar QPushButton,
    QFrame#MeshEditorDraftChoiceCard QPushButton,
    QPushButton#MeshEditorHairMenu {{
        background: {button};
        color: {text};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 4px 10px;
        min-height: 22px;
        font-weight: 400;
    }}
    QPushButton:hover:enabled,
    QFrame#MeshEditorEntryBar QPushButton:hover:enabled,
    QFrame#MeshEditorDraftChoiceCard QPushButton:hover:enabled,
    QPushButton#MeshEditorHairMenu:hover:enabled {{
        background: {button_hover};
        border-color: {border_strong};
    }}
    QPushButton:pressed:enabled,
    QFrame#MeshEditorEntryBar QPushButton:pressed:enabled,
    QFrame#MeshEditorDraftChoiceCard QPushButton:pressed:enabled,
    QPushButton#MeshEditorHairMenu:pressed:enabled {{
        background: {button_pressed};
    }}
    QPushButton:checked {{
        color: {accent_text};
        background: {accent};
        border-color: {accent};
        padding: 4px 10px;
        min-height: 22px;
        font-weight: 400;
    }}
    QPushButton:checked:hover {{
        color: {text_strong};
        background: {accent_soft};
        border-color: {accent};
    }}
    /* Create New Item's effect toolbar keeps its eight icon buttons on one row. */
    QPushButton[effectToolbarButton="true"],
    QPushButton[effectToolbarButton="true"]:checked {{
        padding: 3px 5px;
    }}
    QPushButton#EditorPrimaryButton,
    QPushButton[primaryAction="true"] {{
        color: {accent_text};
        background: {accent};
        border-color: {accent};
        padding: 4px 10px;
        min-height: 22px;
        /* Regular weight: CDMW sets each widget's font itself, so a heavier style sheet
           weight is painted but not measured, and the text overruns the button. */
        font-weight: 400;
    }}
    QPushButton#EditorPrimaryButton:hover:enabled,
    QPushButton[primaryAction="true"]:hover:enabled {{
        color: {text_strong};
        background: {accent_soft};
        border-color: {accent};
    }}
    QPushButton:disabled,
    QPushButton#EditorPrimaryButton:disabled,
    QPushButton[primaryAction="true"]:disabled {{
        color: {button_disabled_text};
        background: {button_disabled};
        border-color: {border};
    }}
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QTextBrowser,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox {{
        background: {field};
        border: 1px solid {border};
        border-radius: 4px;
        padding: 5px 8px;
    }}
    QComboBox {{
        padding: 5px 24px 5px 8px;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 22px;
        border: none;
    }}
    QComboBox::down-arrow {{
        image: url({combo_chevron});
        width: 10px;
        height: 7px;
        border: none;
        margin-right: 4px;
    }}
    QComboBox::down-arrow:disabled {{
        image: url({combo_chevron_disabled});
    }}
    QLineEdit:hover,
    QTextEdit:hover,
    QPlainTextEdit:hover,
    QTextBrowser:hover,
    QComboBox:hover,
    QSpinBox:hover,
    QDoubleSpinBox:hover {{
        border-color: {border_strong};
    }}
    QLineEdit:focus,
    QTextEdit:focus,
    QPlainTextEdit:focus,
    QTextBrowser:focus,
    QComboBox:focus,
    QSpinBox:focus,
    QDoubleSpinBox:focus,
    QAbstractSpinBox[cleanField="true"]:focus {{
        border-color: {accent};
    }}
    QAbstractSpinBox[cleanField="true"] {{
        padding: 3px 8px;
    }}
    QAbstractSpinBox[cleanField="true"][inCell="true"] {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
        margin: 0px 4px;
    }}
    QAbstractSpinBox[cleanField="true"][inCell="true"]:hover {{
        border: 1px solid {border_strong};
        background: {field};
    }}
    QAbstractSpinBox[cleanField="true"][inCell="true"]:focus {{
        border: 1px solid {accent};
        background: {field};
    }}
    QListWidget,
    QListView,
    QTreeWidget,
    QTreeView,
    QTableView,
    QTableWidget {{
        background: {field};
        border: 1px solid {border};
        border-radius: 6px;
        padding: 2px;
        outline: 0;
    }}
    QListWidget,
    QListView,
    QTreeWidget,
    QTreeView[cdmwUnifiedList="true"],
    QTableView,
    QTableWidget {{
        gridline-color: transparent;
        show-decoration-selected: 1;
        selection-background-color: {accent_soft};
        selection-color: {text_strong};
    }}
    QFrame[surfaceCard="true"] QListWidget,
    QFrame[surfaceCard="true"] QListView,
    QFrame[surfaceCard="true"] QTreeWidget,
    QFrame[surfaceCard="true"] QTreeView[cdmwUnifiedList="true"],
    QFrame[surfaceCard="true"] QTableView,
    QFrame[surfaceCard="true"] QTableWidget {{
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 0px;
    }}
    QListWidget:focus,
    QListView:focus,
    QTreeWidget:focus,
    QTreeView:focus,
    QTableView:focus,
    QTableWidget:focus {{
        border-color: {border_strong};
    }}
    QListWidget::item,
    QListView::item,
    QTreeWidget::item,
    QTreeView[cdmwUnifiedList="true"]::item,
    QTableView::item,
    QTableWidget::item {{
        padding: 5px 10px;
    }}
    QListWidget::item:hover:!selected,
    QListView::item:hover:!selected,
    QTreeWidget::item:hover:!selected,
    QTreeView[cdmwUnifiedList="true"]::item:hover:!selected,
    QTreeWidget::branch:hover:!selected,
    QTreeView[cdmwUnifiedList="true"]::branch:hover:!selected {{
        background: {button_hover};
    }}
    QListWidget::item:selected:active,
    QListView::item:selected:active,
    QTreeWidget::item:selected:active,
    QTreeView[cdmwUnifiedList="true"]::item:selected:active,
    QTableView::item:selected:active,
    QTableWidget::item:selected:active,
    QTreeWidget::branch:selected:active,
    QTreeView[cdmwUnifiedList="true"]::branch:selected:active {{
        background: {accent_soft};
        color: {text_strong};
    }}
    QListWidget::item:selected:!active,
    QListView::item:selected:!active,
    QTreeWidget::item:selected:!active,
    QTreeView[cdmwUnifiedList="true"]::item:selected:!active,
    QTableView::item:selected:!active,
    QTableWidget::item:selected:!active,
    QTreeWidget::branch:selected:!active,
    QTreeView[cdmwUnifiedList="true"]::branch:selected:!active {{
        background: {selection_inactive};
        color: {text_strong};
    }}
    QTreeWidget#MeshEditorTexturesTree::item {{
        padding: 2px 6px;
    }}
    QHeaderView::section {{
        background: {surface};
        color: {text_muted};
        border: none;
        border-bottom: 1px solid {border};
        padding: 6px 10px;
        font-weight: 600;
    }}
    QTableView QHeaderView,
    QTreeWidget QHeaderView,
    QTreeView[cdmwUnifiedList="true"] QHeaderView {{
        background: transparent;
        border: none;
    }}
    QTableView QHeaderView::section,
    QTreeWidget QHeaderView::section,
    QTreeView[cdmwUnifiedList="true"] QHeaderView::section {{
        background: transparent;
        color: {text_muted};
        border: none;
        border-bottom: 1px solid {border};
        padding: 6px 10px;
        font-weight: 500;
        text-align: left;
    }}
    QTableView QHeaderView::section:hover,
    QTreeWidget QHeaderView::section:hover,
    QTreeView[cdmwUnifiedList="true"] QHeaderView::section:hover {{
        background: {button_hover};
        color: {text_strong};
    }}
    QTableCornerButton::section {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {border};
    }}
    QTableView QAbstractSpinBox[cleanField="true"][inCell="true"] {{
        background: {field};
        color: {text};
        border: 1px solid {border};
        border-radius: 4px;
    }}
    QScrollArea {{
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 0px;
    }}
    QAbstractScrollArea::corner,
    QWidget#qt_scrollarea_hcontainer,
    QWidget#qt_scrollarea_vcontainer {{
        background: transparent;
        border: none;
    }}
    QGraphicsView {{
        border-radius: 6px;
        padding: 1px;
    }}
    QSplitter::handle {{
        background: transparent;
        border: none;
        image: none;
    }}
    QSplitter::handle:horizontal {{
        width: 5px;
        {splitter_h_idle}
    }}
    QSplitter::handle:vertical {{
        height: 5px;
        {splitter_v_idle}
    }}
    QSplitter::handle:horizontal:hover,
    QSplitter::handle:horizontal:pressed {{
        {splitter_h_hover}
    }}
    QSplitter::handle:vertical:hover,
    QSplitter::handle:vertical:pressed {{
        {splitter_v_hover}
    }}
    QCheckBox {{
        spacing: 6px;
    }}
    QCheckBox::indicator,
    QProgressBar,
    QProgressBar::chunk {{
        border-radius: 3px;
    }}
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {border};
        border-radius: 0px;
        background: transparent;
        margin-top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {text_muted};
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0px;
        padding: 7px 14px;
        margin-right: 4px;
        font-weight: 500;
    }}
    QTabBar::tab:hover:!selected {{
        color: {text_strong};
        background: {surface};
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }}
    QTabBar::tab:selected {{
        color: {text_strong};
        background: transparent;
        border-bottom: 2px solid {accent};
        font-weight: 600;
    }}
    QScrollBar:vertical {{
        background: transparent;
        border: none;
        border-radius: 0px;
        width: 8px;
        margin: 2px 1px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        border: none;
        border-radius: 0px;
        height: 8px;
        margin: 1px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {scrollbar_handle};
        border: none;
        border-radius: 3px;
        min-height: 28px;
    }}
    QScrollBar::handle:horizontal {{
        background: {scrollbar_handle};
        border: none;
        border-radius: 3px;
        min-width: 28px;
    }}
    QScrollBar::handle:vertical:hover,
    QScrollBar::handle:horizontal:hover {{
        background: {border_strong};
        border: none;
    }}
    QScrollBar::handle:vertical:pressed,
    QScrollBar::handle:horizontal:pressed {{
        background: {accent};
        border: none;
    }}
    QScrollBar::add-line,
    QScrollBar::sub-line {{
        background: transparent;
        border: none;
        width: 0px;
        height: 0px;
    }}
    QScrollBar::add-page,
    QScrollBar::sub-page {{
        background: transparent;
        border: none;
    }}
    QLabel#WarningBadge {{
        border-radius: 4px;
        padding: 2px 7px;
    }}
    QLabel#PreviewLabel,
    QLabel#DdsFlowChip,
    QLabel#DdsFlowValue,
    QLabel#GuidanceChip,
    QLabel#GuidanceValue,
    QLabel#SettingsPerformanceOverview,
    QLabel#ArchivePreviewHealthLabel[attention="true"] {{
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
    QFrame#GuidanceRow[guidanceRole="warning"],
    QFrame#GuidanceRow[guidanceRole="override"] {{
        background: {warning_bg};
        border: 1px solid {warning_border};
        border-radius: 4px;
    }}
    QWidget#SettingsSectionNavPanel {{
        background: {field_alt};
        border: none;
        border-right: 1px solid {border};
    }}
    QListWidget#SettingsSectionNav {{
        background: transparent;
        border: none;
        border-radius: 0px;
        padding: 6px 6px;
    }}
    QListWidget#SettingsSectionNav::item {{
        border-radius: 4px;
        margin: 1px 0px;
        padding: 5px 8px;
    }}
    QListWidget#SettingsSectionNav::item:selected,
    QListWidget#SettingsSectionNav::item:selected:!active {{
        background: {accent_soft};
        border: 1px solid {accent};
        color: {text_strong};
        font-weight: 600;
    }}
    """


def native_tool_stylesheet(theme: Dict[str, str]) -> str:
    params = dict(theme)
    light_theme = _is_light_hex(theme.get("window", "#151719"))
    high_contrast = (
        str(theme.get("window", "")).lower() == "#000000"
        and str(theme.get("border_strong", "")).lower() == "#ffffff"
    )
    border_hex = theme.get("border", "#343b42")
    accent_hex = theme.get("accent", "#e06f3e")
    border_strong_hex = theme.get("border_strong", "#5a626a")

    idle_opacity = 90 if (light_theme or high_contrast) else 72
    line_1x1 = _splitter_line_png_url(border_hex, width=1, height=1, opacity_pct=idle_opacity)
    line_2x1 = _splitter_line_png_url(accent_hex, width=2, height=1, opacity_pct=95)
    line_1x2 = _splitter_line_png_url(accent_hex, width=1, height=2, opacity_pct=95)

    params["splitter_h_idle"] = _bg_image_rule(line_1x1, "repeat-y")
    params["splitter_v_idle"] = _bg_image_rule(line_1x1, "repeat-x")
    params["splitter_h_hover"] = _bg_image_rule(line_2x1, "repeat-y")
    params["splitter_v_hover"] = _bg_image_rule(line_1x2, "repeat-x")
    params["scrollbar_handle"] = _rgba_css(
        border_strong_hex,
        220 if high_contrast else (180 if light_theme else 145),
    )
    params["selection_inactive"] = _rgba_css(
        accent_hex,
        72 if high_contrast else (34 if light_theme else 44),
    )
    params["combo_chevron"] = _chevron_svg_url(theme.get("text_muted", "#9ca3af"))
    params["combo_chevron_disabled"] = _chevron_svg_url(theme.get("button_disabled_text", "#6b7280"))
    return _NATIVE_TOOL_QSS.format_map(params)
