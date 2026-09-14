"""Paint waiting/loading indicators over the Finder's empty thumbnail slots."""

from time import monotonic

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem


THUMBNAIL_ACTIVITY_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class CharacterThumbnailDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        stage = index.data(THUMBNAIL_ACTIVITY_ROLE)
        if not stage or stage in {"ready", "failed"}:
            return
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        rect = styled.widget.style().subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, styled, styled.widget)
        center = rect.center()
        ring = QRectF(center.x() - 12, center.y() - 12, 24, 24)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(styled.palette.text().color(), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if stage == "queued":
            painter.drawEllipse(ring)
            painter.drawLine(center.x(), center.y() - 7, center.x(), center.y())
            painter.drawLine(center.x(), center.y(), center.x() + 5, center.y() + 3)
        else:
            painter.drawArc(ring, -int(monotonic() * 300) % 360 * 16, 260 * 16)
        painter.restore()
