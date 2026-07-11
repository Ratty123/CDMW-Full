"""Reusable panel widgets shared by UI features."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional, Tuple

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QTreeWidget, QVBoxLayout, QWidget

from cdmw.ui.layout_utils import scaled_px

class FlatSectionPanel(QWidget):
    """Simple titled panel without QGroupBox title-over-border rendering."""

    def __init__(self, title: str, *, body_margins: Tuple[int, int, int, int] = (10, 10, 10, 10), body_spacing: int = 8):
        super().__init__()
        self.setObjectName("FlatSectionPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 4, 0, 0)
        outer_layout.setSpacing(2)

        self.header_widget = QWidget()
        self.header_widget.setObjectName("FlatSectionHeader")
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(14, 0, 0, 0)
        header_layout.setSpacing(0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("FlatSectionTitle")
        self.title_label.setWordWrap(True)
        header_layout.addWidget(self.title_label, alignment=Qt.AlignLeft | Qt.AlignTop)
        header_layout.addStretch(1)
        outer_layout.addWidget(self.header_widget)

        self.body_frame = QFrame()
        self.body_frame.setObjectName("FlatSectionBody")
        self.body_layout = QVBoxLayout(self.body_frame)
        self.body_layout.setContentsMargins(*body_margins)
        self.body_layout.setSpacing(body_spacing)
        outer_layout.addWidget(self.body_frame, stretch=1)

class EmptyStatePanel(QWidget):
    """Centered low-noise guidance for empty tables, previews, and idle panes."""

    def __init__(self, title: str, detail: str = "", *, compact: bool = False):
        super().__init__()
        self.setObjectName("EmptyStatePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        pad_x = scaled_px(18 if compact else 28, self)
        pad_y = scaled_px(16 if compact else 24, self)
        layout.setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        layout.setSpacing(scaled_px(6, self))
        layout.addStretch(1)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("EmptyStateTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("EmptyStateDetail")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(bool(detail))
        layout.addWidget(self.detail_label)
        layout.addStretch(1)

    def set_text(self, title: str, detail: str = "") -> None:
        self.title_label.setText(title)
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))

class EmptyStateTreeWidget(QTreeWidget):
    """QTreeWidget with quiet placeholder copy when the model has no rows."""

    def __init__(self, title: str = "", detail: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.empty_title = title
        self.empty_detail = detail

    def set_empty_state(self, title: str, detail: str = "") -> None:
        self.empty_title = title
        self.empty_detail = detail
        self.viewport().update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self.topLevelItemCount() > 0 or not (self.empty_title or self.empty_detail):
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = self.viewport().rect().adjusted(scaled_px(24, self), scaled_px(24, self), -scaled_px(24, self), -scaled_px(24, self))
        palette = self.palette()
        title_font = QFont(self.font())
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(palette.color(QPalette.Text))
        metrics = painter.fontMetrics()
        title_height = metrics.boundingRect(rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_title).height()
        detail_height = 0
        if self.empty_detail:
            detail_font = QFont(self.font())
            detail_font.setBold(False)
            painter.setFont(detail_font)
            detail_height = painter.fontMetrics().boundingRect(rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_detail).height()
        gap = scaled_px(8, self) if self.empty_title and self.empty_detail else 0
        total_height = title_height + detail_height + gap
        y = rect.center().y() - total_height // 2
        if self.empty_title:
            title_rect = QRect(rect.left(), y, rect.width(), title_height)
            painter.setFont(title_font)
            painter.setPen(palette.color(QPalette.Text))
            painter.drawText(title_rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_title)
            y += title_height + gap
        if self.empty_detail:
            detail_rect = QRect(rect.left(), y, rect.width(), detail_height)
            painter.setFont(self.font())
            painter.setPen(palette.color(QPalette.PlaceholderText))
            painter.drawText(detail_rect, Qt.AlignCenter | Qt.TextWordWrap, self.empty_detail)

class CollapsibleSection(QWidget):
    toggled = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = False,
        body_builder: Optional[Callable[[QVBoxLayout], None]] = None,
    ):
        super().__init__()
        self._body_builder = body_builder
        self._body_built = body_builder is None
        self._body_building = False
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(6)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("SectionToggle")
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_button.clicked.connect(self.set_expanded)
        outer_layout.addWidget(self.toggle_button)

        self.body_frame = QFrame()
        self.body_frame.setObjectName("SectionBody")
        self.body_layout = QVBoxLayout(self.body_frame)
        self.body_layout.setContentsMargins(12, 10, 12, 12)
        self.body_layout.setSpacing(8)
        outer_layout.addWidget(self.body_frame)

        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded:
            self.ensure_body_built()
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body_frame.setVisible(expanded)
        self.toggled.emit(expanded)

    def is_body_built(self) -> bool:
        return self._body_built

    def ensure_body_built(self) -> None:
        if self._body_built or self._body_building:
            return
        builder = self._body_builder
        if builder is None:
            self._body_built = True
            return
        self._body_building = True
        self._body_built = True
        try:
            builder(self.body_layout)
        except Exception:
            self._body_built = False
            raise
        else:
            self._body_builder = None
        finally:
            self._body_building = False
