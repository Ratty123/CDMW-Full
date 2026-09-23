"""Project the existing workflow into native Rust presentation primitives.

The adapter walks layouts, not screen coordinates. Unknown interactive/custom
surfaces are reported as unsupported so coverage cannot silently lose a tool.
"""

from __future__ import annotations

import hashlib
import re

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QAction, QIntValidator, QPalette, QTextDocument
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QBoxLayout, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QRadioButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTextEdit, QToolButton, QWidget,
)

from cdmw.services.new_item_rust_protocol import MAX_DEPTH, MAX_NODES, MAX_TEXT_CHARS, MAX_EDITABLE_TEXT_CHARS, PresentationProtocolError
from cdmw.services.active_ui_translation import active_ui_localizer, translate_active_ui_text
from cdmw.ui.new_item.rust_ui_models import ModelProjection
from cdmw.ui.new_item.rust_ui_registry import ControlRegistry
from cdmw.ui.new_item.workflow_header import WorkflowHeader
from cdmw.ui.themes import get_theme


def plain_text(value):
    value = str(value or "")
    if "<" not in value:
        return value, []
    doc = QTextDocument()
    doc.setHtml(value)
    links = []
    block = doc.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isAnchor():
                links.append({"text": fragment.text(), "url": fragment.charFormat().anchorHref()})
            iterator += 1
        block = block.next()
    return doc.toPlainText(), links


def rich_spans(value):
    if "<" not in value:
        return []
    document = QTextDocument()
    document.setHtml(value)
    spans = []
    block = document.begin()
    while block.isValid():
        if spans:
            spans.append({"text": "\n"})
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                style = fragment.charFormat()
                spans.append({"text": fragment.text().replace("\u2028", "\n").replace("\u2029", "\n"), "bold": style.fontWeight() >= 600,
                              "italic": style.fontItalic(),
                              "color": style.foreground().color().name() if style.foreground().style() != Qt.NoBrush else "",
                              "url": style.anchorHref() if style.isAnchor() else ""})
            iterator += 1
        block = block.next()
    return spans


def theme_snapshot(widget):
    palette = widget.palette()
    roles = {"background": QPalette.Window, "panel": QPalette.Base,
             "text": QPalette.WindowText, "muted": QPalette.PlaceholderText,
             "button": QPalette.Button, "border": QPalette.Mid,
             "accent": QPalette.Highlight, "accent_text": QPalette.HighlightedText,
             "link": QPalette.Link}
    result = {key: palette.color(role).name() for key, role in roles.items()}
    app = QApplication.instance()
    theme_key = app.property("_cdmw_theme_key") if app is not None else None
    if theme_key:
        theme = get_theme(str(theme_key))
        for key in ("button_hover", "button_pressed", "button_border"):
            result[key] = theme[key]
    result["disabled"] = palette.color(QPalette.Disabled, QPalette.WindowText).name()
    font = widget.font()
    result["font_family"] = font.family()
    pixels = font.pixelSize() if font.pixelSize() > 0 else font.pointSizeF() * widget.logicalDpiY() / 72
    result["font_pixels"] = max(8, round(pixels))
    result["dark"] = palette.color(QPalette.Window).lightnessF() < 0.5
    localizer = active_ui_localizer()
    result["language"] = str(getattr(localizer, "language_code", "en"))
    return result


class PresentationDocument:
    def __init__(self):
        self.registry = ControlRegistry()
        self.models = ModelProjection()
        self.unsupported = []
        self.assets = {}
        self._depth = 0
        self._nodes = 0
        self._images = {}
        self.portals = {}

    def snapshot(self, root, *, dialogs=()):
        self.registry.begin()
        self.unsupported, self.assets, self.portals = [], {}, {}
        self._depth, self._nodes = 0, 0
        content = self.widget(root, force=True)
        windows = [self.widget(dialog, force=True) for dialog in dialogs]
        return {"root": content, "dialogs": windows, "theme": theme_snapshot(root),
                "assets": self.assets, "unsupported": self.unsupported,
                "strings": {"copy": translate_active_ui_text("Copy"),
                            "previous": translate_active_ui_text("Previous"),
                            "next": translate_active_ui_text("Next")}}

    def image(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return None
        cache_key = pixmap.cacheKey()
        cached = self._images.get(cache_key)
        if cached is None:
            if max(pixmap.width(), pixmap.height()) > 1024:
                pixmap = pixmap.scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            pixmap.save(buffer, "PNG")
            data = bytes(buffer.data())
            identifier = hashlib.sha256(data).hexdigest()
            cached = (identifier, {"png_hex": data.hex(), "width": pixmap.width(), "height": pixmap.height()})
            if len(self._images) >= 128:
                self._images.clear()
            self._images[cache_key] = cached
        self.assets[cached[0]] = cached[1]
        return cached[0]

    def widget(self, widget, *, force=False):
        if widget is None or (widget.isHidden() and not force):
            return None
        from cdmw.ui.new_item.rust_ui_portals import _PreviewPlaceholder
        if isinstance(widget, _PreviewPlaceholder):
            return self.widget(widget.preview, force=True)
        self._depth += 1
        self._nodes += 1
        if self._depth > MAX_DEPTH or self._nodes > MAX_NODES:
            raise PresentationProtocolError("The presentation exceeds its control-tree limit.")
        try:
            identifier = self.registry.identify(widget)
            node = {"kind": "column", "name": widget.objectName(),
                    "label": widget.accessibleName(), "tooltip": plain_text(widget.toolTip())[0],
                    "enabled": widget.isEnabled(), "props": {}, "children": []}
            node["props"]["grow_x"] = bool(widget.sizePolicy().horizontalPolicy().value & 2)
            node["props"]["grow_y"] = bool(widget.sizePolicy().verticalPolicy().value & 2)
            self._describe(widget, identifier, node)
            return self.registry.publish(widget, node)
        finally:
            self._depth -= 1

    def _describe(self, widget, identifier, node):
        props = node["props"]
        if widget.__class__.__name__ == "NewItemStudioTab" and widget._panels_built:
            node["kind"] = "workspace"
            # These slots retain the existing workflow's stable navigation. Page
            # scrolling must never push Back/Continue out of the native window.
            for name, value in (("notice", widget._read_failure), ("header", widget.steps),
                                ("body", widget.pages.currentWidget()),
                                ("back", widget.back_button), ("hint", widget.step_hint),
                                ("next", widget.continue_button)):
                child = self.widget(value)
                if child is not None:
                    child["slot"] = name
                    node["children"].append(child)
        elif isinstance(widget, WorkflowHeader):
            node["kind"] = "steps"
            props.update(selected=widget.currentRow(), steps=[
                {"text": widget.item(i).text(), "tooltip": widget.item(i).toolTip(),
                 "state": widget.stepState(i).value} for i in range(widget.count())])
        elif widget.objectName() == "RustPreviewViewport":
            node["kind"] = "viewport"
            self.portals[identifier] = widget
            props.update(min_height=260)
        elif widget.__class__.__name__ == "_BusySpinner":
            node["kind"] = "progress"
            props.update(indeterminate=True, text=widget.accessibleName())
        elif widget.__class__.__name__ == "IconRegionSelector":
            node["kind"] = "image_crop"
            selection = widget.source_selection_rect()
            props.update(image=self.image(widget._image), width=widget._image.width(), height=widget._image.height(),
                         selection=[selection.x(),selection.y(),selection.width(),selection.height()])
        elif widget.__class__.__name__ == "RustPreviewHostFrame":
            # Keep the preview and its loading/retry overlays together. They
            # share one slot, so status changes never resize the rendered mesh.
            node["kind"] = "viewport"
            self.portals[identifier] = widget
            props.update(min_height=260)
        elif isinstance(widget, QAbstractButton):
            self._button(widget, node)
        elif isinstance(widget, QLineEdit):
            node["kind"] = "text"
            props.update(text=widget.text(), placeholder=widget.placeholderText(),
                         readonly=widget.isReadOnly(), maximum=widget.maxLength(),
                         password=widget.echoMode() != QLineEdit.Normal, multiline=False,
                         acceptable=widget.hasAcceptableInput())
            validator = widget.validator()
            if isinstance(validator, QIntValidator) and validator.bottom() >= 0:
                props["digits_only"] = True
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            node["kind"] = "text"
            text = widget.toPlainText()
            offset = self.models.ranges.get((identifier, ()), 0) if widget.isReadOnly() else 0
            limit = MAX_TEXT_CHARS if widget.isReadOnly() else MAX_EDITABLE_TEXT_CHARS
            props.update(text=text[offset:offset + limit], total=len(text), offset=offset,
                         readonly=widget.isReadOnly(), multiline=True,
                         placeholder=widget.placeholderText(), maximum=limit)
            if not widget.isReadOnly() and len(text) > limit:
                self.unsupported.append({"name": widget.objectName(), "class": type(widget).__name__,
                                         "reason": "Editable text exceeds the protocol limit."})
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox, QSlider)):
            node["kind"] = "slider" if isinstance(widget, QSlider) else "number"
            props.update(value=widget.value(), minimum=widget.minimum(), maximum=widget.maximum(),
                         step=widget.singleStep(), decimals=widget.decimals() if isinstance(widget, QDoubleSpinBox) else 0)
            if not isinstance(widget, QSlider):
                props.update(prefix=widget.prefix(), suffix=widget.suffix(), readonly=widget.isReadOnly(),
                             special=widget.specialValueText(), keyboard_tracking=widget.keyboardTracking())
        elif isinstance(widget, QComboBox):
            node["kind"] = "choice"
            props.update(self.models.combo(widget, identifier))
        elif isinstance(widget, QAbstractItemView):
            node["kind"] = "table"
            props.update(self.models.view(widget, identifier, self.widget))
        elif isinstance(widget, QLabel):
            node["kind"] = "label"
            text, links = plain_text(widget.text()) if widget.textFormat() != Qt.PlainText else (widget.text(), [])
            props.update(text=text, links=links, bold=widget.font().bold(), wrap=widget.wordWrap(),
                         image=self.image(widget.pixmap()), align=int(widget.alignment()),
                         spans=rich_spans(widget.text()) if widget.textFormat() != Qt.PlainText else [])
        elif isinstance(widget, QProgressBar):
            node["kind"] = "progress"
            props.update(value=widget.value(), minimum=widget.minimum(), maximum=widget.maximum(),
                         text=widget.text(), indeterminate=widget.maximum() == widget.minimum())
        elif isinstance(widget, QTabWidget):
            node["kind"] = "tabs"
            props.update(selected=widget.currentIndex(), tabs=[
                {"text": widget.tabText(i), "enabled": widget.isTabEnabled(i),
                 "visible": widget.isTabVisible(i), "tooltip": widget.tabToolTip(i)} for i in range(widget.count())])
            child = self.widget(widget.currentWidget(), force=True)
            node["children"] = [child] if child else []
            props["corners"] = self._widgets(widget.cornerWidget(corner) for corner in
                                             (Qt.TopLeftCorner, Qt.TopRightCorner))
        elif isinstance(widget, QStackedWidget):
            child = self.widget(widget.currentWidget(), force=True)
            node["children"] = [child] if child else []
        elif isinstance(widget, QScrollArea):
            node["kind"] = "scroll"
            child = self.widget(widget.widget())
            node["children"] = [child] if child else []
        elif isinstance(widget, QSplitter):
            node["kind"] = "split"
            props.update(horizontal=widget.orientation() == Qt.Horizontal, sizes=widget.sizes())
            props["indices"] = []
            for index in range(widget.count()):
                child = self.widget(widget.widget(index))
                if child is not None:
                    node["children"].append(child)
                    props["indices"].append(index)
        elif isinstance(widget, QMenu):
            node["kind"] = "menu"
            node["children"] = [self.action(action) for action in widget.actions() if action.isVisible()]
        else:
            if isinstance(widget, QGroupBox):
                node["kind"] = "group"
                node["label"] = widget.title()
                props.update(checkable=widget.isCheckable(), checked=widget.isChecked(),
                             plain=bool(widget.property("guidedPage") or widget.property("titlelessSection")))
            elif isinstance(widget, QDialog):
                node["kind"] = "dialog"
                node["label"] = widget.windowTitle()
                props["modal"] = widget.isModal()
            elif isinstance(widget, QDialogButtonBox):
                props["dialog_actions"] = True
            elif isinstance(widget, QFrame) and widget.frameShape() in (QFrame.HLine, QFrame.VLine):
                node["kind"] = "separator"
            layout = widget.layout()
            if layout is not None:
                child = self.layout(layout)
                node["children"] = [child] if child else []
            else:
                children = widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
                visible = [child for child in children if not child.isHidden()]
                if visible:
                    node["children"] = self._widgets(visible)
                elif type(widget) not in (QWidget, QFrame) and node["kind"] != "separator":
                    self.unsupported.append({"name": widget.objectName(), "class": type(widget).__name__,
                                             "reason": "Custom surface has no presentation adapter."})

    def _widgets(self, values):
        return [node for value in values if (node := self.widget(value)) is not None]

    def _button(self, widget, node):
        node["kind"] = "radio" if isinstance(widget, QRadioButton) else "check" if isinstance(widget, QCheckBox) else "button"
        node["label"] = widget.text()
        parent = widget.parentWidget()
        if isinstance(parent, QDialogButtonBox) and parent.standardButton(widget) == QDialogButtonBox.NoButton:
            # Qt's shared localizer handles standard button-box labels; custom
            # roles retain their source text, so translate their presentation.
            node["label"] = translate_active_ui_text(widget.text())
        props = node["props"]
        props.update(checkable=widget.isCheckable(), checked=widget.isChecked(),
                     primary=bool(widget.property("newItemPrimary")),
                     default=bool(hasattr(widget, "isDefault") and widget.isDefault()),
                     image=self.image(widget.icon().pixmap(24, 24)) if not widget.icon().isNull() else None)
        # The colour-curve editor uses an explicit bottom-border swatch. Carry
        # that semantic colour, rather than attempting to render arbitrary QSS.
        swatch = re.search(r"border-bottom:\s*\d+px\s+solid\s+(#[0-9a-fA-F]{6})", widget.styleSheet())
        if swatch:
            props["swatch"] = swatch.group(1)
        if "background-color:" in widget.styleSheet():
            props["swatch"] = widget.palette().color(QPalette.Button).name()
        if isinstance(widget, QCheckBox):
            props["check_state"] = widget.checkState().value
        if hasattr(widget, "menu") and widget.menu() is not None:
            props["menu"] = [self.action(action) for action in widget.menu().actions() if action.isVisible()]
            props["instant_menu"] = isinstance(widget, QToolButton) and widget.popupMode() == QToolButton.InstantPopup

    def action(self, action: QAction):
        node = {"kind": "separator" if action.isSeparator() else "action", "name": action.objectName(),
                "label": action.text(), "tooltip": action.toolTip(), "enabled": action.isEnabled(),
                "props": {"checkable": action.isCheckable(), "checked": action.isChecked(),
                          "shortcut": action.shortcut().toString()}, "children": []}
        if action.menu() is not None:
            node["children"] = [self.action(child) for child in action.menu().actions() if child.isVisible()]
        return self.registry.publish(action, node)

    def layout(self, layout):
        children = []
        grid = isinstance(layout, (QGridLayout, QFormLayout))
        horizontal = isinstance(layout, QBoxLayout) and layout.direction() in (QBoxLayout.LeftToRight, QBoxLayout.RightToLeft)
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child = self.widget(item.widget()) if item.widget() is not None else self.layout(item.layout()) if item.layout() is not None else None
            if child is None:
                # Fixed margins/stretch never become empty panels in the Rust UI.
                continue
            if isinstance(layout, QGridLayout):
                row, column, row_span, column_span = layout.getItemPosition(index)
                child["cell"] = [row, column, row_span, column_span]
            elif isinstance(layout, QFormLayout):
                row, role = layout.getItemPosition(index)
                child["cell"] = [row, 0 if role == QFormLayout.SpanningRole else int(role.value),
                                 1, 2 if role == QFormLayout.SpanningRole else 1]
            if isinstance(layout, QBoxLayout):
                if horizontal:
                    child["props"]["grow_x"] = bool(layout.stretch(index)) or child["props"].get("grow_x", False)
                else:
                    child["stretch"] = layout.stretch(index)
            children.append(child)
        return {"kind": "grid" if grid else "row" if horizontal else "column",
                "name": layout.objectName(), "enabled": True, "label": "", "tooltip": "",
                "props": {"form": isinstance(layout, QFormLayout), "spacing": max(4, min(12, layout.spacing())),
                          "dialog_actions": horizontal and any(isinstance(layout.itemAt(i).widget(), QDialogButtonBox)
                                                               for i in range(layout.count()))},
                "children": children}
