"""Remember user-sized windows and split panes in the application's portable cfg.

Watch late-created widgets too: tools, dialogs and the offscreen New Item workflow
share this policy. Only splitter gestures are saved, so responsive defaults and
temporarily hidden preview panes cannot replace a user's chosen proportions.
"""

from __future__ import annotations

import json
import weakref

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHeaderView, QSplitter, QWidget
from shiboken6 import isValid

from cdmw.ui.widgets import request_settings_sync

PREFIX = "ui/layout/v1"


def _identity(widget: QWidget) -> str:
    return f"{type(widget).__module__}.{type(widget).__qualname__}"


def _widget_identity(widget: QWidget) -> str:
    owner = widget.parentWidget()
    path = []
    child = widget
    while owner is not None:
        # Attribute names and explicit object names survive navigation changes,
        # translation, detached windows and lazy construction order.
        attribute = next((name for name, value in vars(owner).items() if value is child), "")
        siblings = [w for w in owner.children() if type(w) is type(child)]
        name = attribute or child.objectName() or f"{type(child).__name__}_{siblings.index(child)}"
        path.insert(0, name)
        if type(owner).__module__.startswith(("cdmw.", "tools.")) or (isinstance(owner, QDialog) and owner.objectName()):
            return "/".join((_identity(owner), owner.objectName() or "root", *path))
        child, owner = owner, owner.parentWidget()
    return "/".join((_identity(child), child.objectName() or "root", *path))


def _sizes(value: object, count: int) -> list[int]:
    try:
        sizes = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    if (not isinstance(sizes, list) or len(sizes) != count
            or any(type(n) is not int or not 0 <= n <= 65535 for n in sizes)
            or not any(sizes)):
        return []
    return sizes


def layout_policy() -> UiLayoutPersistence | None:
    app = QApplication.instance()
    policy = getattr(app, "_cdmw_layout_persistence", None)
    return policy if policy is not None and isValid(policy) else None


def remember_splitter_resize(splitter: QSplitter, sizes=None, orientation=None) -> None:
    """Native presentation gestures use setSizes(), which emits no Qt signal."""
    policy = layout_policy()
    if policy is not None:
        policy.save_splitter(splitter, sizes, orientation)


def saved_splitter_sizes(splitter: QSplitter, orientation=None) -> list[int]:
    policy = layout_policy()
    if policy is None or not policy.splitters_enabled():
        return []
    return policy.splitter_sizes(splitter, orientation)


def restore_splitter_layout(splitter: QSplitter) -> bool:
    policy = layout_policy()
    return policy.restore_splitter(splitter) if policy is not None else False


def ensure_header_layout(header: QHeaderView) -> None:
    policy = layout_policy()
    if policy is not None:
        policy.watch_header(header)


def remember_header_resize(header: QHeaderView) -> None:
    policy = layout_policy()
    if policy is not None:
        policy.save_header(header)


def restore_header_layout(header: QHeaderView) -> bool:
    policy = layout_policy()
    return policy.restore_header(header) if policy is not None else False


def native_dialog_layout(dialog: QDialog, rect=None) -> list[int]:
    """Rust dialog coordinates are logical client pixels, separate from Qt frames."""
    policy = layout_policy()
    if policy is None:
        return []
    key = f"{PREFIX}/native_dialogs/{_identity(dialog)}/{dialog.objectName() or 'geometry'}"
    if rect is not None:
        policy.settings.setValue(key, json.dumps(rect))
        request_settings_sync(policy.settings)
        return rect
    try:
        value = json.loads(str(policy.settings.value(key, "[]")))
    except (ValueError, TypeError):
        return []
    if (not isinstance(value, list) or len(value) != 4
            or any(type(n) is not int or abs(n) > 32768 for n in value)
            or not 120 <= value[2] <= 16000 or not 80 <= value[3] <= 16000):
        return []
    return value


class UiLayoutPersistence(QObject):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._splitters = weakref.WeakKeyDictionary()
        self._windows = weakref.WeakKeyDictionary()
        self._headers = weakref.WeakKeyDictionary()
        self._pending = weakref.WeakSet()
        self._restoring = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._restore_pending)

    def splitters_enabled(self) -> bool:
        value = self.settings.value("preferences/remember_splitter_sizes", True)
        return str(value).strip().lower() not in {"false", "0", "no", "off"}

    def _splitter_key(self, splitter: QSplitter, orientation=None) -> str:
        if splitter not in self._splitters:
            self._splitters[splitter] = (_widget_identity(splitter), splitter.orientation())
            reference = weakref.ref(splitter)

            def moved(*_args):
                widget = reference()
                if widget is not None and isValid(widget) and isValid(self):
                    self.save_splitter(widget)

            splitter.splitterMoved.connect(moved)
        identity, _orientation = self._splitters[splitter]
        direction = "horizontal" if (orientation or splitter.orientation()) == Qt.Horizontal else "vertical"
        return f"{PREFIX}/splitters/{identity}/{direction}"

    def watch_header(self, header: QHeaderView) -> None:
        if header.orientation() != Qt.Horizontal or header.property("cdmwColumnSettingsKey"):
            return  # Preserve existing table-specific settings and column order.
        if header not in self._headers:
            key = f"{PREFIX}/columns/{_widget_identity(header.parentWidget())}"
            self._headers[header] = (key, -1)
            reference = weakref.ref(header)

            def resized(*_args):
                current = reference()
                if current is not None and isValid(current) and isValid(self) and QApplication.mouseButtons() & Qt.LeftButton:
                    self.save_header(current)

            header.sectionResized.connect(resized)
        key, count = self._headers[header]
        if count == header.count():
            return
        self._headers[header] = (key, header.count())
        self.restore_header(header)

    def restore_header(self, header: QHeaderView) -> bool:
        if header not in self._headers:
            self.watch_header(header)
        entry = self._headers.get(header)
        if entry is None:
            return False
        key, _count = entry
        widths = _sizes(self.settings.value(key), header.count())
        previous = self._restoring
        self._restoring = True
        try:
            for i, width in enumerate(widths):
                if width > 0 and header.sectionResizeMode(i) == QHeaderView.Interactive:
                    header.resizeSection(i, width)
        finally:
            self._restoring = previous
        return bool(widths)

    def save_header(self, header: QHeaderView) -> None:
        if self._restoring:
            return
        self.watch_header(header)
        if header not in self._headers:
            return
        widths = [header.sectionSize(i) if header.sectionResizeMode(i) == QHeaderView.Interactive else 0
                  for i in range(header.count())]
        if any(widths):
            self.settings.setValue(self._headers[header][0], json.dumps(widths))
            request_settings_sync(self.settings)

    def save_splitter(self, splitter: QSplitter, sizes=None, orientation=None) -> None:
        if self._restoring or not self.splitters_enabled():
            return
        key = self._splitter_key(splitter, orientation)
        sizes = list(sizes) if sizes is not None else splitter.sizes()
        previous = _sizes(self.settings.value(key), splitter.count())
        hidden = [splitter.widget(i).isHidden() for i in range(splitter.count())]
        # Hiding the comparison/library pane is not a resize to zero.
        for i in range(len(sizes)):
            if splitter.widget(i).isHidden() and previous:
                sizes[i] = previous[i]
        if any(sizes):
            self.settings.setValue(key, json.dumps(sizes))
            self.settings.setValue(f"{key}/hidden", json.dumps(hidden))
            request_settings_sync(self.settings)

    def splitter_sizes(self, splitter: QSplitter, orientation=None) -> list[int]:
        key = self._splitter_key(splitter, orientation)
        sizes = _sizes(self.settings.value(key), splitter.count())
        if not sizes:
            return []
        try:
            hidden = json.loads(str(self.settings.value(f"{key}/hidden", "[]")))
        except (ValueError, TypeError):
            hidden = []
        if isinstance(hidden, list) and len(hidden) == len(sizes):
            current = splitter.sizes()
            for i, was_hidden in enumerate(hidden):
                if was_hidden is True and sizes[i] == 0 and not splitter.widget(i).isHidden():
                    # A never-opened context/comparison pane had no user size.
                    # Keep its opening default; zero was not a collapse gesture.
                    sizes[i] = current[i] or 100
        return sizes

    def restore_splitter(self, splitter: QSplitter) -> bool:
        self._splitter_key(splitter)
        identity, _orientation = self._splitters[splitter]
        self._splitters[splitter] = (identity, splitter.orientation())
        sizes = self.splitter_sizes(splitter) if self.splitters_enabled() else []
        if not sizes:
            return False
        previous = self._restoring
        self._restoring = True
        try:
            splitter.setSizes(sizes)
        finally:
            self._restoring = previous
        return True

    def restore_visible_splitters(self) -> None:
        for splitter in list(self._splitters):
            if isValid(splitter) and splitter.isVisible():
                self.restore_splitter(splitter)

    def watch_window(self, window: QWidget, key: str, *, restore: bool = True) -> None:
        if window in self._windows:
            return
        self._windows[window] = (key, not restore)
        if restore:
            self._schedule(window)

    def _window_key(self, window: QWidget) -> str:
        if not window.isWindow() or window.testAttribute(Qt.WA_DontShowOnScreen):
            return ""
        if window.windowType() not in (Qt.Window, Qt.Dialog, Qt.Tool):
            return ""
        if hasattr(window, "tool_key") and hasattr(window, "owner"):
            return f"window/detached/{window.tool_key}/geometry"
        if (not type(window).__module__.startswith(("cdmw.", "tools."))
                and not (isinstance(window, QDialog) and window.objectName())):
            return ""
        if window.minimumSize() == window.maximumSize():
            return ""
        return f"{PREFIX}/windows/{_identity(window)}/{window.objectName() or 'geometry'}"

    def _schedule(self, widget: QWidget) -> None:
        self._pending.add(widget)
        if not self._timer.isActive():
            self._timer.start(0)

    def _restore_pending(self) -> None:
        pending = tuple(self._pending)
        self._pending.clear()
        # Restore windows first so child splitter proportions use final bounds.
        for widget in pending:
            if not isValid(widget) or widget not in self._windows:
                continue
            key, ready = self._windows[widget]
            if not ready:
                geometry = self.settings.value(key)
                if geometry:
                    self._restoring = True
                    try:
                        widget.restoreGeometry(geometry)
                    except (TypeError, ValueError):
                        pass  # A malformed setting must not prevent opening a tool.
                    finally:
                        self._restoring = False
                self._windows[widget] = (key, True)
        for widget in pending:
            if isValid(widget) and isinstance(widget, QSplitter):
                self.restore_splitter(widget)
            elif isValid(widget) and isinstance(widget, QHeaderView):
                self.watch_header(widget)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if self._restoring or not isinstance(watched, QWidget) or not isValid(watched):
            return False
        kind = event.type()
        if kind == QEvent.Show:
            if isinstance(watched, QSplitter):
                self._splitter_key(watched)
                self._schedule(watched)
            elif isinstance(watched, QHeaderView):
                self._schedule(watched)
            elif watched not in self._windows:
                key = self._window_key(watched)
                if key:
                    self.watch_window(watched, key)
        elif kind in (QEvent.Resize, QEvent.LayoutRequest):
            splitter = watched if watched in self._splitters else watched.parentWidget()
            if splitter in self._splitters and self._splitters[splitter][1] != splitter.orientation():
                self._schedule(splitter)
        if kind in (QEvent.Resize, QEvent.Move, QEvent.WindowStateChange, QEvent.Hide, QEvent.Close):
            entry = self._windows.get(watched)
            if entry is not None and entry[1] and not watched.isMinimized():
                self.settings.setValue(entry[0], watched.saveGeometry())
                request_settings_sync(self.settings)
        return False

    def flush(self) -> None:
        self.settings.sync()


def install_layout_persistence(window, settings) -> UiLayoutPersistence:
    app = QApplication.instance()
    previous = layout_policy()
    if previous is not None:
        app.removeEventFilter(previous)
    policy = UiLayoutPersistence(settings, window)
    app._cdmw_layout_persistence = policy
    app.installEventFilter(policy)
    # The shell already restores this legacy key before its first show.
    policy.watch_window(window, "window/geometry", restore=False)
    return policy
