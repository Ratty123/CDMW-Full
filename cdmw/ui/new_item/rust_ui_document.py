"""Project the existing workflow into native Rust presentation primitives.

The adapter walks layouts, not screen coordinates. Unknown interactive/custom
surfaces are reported as unsupported so coverage cannot silently lose a tool.
"""

from __future__ import annotations

import hashlib
import re
import weakref
from collections import OrderedDict

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QAction, QIcon, QImage, QIntValidator, QPainter, QPalette, QPixmap, QRegion, QTextDocument
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QBoxLayout, QCheckBox, QComboBox,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QLabel, QLayout, QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QRadioButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
    QTextEdit, QToolButton, QWidget,
)

from cdmw.services.new_item_rust_protocol import MAX_DEPTH, MAX_NODES, MAX_TEXT_CHARS, MAX_EDITABLE_TEXT_CHARS, PresentationProtocolError
from cdmw.services.active_ui_translation import active_ui_localizer, translate_active_ui_text
from cdmw.ui.new_item.rust_ui_models import ModelProjection
from cdmw.ui.new_item.rust_ui_registry import ControlRegistry
from cdmw.ui.new_item.workflow_header import WorkflowHeader
from cdmw.ui.themes import get_theme
from cdmw.ui.layout_metrics import MIN_FONT_PIXELS, layout_metrics


def qt_caption(value):
    """Return the visible caption without Qt-only mnemonic escapes."""
    return re.sub(r"&(.)", lambda match: match[1], str(value or ""))


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
    # One range on every surface (P11): the page's floor is the UI minimum.
    result["font_pixels"] = max(MIN_FONT_PIXELS, round(pixels))
    result["min_font_pixels"] = MIN_FONT_PIXELS
    application = QApplication.instance()
    density = str(application.property("_cdmw_ui_density") or "compact") if application is not None else "compact"
    try:
        scale = float(application.property("_cdmw_layout_scale") or 1.0) if application is not None else 1.0
    except (TypeError, ValueError):
        scale = 1.0
    result["layout_metrics"] = layout_metrics(density, pixels * 72.0 / 96.0, scale).payload()
    result["dark"] = palette.color(QPalette.Window).lightnessF() < 0.5
    localizer = active_ui_localizer()
    result["language"] = str(getattr(localizer, "language_code", "en"))
    return result


#: A custom-painted surface is sent at most this many device pixels on its long side,
#: and its PNG at most this many bytes (the page refuses an image over 1024 pixels or
#: 8 MB of hex, and the whole state is serialised on every update).
PICTURE_MAX_SIDE = 900
PICTURE_MAX_BYTES = 1_000_000
#: ...and drawn at most this many times its size in Qt, however small it is there.
PICTURE_MAX_ZOOM = 4.0
#: Encoded images kept between snapshots, least recently used first out.
IMAGE_CACHE_ENTRIES = 512

_QT_MODULE_PREFIX = "PySide6"
_PLAIN_CONTAINERS = (QWidget, QFrame)


def _paints_itself(widget):
    """Whether a Python subclass of a plain widget draws its own content in paintEvent."""

    if isinstance(widget, (QDialog, QGroupBox, QDialogButtonBox)):
        return False
    for cls in type(widget).__mro__:
        if cls in _PLAIN_CONTAINERS:
            return False
        if not cls.__module__.startswith(_QT_MODULE_PREFIX) and "paintEvent" in vars(cls):
            return True
    return False


def _shows_only_text(widget):
    """Whether every visible descendant is a label or a plain container: nothing to click."""

    for child in widget.findChildren(QWidget):
        if child.isHidden():
            continue
        if isinstance(child, QLabel):
            continue
        if type(child) in _PLAIN_CONTAINERS:
            continue
        return False
    return True


def _icon_cell(icon, size, ratio):
    """The icon as Qt draws it in a view: within the icon size, centred, never enlarged.
    The page draws the result at exactly the icon size."""

    cell = QImage(round(size.width() * ratio), round(size.height() * ratio),
                  QImage.Format.Format_ARGB32_Premultiplied)
    cell.fill(Qt.GlobalColor.transparent)
    pixmap = icon.pixmap(size, ratio)
    if pixmap.isNull():
        return None
    shown = pixmap.size().scaled(cell.size(), Qt.KeepAspectRatio)
    if shown.width() > pixmap.width() or shown.height() > pixmap.height():
        shown = pixmap.size()
    painter = QPainter(cell)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap((cell.width() - shown.width()) // 2, (cell.height() - shown.height()) // 2,
                           shown.width(), shown.height(), pixmap)
    finally:
        painter.end()
    return QPixmap.fromImage(cell)


def _drawn_bounds(image):
    """The smallest rectangle holding every pixel of `image` that is not fully transparent."""

    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    data, stride, width = bytes(alpha.constBits()), alpha.bytesPerLine(), alpha.width()
    rows = [(y, data[y * stride:y * stride + width]) for y in range(alpha.height())]
    drawn = [(y, row) for y, row in rows if row.count(0) != width]
    if not drawn:
        return QRect()
    left = min(width - len(row.lstrip(b"\0")) for _, row in drawn)
    right = max(len(row.rstrip(b"\0")) for _, row in drawn)
    return QRect(left, drawn[0][0], right - left, drawn[-1][0] - drawn[0][0] + 1)


def _png(image):
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class PresentationDocument:
    def __init__(self):
        self.registry = ControlRegistry()
        self.models = ModelProjection()
        self.unsupported = []
        self.assets = {}
        self._depth = 0
        self._nodes = 0
        self._images = OrderedDict()
        #: per custom-painted widget: (change key, content digest, asset id, asset)
        self._pictures = weakref.WeakKeyDictionary()
        self.portals = {}
        self._text_revisions = {}
        self._formatted_text = {}
        self._format_font = None
        self._document_texts = weakref.WeakKeyDictionary()

    def snapshot(self, root, *, dialogs=()):
        font = QApplication.font().key()
        if font != self._format_font:
            self._formatted_text.clear()
            self._format_font = font
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

    def _format_text(self, value, formatter):
        if "<" not in value:
            return formatter(value)
        key = formatter, value
        if key not in self._formatted_text:
            result = formatter(value)
            # Keep only small UI captions/tooltips, never unbounded HTML reports.
            if len(value) > 8192:
                return result
            if len(self._formatted_text) >= 128:
                self._formatted_text.pop(next(iter(self._formatted_text)))
            self._formatted_text[key] = result
        return self._formatted_text[key]

    def _document_text(self, widget):
        document = widget.document()
        revision = document.revision()
        cached = self._document_texts.get(document)
        if cached is not None and revision >= 0 and cached[0] == revision:
            return cached[1]
        text = widget.toPlainText()
        self._document_texts.pop(document, None)
        if revision >= 0 and len(text) <= MAX_EDITABLE_TEXT_CHARS:
            if len(self._document_texts) >= 8:
                self._document_texts.clear()
            self._document_texts[document] = revision, text
        return text

    def _cached_image(self, cache_key, make):
        """The asset id of an image, encoding it with `make()` only when it is not cached."""

        cached = self._images.get(cache_key)
        if cached is None:
            pixmap = make()
            if pixmap is None or pixmap.isNull():
                return None
            if max(pixmap.width(), pixmap.height()) > 1024:
                pixmap = pixmap.scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            data = _png(pixmap)
            identifier = hashlib.sha256(data).hexdigest()
            cached = (identifier, {"png_hex": data.hex(), "width": pixmap.width(), "height": pixmap.height()})
            self._images[cache_key] = cached
            while len(self._images) > IMAGE_CACHE_ENTRIES:
                self._images.popitem(last=False)
        else:
            self._images.move_to_end(cache_key)
        self.assets[cached[0]] = cached[1]
        return cached[0]

    def image(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return None
        return self._cached_image(("pixmap", pixmap.cacheKey()), lambda: pixmap)

    def icon(self, value, size):
        """An item's decoration (an icon, pixmap or image) at the view's icon size."""

        if size is None or not size.isValid() or size.isEmpty():
            return None
        if not isinstance(value, (QIcon, QPixmap, QImage)) or value.isNull():
            return None
        ratio = max(1.0, float(QApplication.instance().devicePixelRatio()))
        # Keyed on the icon, not on the pixmap it gives: QIcon.pixmap() may make a new
        # pixmap on every call, which would encode every row on every update.
        key = (type(value).__name__, value.cacheKey(), size.width(), size.height(), ratio)

        def make():
            icon = value if isinstance(value, QIcon) else QIcon(
                value if isinstance(value, QPixmap) else QPixmap.fromImage(value))
            return _icon_cell(icon, size, ratio)

        return self._cached_image(key, make)

    def picture(self, widget):
        """A custom-painted widget's own drawing (its children are described apart), cut to
        what it draws: the asset id, or None when it draws nothing, and that part's size in
        logical pixels. The page fits it into the room it has, which is seldom the hidden Qt
        widget's shape, so empty margins would only make the drawing smaller.

        It is drawn again only when its change key differs: its size, scale, palette and,
        when it has one, its `presentation_revision()`. A widget without that hook is drawn
        on every snapshot, but encoded only when its pixels differ."""

        size = widget.size()
        if size.width() <= 0 or size.height() <= 0:
            return None, (0, 0)
        revision_of = getattr(widget, "presentation_revision", None)
        revision = revision_of() if callable(revision_of) else None
        ratio = max(1.0, float(widget.devicePixelRatioF()))
        key = (revision, size.width(), size.height(), ratio, widget.palette().cacheKey())
        cached = self._pictures.get(widget)
        if cached is not None and revision is not None and cached[0] == key:
            return self._reuse_picture(widget, key, cached)
        whole = QRectF(widget.rect())
        probe_scale = min(1.0, PICTURE_MAX_SIDE / max(size.width(), size.height()))
        probe = self._render(widget, whole, probe_scale)
        digest = hashlib.blake2b(bytes(probe.constBits()), digest_size=16).digest()
        if cached is not None and cached[1] == digest:
            return self._reuse_picture(widget, key, cached)
        bounds = _drawn_bounds(probe)
        if bounds.isEmpty():
            self._pictures[widget] = (key, digest, None, None, (0, 0))
            return None, (0, 0)
        crop = QRectF(bounds.x() / probe_scale, bounds.y() / probe_scale, bounds.width() / probe_scale,
                      bounds.height() / probe_scale).adjusted(-1, -1, 1, 1).intersected(whole)
        # As sharp as the cap allows, so a page larger than the hidden widget stays crisp.
        scale = min(PICTURE_MAX_SIDE / max(crop.width(), crop.height()), max(ratio, PICTURE_MAX_ZOOM))
        image = self._render(widget, crop, scale)
        data = _png(image)
        while len(data) > PICTURE_MAX_BYTES and max(image.width(), image.height()) > 64:
            scale *= 0.7
            image = self._render(widget, crop, scale)
            data = _png(image)
        identifier = hashlib.sha256(data).hexdigest()
        asset = {"png_hex": data.hex(), "width": image.width(), "height": image.height()}
        shown = (round(crop.width()), round(crop.height()))
        self._pictures[widget] = (key, digest, identifier, asset, shown)
        self.assets[identifier] = asset
        return identifier, shown

    def _reuse_picture(self, widget, key, cached):
        self._pictures[widget] = (key, *cached[1:])
        if cached[2] is not None:
            self.assets[cached[2]] = cached[3]
        return cached[2], cached[4]

    @staticmethod
    def _render(widget, source, scale):
        """`source` (a part of the widget, in logical pixels) drawn at `scale`."""

        image = QImage(max(1, round(source.width() * scale)), max(1, round(source.height() * scale)),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            painter.scale(image.width() / source.width(), image.height() / source.height())
            painter.translate(-source.topLeft())
            # Only the widget's own paintEvent: its labels are described as children.
            widget.render(painter, QPoint(), QRegion(), QWidget.RenderFlag(0))
        finally:
            painter.end()
        return image

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
                    "label": widget.accessibleName(), "tooltip": self._format_text(widget.toolTip(), plain_text)[0],
                    "enabled": widget.isEnabled(), "props": {}, "children": []}
            node["props"]["grow_x"] = bool(widget.sizePolicy().horizontalPolicy().value & 2)
            node["props"]["grow_y"] = bool(widget.sizePolicy().verticalPolicy().value & 2)
            if widget.property('managementRole'):
                node['props']['management_role'] = str(widget.property('managementRole'))
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
        elif widget.__class__.__name__ == "EffectPlaybackControls":
            # Reflow against the rendered pane's width, not the hidden Qt pane.
            node["kind"] = "row"
            node["children"] = self._widgets(widget._controls)
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
            text = self._document_text(widget)
            offset = self.models.ranges.get((identifier, ()), 0) if widget.isReadOnly() else 0
            limit = MAX_TEXT_CHARS if widget.isReadOnly() else MAX_EDITABLE_TEXT_CHARS
            if widget.isReadOnly() and widget.property("followTail"):
                revision = widget.document().revision()
                if self._text_revisions.get(identifier) != revision:
                    # New activity resumes the latest page; explicit history paging
                    # remains stable between messages. Copy still uses all text.
                    offset = max(0, len(text) - limit)
                    self.models.ranges[(identifier, ())] = offset
                    self._text_revisions[identifier] = revision
                props["follow_tail"] = True
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
            props.update(self.models.view(widget, identifier, self.widget, self.icon))
            props['empty_text'] = widget.accessibleDescription()
            if node['name'] == 'mod_management_archives':
                props['folder_states'] = dict(widget.property('modManagementFolderStates') or {})
        elif isinstance(widget, QLabel):
            node["kind"] = "label"
            text, links = self._format_text(widget.text(), plain_text) if widget.textFormat() != Qt.PlainText else (widget.text(), [])
            props.update(text=text, links=links, bold=widget.font().bold(), wrap=widget.wordWrap(),
                         image=self.image(widget.pixmap()), align=int(widget.alignment()),
                         spans=self._format_text(widget.text(), rich_spans) if widget.textFormat() != Qt.PlainText else [])
            margins = widget.contentsMargins()
            if not margins.isNull():
                props["margins"] = [margins.left(), margins.top(), margins.right(), margins.bottom()]
            if node['name'] == 'mod_management_status':
                props['management_warning'] = bool(widget.property('modManagementWarning'))
        elif isinstance(widget, QProgressBar):
            node["kind"] = "progress"
            props.update(value=widget.value(), minimum=widget.minimum(), maximum=widget.maximum(),
                         text=widget.text(), indeterminate=widget.maximum() == widget.minimum())
        elif isinstance(widget, QTabWidget):
            node["kind"] = "column" if widget.tabBar().isHidden() else "tabs"
            props.update(selected=widget.currentIndex(), tabs=[
                {"text": qt_caption(widget.tabText(i)), "enabled": widget.isTabEnabled(i),
                 "visible": widget.isTabVisible(i), "tooltip": widget.tabToolTip(i)} for i in range(widget.count())])
            child = self.widget(widget.currentWidget(), force=True)
            if child:
                child["stretch"] = 1
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
            from cdmw.ui.layout_persistence import saved_splitter_sizes

            orientation = Qt.Horizontal if widget.objectName() == "new_item_model_workspace_splitter" else None
            saved = saved_splitter_sizes(widget, orientation)
            if saved:
                props.update(sizes=saved, user_sized=True)
            props["indices"] = []
            for index in range(widget.count()):
                child = self.widget(widget.widget(index))
                if child is not None:
                    node["children"].append(child)
                    props["indices"].append(index)
        elif isinstance(widget, QMenu):
            node["kind"] = "menu"
            node["children"] = [self.action(action) for action in widget.actions() if action.isVisible()]
        elif _paints_itself(widget) and _shows_only_text(widget):
            # A custom-painted surface (a drawing, not a control): its own drawing as an
            # image, with its labels laid over it. Without this the page drew only the
            # labels, and New painting's Front view showed no frame (2026-11-17).
            node["kind"] = "picture"
            minimum = widget.minimumSize()
            image, (width, height) = self.picture(widget)
            # width/height: the drawn part the image shows; natural: the widget's own size,
            # the height a picture that does not grow keeps (grow_y follows its size policy).
            props.update(image=image, width=width, height=height,
                         natural=[min(widget.width(), 4096), min(widget.height(), 4096)],
                         min_width=min(minimum.width(), 4096), min_height=min(minimum.height(), 4096))
            layout = widget.layout()
            if layout is not None:
                child = self.layout(layout)
                node["children"] = [child] if child and child["children"] else []
            else:
                node["children"] = self._widgets(
                    child for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
                    if not child.isHidden())
        else:
            if node['name'] == 'mod_management_workspace':
                props['management_surface'] = widget.palette().color(QPalette.ToolTipBase).name()
            if isinstance(widget, QGroupBox):
                node["kind"] = "group"
                node["label"] = qt_caption(widget.title())
                props.update(checkable=widget.isCheckable(), checked=widget.isChecked(),
                             plain=bool(widget.property("guidedPage") or widget.property("titlelessSection")))
            elif isinstance(widget, QDialog) and widget.isWindow():
                from cdmw.ui.layout_persistence import native_dialog_layout

                node["kind"] = "dialog"
                node["label"] = widget.windowTitle()
                props["modal"] = widget.isModal()
                props["saved_rect"] = native_dialog_layout(widget)
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
        node["label"] = qt_caption(widget.text())
        if isinstance(widget, QToolButton) and widget.isCheckable() and widget.arrowType() != Qt.ArrowType.NoArrow:
            node["label"] = ("▾ " if widget.isChecked() else "▸ ") + qt_caption(widget.text())
        if widget.property("effectToolbarButton") and not widget.icon().isNull():
            node["tooltip"] = node["tooltip"] or qt_caption(widget.text())
            node["label"] = ""
        parent = widget.parentWidget()
        if isinstance(parent, QDialogButtonBox) and parent.standardButton(widget) == QDialogButtonBox.NoButton:
            # Qt's shared localizer handles standard button-box labels; custom
            # roles retain their source text, so translate their presentation.
            node["label"] = qt_caption(translate_active_ui_text(widget.text()))
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
                "label": qt_caption(action.text()), "tooltip": action.toolTip(), "enabled": action.isEnabled(),
                "props": {"checkable": action.isCheckable(), "checked": action.isChecked(),
                          "shortcut": action.shortcut().toString()}, "children": []}
        if action.menu() is not None:
            node["children"] = [self.action(child) for child in action.menu().actions() if child.isVisible()]
        return self.registry.publish(action, node)

    def layout(self, layout):
        children = []
        grid = isinstance(layout, (QGridLayout, QFormLayout))
        horizontal = (isinstance(layout, QBoxLayout) and layout.direction() in (QBoxLayout.LeftToRight, QBoxLayout.RightToLeft)
                      or layout.__class__.__name__ == "WrappingLayout")
        # itemAt() makes PySide retain a wrapper for Qt-owned QWidgetItems. Qt
        # can delete those items implicitly when a widget moves to another
        # layout, leaving a stale binding at an address a later QObject reuses.
        # Walk the QObjects instead, ordering them by their actual layout index.
        parent = layout.parentWidget()
        widgets = (parent.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
                   if parent is not None else QApplication.allWidgets())
        candidates = [*widgets, *(child for child in layout.children() if isinstance(child, QLayout))]
        entries = sorted(((index, child) for child in candidates if (index := layout.indexOf(child)) >= 0),
                         key=lambda entry: entry[0])
        dialog_actions = horizontal and any(isinstance(child, QDialogButtonBox) for _, child in entries)
        for index, obj in entries:
            child = self.widget(obj) if isinstance(obj, QWidget) else self.layout(obj)
            if child is None:
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
                          "dialog_actions": dialog_actions},
                "children": children}
