"""Scrollable compact navigation rail with fixed application actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.shell.compact.config import compact_category_expanded_setting
from cdmw.ui.shell.compact.icons import compact_line_icon
from cdmw.ui.shell.compact.registry import (
    COMPACT_CATEGORY_ORDER,
    COMPACT_TOOL_SPECS,
    compact_specs_for_category,
)


def _read_bool(settings: object, key: str, default: bool) -> bool:
    value = settings.value(key, default)  # type: ignore[attr-defined]
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _rgba(color: QColor, alpha: int) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {max(0, min(255, alpha))})"


class CompactCategoryHeader(QToolButton):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompactCategoryHeader")
        self.setProperty("compactCategoryHeader", True)
        self.setText(str(title).upper())
        self.setCheckable(True)
        self.setChecked(True)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(34)
        self.setAccessibleName(f"{title} tools")
        self._refresh_icon()
        self.toggled.connect(lambda _checked: self._refresh_icon())

    def _refresh_icon(self) -> None:
        self.setIcon(
            compact_line_icon(
                "chevron_up" if self.isChecked() else "chevron_down",
                self.palette(),
                size=14,
            )
        )


class CompactWorkspaceRail(QFrame):
    tool_requested = Signal(str)

    def __init__(self, owner: object, settings: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CompactWorkspaceRail")
        self.setFixedWidth(236)
        self._owner = owner
        self._settings = settings
        self._tool_buttons: dict[str, QToolButton] = {}
        self._category_headers: dict[str, CompactCategoryHeader] = {}
        self._category_bodies: dict[str, QWidget] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("CompactToolScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        content.setObjectName("CompactToolRailContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 6, 0, 4)
        content_layout.setSpacing(0)
        for category in COMPACT_CATEGORY_ORDER:
            self._add_category(content_layout, category)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)
        root.addWidget(self._footer(owner))
        self.refresh_palette()

    @property
    def tool_buttons(self) -> dict[str, QToolButton]:
        return dict(self._tool_buttons)

    @property
    def category_headers(self) -> dict[str, CompactCategoryHeader]:
        return dict(self._category_headers)

    def _add_category(self, layout: QVBoxLayout, category: str) -> None:
        header = CompactCategoryHeader(category)
        setting_key = compact_category_expanded_setting(category)
        expanded = _read_bool(self._settings, setting_key, True)
        header.setChecked(expanded)
        layout.addWidget(header)
        body = QWidget()
        body.setObjectName(f"CompactCategory{category}")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 3, 8, 6)
        body_layout.setSpacing(1)
        for spec in compact_specs_for_category(category):
            button = QToolButton()
            button.setObjectName(f"CompactTool_{spec.key}")
            button.setProperty("compactToolRow", True)
            button.setText(spec.label)
            button.setToolTip(spec.label)
            button.setAccessibleName(spec.label)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setFixedHeight(38)
            button.clicked.connect(
                lambda _checked=False, tool_key=spec.key: self.tool_requested.emit(tool_key)
            )
            self._button_group.addButton(button)
            self._tool_buttons[spec.key] = button
            body_layout.addWidget(button)
        body.setVisible(expanded)
        header.toggled.connect(body.setVisible)
        header.toggled.connect(
            lambda checked, key=setting_key: self._save_category_state(key, checked)
        )
        self._category_headers[category] = header
        self._category_bodies[category] = body
        layout.addWidget(body)

    def _save_category_state(self, setting_key: str, expanded: bool) -> None:
        self._settings.setValue(setting_key, bool(expanded))  # type: ignore[attr-defined]
        sync = getattr(self._settings, "sync", None)
        if callable(sync):
            sync()

    def _footer(self, owner: object) -> QWidget:
        footer = QFrame()
        footer.setObjectName("CompactRailFooter")
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(8, 7, 8, 9)
        layout.setSpacing(2)

        self.settings_button = QToolButton()
        self.settings_button.setObjectName("CompactSettingsButton")
        self.settings_button.setProperty("compactFooterRow", True)
        self.settings_button.setDefaultAction(owner.open_settings_action)
        self.settings_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.settings_button.setFocusPolicy(Qt.StrongFocus)
        self.settings_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.settings_button)

        self.help_button = QToolButton()
        self.help_button.setObjectName("CompactHelpButton")
        self.help_button.setProperty("compactFooterRow", True)
        self.help_button.setText("Help")
        self.help_button.setPopupMode(QToolButton.InstantPopup)
        self.help_button.setMenu(owner.help_menu)
        self.help_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.help_button.setFocusPolicy(Qt.StrongFocus)
        self.help_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.help_button)

        self.support_button = owner.support_corner_button
        self.support_button.setObjectName("CompactSupportButton")
        self.support_button.setText("Support Me")
        self.support_button.setMinimumWidth(0)
        self.support_button.setMaximumWidth(16777215)
        self.support_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.support_button)

        self.overflow_button = QToolButton()
        self.overflow_button.setObjectName("CompactOverflowButton")
        self.overflow_button.setProperty("compactFooterRow", True)
        self.overflow_button.setText("More")
        self.overflow_button.setToolTip("Profile, window, diagnostics, and about actions.")
        self.overflow_button.setPopupMode(QToolButton.InstantPopup)
        self.overflow_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.overflow_button.setFocusPolicy(Qt.StrongFocus)
        self.overflow_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        overflow_menu = QMenu(self.overflow_button)
        overflow_menu.addAction(owner.profile_menu.menuAction())
        overflow_menu.addAction(owner.window_menu.menuAction())
        overflow_menu.addSeparator()
        owner.mod_package_tool_action.setText("Repackage Mods")
        overflow_menu.addAction(owner.mod_package_tool_action)
        overflow_menu.addAction(owner.export_diagnostics_action)
        overflow_menu.addSeparator()
        overflow_menu.addAction(owner.open_about_action)
        self.overflow_button.setMenu(overflow_menu)
        self.overflow_menu = overflow_menu
        layout.addWidget(self.overflow_button)
        return footer

    def set_active_tool(self, tool_key: str) -> None:
        button = self._tool_buttons.get(str(tool_key or ""))
        if button is None:
            self._button_group.setExclusive(False)
            for candidate in self._tool_buttons.values():
                candidate.setChecked(False)
            self._button_group.setExclusive(True)
            return
        if not button.isChecked():
            button.setChecked(True)
    def refresh_palette(self) -> None:
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.ButtonText)
        base = palette.color(QPalette.ColorRole.Window)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        disabled = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
        self.setStyleSheet(
            "QFrame#CompactWorkspaceRail { border-right: 1px solid %s; }"
            "QToolButton[compactCategoryHeader=\"true\"] { text-align: left; padding: 4px 9px; border: 0; border-left: 2px solid %s; background: %s; }"
            "QToolButton[compactCategoryHeader=\"true\"]:hover { background: %s; }"
            "QToolButton[compactCategoryHeader=\"true\"]:pressed { background: %s; }"
            "QToolButton[compactCategoryHeader=\"true\"]:focus { outline: none; border: 1px solid %s; border-left: 2px solid %s; }"
            "QToolButton[compactToolRow=\"true\"], QToolButton[compactFooterRow=\"true\"] { text-align: left; padding: 5px 9px; border: 1px solid transparent; border-left: 2px solid transparent; background: transparent; }"
            "QToolButton[compactToolRow=\"true\"]:hover, QToolButton[compactFooterRow=\"true\"]:hover { background: %s; }"
            "QToolButton[compactToolRow=\"true\"]:pressed, QToolButton[compactFooterRow=\"true\"]:pressed { background: %s; }"
            "QToolButton[compactToolRow=\"true\"]:checked { border-left: 2px solid %s; background: %s; }"
            "QToolButton[compactToolRow=\"true\"]:focus, QToolButton[compactFooterRow=\"true\"]:focus { border: 1px solid %s; border-left: 2px solid %s; }"
            "QToolButton[compactToolRow=\"true\"]:disabled, QToolButton[compactFooterRow=\"true\"]:disabled { color: %s; }"
            "QFrame#CompactRailFooter { border-top: 1px solid %s; }"
            % (
                _rgba(text, 45),
                _rgba(highlight, 190),
                _rgba(base.lighter(120), 150),
                _rgba(highlight, 35),
                _rgba(highlight, 65),
                _rgba(highlight, 180),
                _rgba(highlight, 220),
                _rgba(highlight, 32),
                _rgba(highlight, 58),
                highlight.name(),
                _rgba(highlight, 42),
                _rgba(highlight, 180),
                _rgba(highlight, 220),
                disabled.name(),
                _rgba(text, 45),
            )
        )
        for spec in COMPACT_TOOL_SPECS:
            self._tool_buttons[spec.key].setIcon(compact_line_icon(spec.icon, palette))
        for header in self._category_headers.values():
            header._refresh_icon()
        self.settings_button.setIcon(compact_line_icon("mesh", palette))
        self.help_button.setIcon(compact_line_icon("book", palette))
        self.overflow_button.setIcon(compact_line_icon("more", palette))


__all__ = ["CompactCategoryHeader", "CompactWorkspaceRail"]
