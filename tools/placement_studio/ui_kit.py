"""The building blocks every Placement & Animations tab is laid out with.

The tabs follow Create New Item's inspector layout: titled header bars that fold, muted
captions beside their fields, and one main action pinned under the scrolling part. Colours
come from the app theme's own object names (`SectionToggle`, `EditorToolButton`,
`EditorPrimaryButton`, `HintLabel`), so the tab follows every theme the app has.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

#: Width of the caption column in a section's form, as in Create New Item's inspector.
CAPTION_WIDTH = 92


def caption(text: str) -> QLabel:
    """A muted field caption."""

    label = QLabel(text)
    label.setObjectName("HintLabel")
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return label


def hint(text: str) -> QLabel:
    """One short muted line. Longer explanations belong in tooltips and the manual."""

    label = QLabel(text)
    label.setObjectName("HintLabel")
    label.setWordWrap(True)
    return label


def primary(text: str, tooltip: str = "") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("EditorPrimaryButton")
    if tooltip:
        button.setToolTip(tooltip)
    return button


def tool(text: str, tooltip: str = "", *, checkable: bool = False) -> QToolButton:
    button = QToolButton()
    button.setObjectName("EditorToolButton")
    button.setText(text)
    button.setCheckable(checkable)
    button.setToolButtonStyle(Qt.ToolButtonTextOnly)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def row(*widgets, stretch: bool = True, spacing: int = 4) -> QWidget:
    """Widgets side by side; `None` adds stretch at that point."""

    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            layout.addStretch(1)
        elif isinstance(widget, QLayout):
            layout.addLayout(widget)
        else:
            layout.addWidget(widget)
    if stretch and widgets and widgets[-1] is not None:
        layout.addStretch(1)
    return holder


class Form(QWidget):
    """Caption on the left, field on the right, one row each."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnMinimumWidth(0, CAPTION_WIDTH)
        self._grid.setColumnStretch(1, 1)
        self._rows = 0

    def add(self, label: str, field, *, tooltip: str = "") -> QLabel:
        text = caption(label)
        if tooltip:
            text.setToolTip(tooltip)
        self._grid.addWidget(text, self._rows, 0, Qt.AlignLeft | Qt.AlignVCenter)
        if isinstance(field, QLayout):
            self._grid.addLayout(field, self._rows, 1)
        else:
            self._grid.addWidget(field, self._rows, 1)
        self._rows += 1
        return text

    def add_wide(self, widget: QWidget) -> None:
        """A row without a caption: a note, a table, a button row."""

        self._grid.addWidget(widget, self._rows, 0, 1, 2)
        self._rows += 1


class Section(QWidget):
    """A header bar that folds its body away."""

    toggled = Signal(bool)

    def __init__(self, title: str, body: Optional[QWidget] = None, *, expanded: bool = True,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._title = title
        self.header = QToolButton()
        self.header.setObjectName("SectionToggle")
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.toggled.connect(self._on_toggled)
        layout.addWidget(self.header)
        self.body = QWidget()
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(10, 8, 6, 10)
        self._body_layout.setSpacing(6)
        layout.addWidget(self.body)
        if body is not None:
            self.add(body)
        self._sync()

    def add(self, widget) -> None:
        if isinstance(widget, QLayout):
            self._body_layout.addLayout(widget)
        else:
            self._body_layout.addWidget(widget)

    def set_title(self, title: str) -> None:
        self._title = title
        self._sync()

    def title(self) -> str:
        return self._title

    def expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        self._sync()
        self.toggled.emit(expanded)

    def _sync(self) -> None:
        expanded = self.header.isChecked()
        self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.header.setText(self._title)
        self.body.setVisible(expanded)


class Segmented(QWidget):
    """A few exclusive choices, shown together. `value()` is the checked one's data."""

    changed = Signal(str)

    def __init__(self, options: Sequence[Tuple[str, str, str]], *, value: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: Dict[str, QToolButton] = {}
        for data, label, tooltip in options:
            button = tool(label, tooltip, checkable=True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked=False, v=data: self.changed.emit(v))
            self._group.addButton(button)
            self.buttons[data] = button
            layout.addWidget(button)
        if options:
            self.set_value(value or options[0][0])

    def value(self) -> str:
        return next((data for data, button in self.buttons.items() if button.isChecked()), "")

    def set_value(self, value: str) -> None:
        button = self.buttons.get(value)
        if button is not None and not button.isChecked():
            button.blockSignals(True)
            button.setChecked(True)
            button.blockSignals(False)


class InspectorPage(QWidget):
    """Sections that scroll, and an optional footer pinned below them.

    Only vertical scrolling: a field that does not fit wraps or elides instead of pushing the
    whole page sideways, which is what made the old tabs scroll horizontally.
    """

    def __init__(self, parent: Optional[QWidget] = None, *, top: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        if top is not None:
            outer.addWidget(top)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._content = QVBoxLayout(content)
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(2)
        self._content.addStretch(1)
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll, 1)
        self._footer_holder = QFrame()
        self._footer_holder.setFrameShape(QFrame.NoFrame)
        self._footer_layout = QVBoxLayout(self._footer_holder)
        self._footer_layout.setContentsMargins(10, 8, 10, 8)
        self._footer_holder.setVisible(False)
        rule = QFrame()
        rule.setFrameShape(QFrame.HLine)
        rule.setFrameShadow(QFrame.Sunken)
        self._rule = rule
        rule.setVisible(False)
        outer.addWidget(rule)
        outer.addWidget(self._footer_holder)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._content.insertWidget(self._content.count() - 1, widget, stretch)
        return widget

    def set_fill(self, widget: QWidget) -> None:
        """Let one widget take the spare height instead of the closing stretch."""

        last = self._content.itemAt(self._content.count() - 1)
        if last is not None and last.spacerItem() is not None:
            self._content.removeItem(last)
        self._content.addWidget(widget, 1)

    def set_footer(self, widget: QWidget) -> None:
        self._footer_layout.addWidget(widget)
        self._footer_holder.setVisible(True)
        self._rule.setVisible(True)


def checkbox_menu(text: str, boxes, tooltip: str = "") -> QToolButton:
    """A dropdown of checkable entries that mirror `boxes`, which stay the record and hide.

    Code that reads or sets the check boxes keeps working; a row of them no longer has to fit
    the panel's width.
    """

    from PySide6.QtWidgets import QMenu

    button = tool(text, tooltip)
    button.setPopupMode(QToolButton.InstantPopup)
    menu = QMenu(button)
    menu.setToolTipsVisible(True)
    for box in boxes:
        action = menu.addAction(box.text())
        action.setCheckable(True)
        action.setChecked(box.isChecked())
        action.setToolTip(box.toolTip())
        action.toggled.connect(box.setChecked)
        box.toggled.connect(action.setChecked)
        box.setVisible(False)
    button.setMenu(menu)
    return button


def section_from_group(box, title: str = "", *, expanded: bool = True) -> Section:
    """Fold an existing `QGroupBox` into a header-bar section, keeping its controls.

    The group's own title becomes the header (any `1. ` style step number dropped), and the box
    is drawn bare inside the section so the two frames do not stack.
    """

    import re

    text = title or re.sub(r"^\s*\d+\.\s*", "", box.title())
    box.setTitle("")
    box.setFlat(True)
    box.setStyleSheet("QGroupBox { border: 0; margin: 0; padding: 0; background: transparent; }")
    if box.layout() is not None:
        box.layout().setContentsMargins(0, 0, 0, 0)
    section = Section(text, box, expanded=expanded)
    # The group's explanation goes on the header only, so it does not pop up over every field.
    section.header.setToolTip(box.toolTip())
    box.setToolTip("")
    return section


def sections_of(page: InspectorPage) -> Iterable[Section]:
    return page.findChildren(Section)


def connect_once(signal, slot: Callable) -> None:
    """Connect without stacking duplicate connections across rebuilds."""

    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):
        pass
    signal.connect(slot)
