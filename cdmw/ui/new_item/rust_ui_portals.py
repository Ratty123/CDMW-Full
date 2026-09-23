"""Move only existing native viewport frames into Rust-reported layout slots."""

from __future__ import annotations

import math

from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from cdmw.services.new_item_rust_protocol import PresentationProtocolError


class _PreviewPlaceholder(QWidget):
    """Preserve the authoritative layout while its native preview is displayed elsewhere."""

    def __init__(self, preview, parent):
        super().__init__(parent)
        self.preview = preview
        self._hint = preview.sizeHint()
        self._minimum_hint = preview.minimumSizeHint()
        self.setSizePolicy(preview.sizePolicy())
        self.setMinimumSize(preview.minimumSize())
        self.setMaximumSize(preview.maximumSize())

    def sizeHint(self):
        return self._hint

    def minimumSizeHint(self):
        return self._minimum_hint


class PreviewPortals:
    def __init__(self, host):
        self.host = host
        self._attached = {}
        self._placeholders = {}

    def update(self, document, message):
        scale = message.get("pixels_per_point")
        if type(scale) not in (float, int) or not math.isfinite(scale) or not 0.5 <= scale <= 8:
            raise PresentationProtocolError("Invalid viewport layout scale.")
        ratio = float(scale) / self.host.devicePixelRatioF()
        portals = message.get("portals")
        if not isinstance(portals, list) or len(portals) > 16:
            raise PresentationProtocolError("Invalid viewport layout.")
        visible = set()
        for item in portals:
            if not isinstance(item, dict):
                raise PresentationProtocolError("Invalid viewport slot.")
            identifier = item.get("id")
            viewport = document.portals.get(identifier)
            if viewport is None or not isValid(viewport):
                continue
            rect = self._rectangle(item.get("rect"), ratio)
            clip = self._rectangle(item.get("clip"), ratio).intersected(self.host.rect()).intersected(rect)
            if clip.isEmpty():
                continue
            if identifier not in self._attached:
                parent = viewport.parentWidget()
                layout = parent.layout() if parent is not None else None
                position = layout.indexOf(viewport) if layout else -1
                if layout and position >= 0:
                    placeholder = _PreviewPlaceholder(viewport, parent)
                    layout.replaceWidget(viewport, placeholder)
                    placeholder.show()
                    self._placeholders[identifier] = placeholder
                self._attached[identifier] = (viewport, parent, layout, position)
                viewport.setParent(self.host)
            viewport.setGeometry(rect)
            viewport.setMask(QRegion(clip.translated(-rect.x(), -rect.y())))
            viewport.show()
            viewport.raise_()
            visible.add(identifier)
        for identifier in self._attached.keys() - visible:
            viewport = self._attached[identifier][0]
            if isValid(viewport):
                viewport.hide()

    @staticmethod
    def _rectangle(value, ratio):
        if (not isinstance(value, list) or len(value) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000 for v in value)
                or value[2] < 0 or value[3] < 0):
            raise PresentationProtocolError("Invalid viewport rectangle.")
        return QRect(*(round(v * ratio) for v in value))

    def restore(self):
        for identifier, (viewport, parent, layout, position) in self._attached.items():
            if not isValid(viewport):
                continue
            viewport.clearMask()
            if parent is not None and isValid(parent):
                viewport.setParent(parent)
                if layout is not None and isValid(layout):
                    placeholder = self._placeholders.get(identifier)
                    if placeholder is not None and isValid(placeholder):
                        layout.replaceWidget(placeholder, viewport)
                    elif hasattr(layout, "insertWidget"):
                        layout.insertWidget(max(0, position), viewport, 1)
                    else:
                        layout.addWidget(viewport)
                viewport.show()
        for placeholder in self._placeholders.values():
            if isValid(placeholder):
                placeholder.hide()
                placeholder.deleteLater()
        self._placeholders.clear()
        self._attached.clear()
