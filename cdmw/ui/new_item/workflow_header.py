"""The compact, keyboard-accessible step header used by New Item workflows.

The header deliberately exposes the small part of :class:`QListWidget`'s API that
the studio uses for its step navigation.  The controls are real Qt buttons rather
than painted hit regions, so mouse, keyboard, focus, tooltip, and accessibility
behaviour all remain available to the host workflow.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Sequence

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget


DEFAULT_STEP_LABELS = (
    "Template",
    "Identity",
    "Model & Icon",
    "Stats & Prices",
    "Perks & Effects",
    "Distribution",
    "Output",
)

ACTIVE_DARK_COLOR = QColor("#078de5")
_CIRCLE_DIAMETER = 32
_HEADER_HEIGHT = 76
_SIDE_PADDING = 16


class WorkflowStepState(str, Enum):
    """Semantic state shown by one guided-workflow step."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"


def _coerce_step_state(value: object) -> Optional[WorkflowStepState]:
    if isinstance(value, WorkflowStepState):
        return value
    normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "current": WorkflowStepState.ACTIVE,
        "done": WorkflowStepState.COMPLETED,
        "error": WorkflowStepState.BLOCKED,
        "invalid": WorkflowStepState.BLOCKED,
    }
    return aliases.get(normalized) or next(
        (state for state in WorkflowStepState if state.value == normalized), None
    )


def _palette_is_dark(palette: QPalette) -> bool:
    """Return whether ``palette`` is predominantly a dark application palette."""

    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    # Looking at both roles handles custom palettes whose window colour is close to
    # middle grey while still keeping the decision deterministic in offscreen tests.
    return window.lightness() < 128 or window.lightness() < text.lightness()


def _palette_color(palette: QPalette, role: QPalette.ColorRole, fallback: QColor) -> QColor:
    color = palette.color(role)
    return color if color.isValid() else QColor(fallback)


class _StepButton(QAbstractButton):
    """One painted step that still behaves like a normal focusable Qt button."""

    def __init__(self, owner: "WorkflowHeader", index: int, label: str) -> None:
        super().__init__(owner)
        self._owner = owner
        self.index = int(index)
        self.setText(str(label))
        self.setCheckable(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"Step {self.index + 1}: {label}")
        self.setAccessibleDescription(str(label))
        self.setToolTip(str(label))
        self.clicked.connect(lambda _checked=False, row=self.index: owner.setCurrentRow(row))

    def circle_rect(self) -> QRect:
        top = self._owner._circle_top()
        return QRect(
            (self.width() - _CIRCLE_DIAMETER) // 2,
            top,
            _CIRCLE_DIAMETER,
            _CIRCLE_DIAMETER,
        )

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        key = event.key()
        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        ):
            self._owner._move_from_key(key)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        owner = self._owner
        palette = self.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dark = owner._dark_palette
        active = owner._active_color
        base = _palette_color(palette, QPalette.ColorRole.Button, palette.color(QPalette.ColorRole.Window))
        button_text = _palette_color(palette, QPalette.ColorRole.ButtonText, palette.color(QPalette.ColorRole.WindowText))
        window_text = _palette_color(palette, QPalette.ColorRole.WindowText, button_text)
        mid = _palette_color(palette, QPalette.ColorRole.Mid, palette.color(QPalette.ColorRole.WindowText))
        circle = self.circle_rect()
        current = self.index == owner.currentRow()
        state = owner.stepState(self.index)
        hovered = self.underMouse()

        if current:
            circle_fill = active
            circle_text = QColor(Qt.GlobalColor.white)
            label_color = active
        else:
            circle_fill = base
            circle_text = button_text
            label_color = window_text
            if hovered:
                # Use a palette-derived hover fill on light themes and a slightly
                # lifted button colour on dark themes; no fixed light-theme colour
                # leaks into a custom application palette.
                circle_fill = palette.color(QPalette.ColorRole.Highlight).lighter(115)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(circle_fill)
        painter.drawEllipse(circle)

        border = active if current else mid
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border, 1))
        painter.drawEllipse(circle.adjusted(0, 0, -1, -1))

        number_font = QFont(self.font())
        number_font.setBold(True)
        painter.setFont(number_font)
        painter.setPen(circle_text)
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(self.index + 1))

        label_rect = QRect(2, circle.bottom() + 8, max(0, self.width() - 4), 24)
        label_font = QFont(self.font())
        label_font.setBold(current)
        painter.setFont(label_font)
        painter.setPen(label_color)
        label = QFontMetrics(label_font).elidedText(
            self.text(), Qt.TextElideMode.ElideRight, label_rect.width()
        )
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

        if self.hasFocus():
            focus_color = active if dark else _palette_color(
                palette, QPalette.ColorRole.Highlight, active
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(focus_color, 1, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(circle.adjusted(-4, -4, 4, 4), 7, 7)
        painter.end()


class WorkflowStepItem:
    """Small item facade returned by :meth:`WorkflowHeader.item`.

    The underlying button remains accessible through ``button``.  The facade also
    gives callers a stable place to attach workflow-owned summary or validation
    metadata without requiring the header to know what those states mean.
    """

    def __init__(self, button: _StepButton) -> None:
        self.button = button

    def text(self) -> str:
        return self.button.text()

    def setText(self, text: str) -> None:  # noqa: N802 - QListWidgetItem-style API
        self.button.setText(str(text))
        self.button.update()

    def toolTip(self) -> str:  # noqa: N802 - QListWidgetItem-style API
        return self.button.toolTip()

    def setToolTip(self, text: str) -> None:  # noqa: N802 - QListWidgetItem-style API
        self.button.setToolTip(str(text))

    def state(self) -> WorkflowStepState:
        return self.button._owner.stepState(self.button.index)

    def setState(self, state: object) -> bool:  # noqa: N802 - QListWidgetItem-style API
        return self.button._owner.setStepState(self.button.index, state)

    def accessibleText(self) -> str:
        return self.button.accessibleName()

    def setAccessibleText(self, text: str) -> None:
        self.button.setAccessibleName(str(text))

    def accessibleDescription(self) -> str:  # noqa: N802 - QWidget-style API
        return self.button.accessibleDescription()

    def setAccessibleDescription(self, text: str) -> None:  # noqa: N802 - QWidget-style API
        self.button.setAccessibleDescription(str(text))

    def data(self, role: int):
        return self.button.property(f"workflowData:{int(role)}")

    def setData(self, role: int, value: object) -> None:
        self.button.setProperty(f"workflowData:{int(role)}", value)


class WorkflowHeader(QWidget):
    """A seven-step horizontal workflow navigator.

    ``currentRow()``, ``setCurrentRow()``, ``count()``, and ``currentRowChanged``
    intentionally mirror the navigation surface used by the former list-based
    header.  Invalid rows are ignored, matching ``QStackedWidget`` navigation and
    avoiding a transient no-selection state in a guided workflow.
    """

    currentRowChanged = Signal(int)

    def __init__(
        self,
        labels: Optional[Sequence[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        # Keep the ordinary QWidget ``WorkflowHeader(parent)`` construction form
        # usable alongside the optional custom-label form.
        if isinstance(labels, QWidget) and parent is None:
            parent = labels
            labels = None
        super().__init__(parent)
        values = tuple(DEFAULT_STEP_LABELS if labels is None else (str(value) for value in labels))
        if not values:
            raise ValueError("WorkflowHeader requires at least one step")

        self.setObjectName("workflow_header")
        self.setAccessibleName("New Item workflow steps")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(_HEADER_HEIGHT)
        self.setMaximumHeight(_HEADER_HEIGHT)
        self._current_row = 0
        self._labels = values
        self._states = [WorkflowStepState.PENDING for _ in values]
        self._states[0] = WorkflowStepState.ACTIVE
        self._dark_palette = _palette_is_dark(self.palette())
        self._active_color = self._resolve_active_color(self.palette())
        self._buttons = [_StepButton(self, index, label) for index, label in enumerate(values)]
        self._items = [WorkflowStepItem(button) for button in self._buttons]
        for previous, current in zip(self._buttons, self._buttons[1:]):
            self.setTabOrder(previous, current)
        self._sync_buttons()

    @staticmethod
    def _resolve_active_color(palette: QPalette) -> QColor:
        if _palette_is_dark(palette):
            return QColor(ACTIVE_DARK_COLOR)
        return _palette_color(palette, QPalette.ColorRole.Highlight, QColor("#0078d4"))

    def _refresh_palette(self) -> None:
        self._dark_palette = _palette_is_dark(self.palette())
        self._active_color = self._resolve_active_color(self.palette())
        self.update()
        for button in getattr(self, "_buttons", ()):
            button.update()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            self._refresh_palette()

    def _circle_top(self) -> int:
        return max(4, (self.height() - _HEADER_HEIGHT) // 2 + 4)

    def _sync_buttons(self) -> None:
        for index, button in enumerate(self._buttons):
            state = self.stepState(index)
            button.setProperty("workflowState", state.value)
            button.setProperty("workflowActive", index == self._current_row)
            button.setProperty("workflowCompleted", state == WorkflowStepState.COMPLETED)
            button.setProperty("workflowBlocked", state == WorkflowStepState.BLOCKED)
            button.setProperty("state", state.value)
            button.setProperty("active", index == self._current_row)
            button.setProperty("completed", state == WorkflowStepState.COMPLETED)
            button.setProperty("blocked", state == WorkflowStepState.BLOCKED)
            button.setAccessibleDescription(f"{button.text()} ({state.value})")
            button.setChecked(index == self._current_row)
            button.update()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        width = max(0, self.width() - 2 * _SIDE_PADDING)
        count = len(self._buttons)
        for index, button in enumerate(self._buttons):
            left = _SIDE_PADDING + round(width * index / count)
            right = _SIDE_PADDING + round(width * (index + 1) / count)
            button.setGeometry(left, 0, max(0, right - left), self.height())
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = self.palette()
        connector = _palette_color(palette, QPalette.ColorRole.Mid, palette.color(QPalette.ColorRole.WindowText))
        painter.setPen(QPen(connector, 1))
        for index in range(len(self._buttons) - 1):
            first = self._buttons[index]
            second = self._buttons[index + 1]
            first_center = first.mapTo(self, first.circle_rect().center())
            second_center = second.mapTo(self, second.circle_rect().center())
            painter.setPen(QPen(connector, 1))
            painter.drawLine(
                first_center.x() + _CIRCLE_DIAMETER // 2,
                first_center.y(),
                second_center.x() - _CIRCLE_DIAMETER // 2,
                second_center.y(),
            )
        painter.end()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        key = event.key()
        if key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        ):
            self._move_from_key(key)
            event.accept()
            return
        super().keyPressEvent(event)

    def _move_from_key(self, key: Qt.Key) -> None:
        current = self.currentRow()
        if key == Qt.Key.Key_Left:
            row = current - 1
        elif key == Qt.Key.Key_Right:
            row = current + 1
        elif key == Qt.Key.Key_Home:
            row = 0
        else:
            row = self.count() - 1
        if self.setCurrentRow(row):
            self._buttons[row].setFocus(Qt.FocusReason.OtherFocusReason)

    def count(self) -> int:
        return len(self._buttons)

    def currentRow(self) -> int:  # noqa: N802 - QListWidget-style API
        return self._current_row

    def stepState(self, index: int) -> Optional[WorkflowStepState]:  # noqa: N802
        try:
            position = int(index)
        except (IndexError, TypeError, ValueError):
            return None
        if not 0 <= position < self.count():
            return None
        return self._states[position]

    def setStepState(self, index: int, state: object) -> bool:  # noqa: N802
        try:
            position = int(index)
        except (IndexError, TypeError, ValueError):
            return False
        if not 0 <= position < self.count():
            return False
        resolved = _coerce_step_state(state)
        if resolved is None:
            return False
        if resolved == WorkflowStepState.ACTIVE and position != self._current_row:
            if not self.setCurrentRow(position):
                return False
            # ``setCurrentRow`` promotes a navigated-to row to active unless it was
            # explicitly blocked; this assignment also handles a manually completed
            # target being made active by its owner.
            changed = self._states[position] != WorkflowStepState.ACTIVE
            self._states[position] = WorkflowStepState.ACTIVE
            if changed:
                self._sync_buttons()
        elif self._states[position] != resolved:
            self._states[position] = resolved
            self._sync_buttons()
        else:
            return False
        return True

    def setCurrentRow(self, row: int) -> bool:  # noqa: N802 - QListWidget-style API
        try:
            target = int(row)
        except (TypeError, ValueError):
            return False
        if not 0 <= target < self.count() or target == self._current_row:
            return False
        previous = self._current_row
        if self._states[previous] == WorkflowStepState.ACTIVE:
            self._states[previous] = WorkflowStepState.COMPLETED
        self._current_row = target
        if self._states[target] != WorkflowStepState.BLOCKED:
            self._states[target] = WorkflowStepState.ACTIVE
        self._sync_buttons()
        self.currentRowChanged.emit(target)
        return True

    def item(self, index: int) -> Optional[WorkflowStepItem]:
        try:
            position = int(index)
        except (IndexError, TypeError, ValueError):
            return None
        if not 0 <= position < len(self._items):
            return None
        return self._items[position]

    def stepButton(self, index: int) -> Optional[QAbstractButton]:  # noqa: N802
        item = self.item(index)
        return item.button if item is not None else None

    def setStepToolTip(self, index: int, text: str) -> bool:
        item = self.item(index)
        if item is None:
            return False
        item.setToolTip(text)
        return True

    def setItemToolTip(self, index: int, text: str) -> bool:  # noqa: N802
        return self.setStepToolTip(index, text)

    def setStepAccessibleText(self, index: int, text: str) -> bool:
        item = self.item(index)
        if item is None:
            return False
        item.setAccessibleText(text)
        return True

    def setItemAccessibleText(self, index: int, text: str) -> bool:  # noqa: N802
        return self.setStepAccessibleText(index, text)

    def setItemData(self, index: int, role: int, value: object) -> bool:  # noqa: N802
        item = self.item(index)
        if item is None:
            return False
        item.setData(role, value)
        return True

    def itemData(self, index: int, role: int):  # noqa: N802
        item = self.item(index)
        return None if item is None else item.data(role)

    def sizeHint(self) -> QSize:
        return QSize(960, _HEADER_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(560, _HEADER_HEIGHT)


__all__ = [
    "ACTIVE_DARK_COLOR",
    "DEFAULT_STEP_LABELS",
    "WorkflowHeader",
    "WorkflowStepState",
    "WorkflowStepItem",
]
