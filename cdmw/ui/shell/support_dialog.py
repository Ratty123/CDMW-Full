"""Optional support dialog for the shell window."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from cdmw.constants import APP_KOFI_URL, APP_TITLE


class SupportDialogMixin:
    """Optional Ko-fi support dialog actions."""
    def _build_support_heart_icon(self) -> QIcon:
        pixmap = QPixmap(18, 18)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#e05263"))
        path = QPainterPath()
        path.moveTo(9.0, 15.0)
        path.cubicTo(2.8, 10.2, 2.0, 7.2, 3.4, 4.8)
        path.cubicTo(4.6, 2.8, 7.2, 2.6, 9.0, 4.7)
        path.cubicTo(10.8, 2.6, 13.4, 2.8, 14.6, 4.8)
        path.cubicTo(16.0, 7.2, 15.2, 10.2, 9.0, 15.0)
        painter.drawPath(path)
        painter.end()
        return QIcon(pixmap)

    def show_support_dialog(self, _checked: bool = False) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Support {APP_TITLE}")
        dialog.setMinimumWidth(440)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        message = QLabel(
            "This app has taken a lot of spare-time work to research, build, test, and keep improving. "
            "You absolutely do not need to tip. If the software helped you, saved time, or made modding a little easier, "
            "coffee money is appreciated and helps keep the project moving."
        )
        message.setWordWrap(True)
        message.setObjectName("HintLabel")
        layout.addWidget(message)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        support_button = QPushButton("Support Me")
        support_button.setIcon(self._build_support_heart_icon())
        support_button.setToolTip(APP_KOFI_URL)
        close_button = QPushButton("Close")
        button_row.addWidget(support_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        support_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(APP_KOFI_URL)))
        close_button.clicked.connect(dialog.accept)
        dialog.exec()

__all__ = ["SupportDialogMixin"]
