"""Layouts that wrap actions or equal-width cards without squeezing their text."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QWidget


class WrappingLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, *, columns: int = 0) -> None:
        super().__init__(parent)
        self._items = []
        self._columns = columns
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item) -> None:
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Horizontal

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def minimumSize(self) -> QSize:
        size = QSize(0, 0)
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def sizeHint(self) -> QSize:
        items = [item for item in self._items if not item.isEmpty()]
        width = sum(item.sizeHint().width() for item in items) + max(0, len(items) - 1) * self.spacing()
        if self._columns and items:
            width = max(item.sizeHint().width() for item in items) * min(self._columns, len(items))
        width = max(width, self.minimumSize().width())
        return QSize(width, self.heightForWidth(width))

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        items = [item for item in self._items if not item.isEmpty()]
        gap = max(0, self.spacing())
        column_width = 0
        if self._columns and items:
            minimum = max(item.minimumSize().width() for item in items)
            count = max(1, min(self._columns, (area.width() + gap) // max(1, minimum + gap)))
            column_width = max(minimum, (area.width() - gap * (count - 1)) // count)
        x, y, row_height = area.x(), area.y(), 0
        for item in items:
            width = column_width or item.sizeHint().expandedTo(item.minimumSize()).width()
            height = item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
            height = max(height, item.minimumSize().height())
            if x > area.x() and x + width > area.right() + 1:
                x = area.x()
                y += row_height + gap
                row_height = 0
            if apply:
                item.setGeometry(QRect(x, y, width, height))
            x += width + gap
            row_height = max(row_height, height)
        return y + row_height - rect.y() + margins.bottom()
