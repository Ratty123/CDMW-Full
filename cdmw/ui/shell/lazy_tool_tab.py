"""Lazy container for optional shell tools."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QProgressBar, QVBoxLayout, QWidget


class _LazyToolPrepareWorker(QObject):
    """Run import-only preparation without occupying the GUI thread."""

    done = Signal()

    def __init__(self, prepare: Callable[[], None], owner_thread: QThread) -> None:
        super().__init__()
        self._prepare = prepare
        self._owner_thread = owner_thread

    @Slot()
    def run(self) -> None:
        try:
            if not QThread.currentThread().isInterruptionRequested():
                self._prepare()
        except Exception:
            # The owning factory remains the authority for import errors and
            # preserves its existing unavailable/error presentation.
            pass
        finally:
            self.done.emit()

    @Slot()
    def return_to_owner_thread(self) -> None:
        current_thread = QThread.currentThread()
        if self.thread() is current_thread:
            self.moveToThread(self._owner_thread)
        current_thread.quit()


class LazyToolTab(QWidget):
    """Construct one optional tool widget when its tab first becomes visible or used."""

    def __init__(
        self,
        factory: Callable[[], QWidget],
        *,
        prepare: Callable[[], None] | None = None,
        prepare_ui: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._factory: Callable[[], QWidget] | None = factory
        self._prepare = prepare
        self._prepare_ui = prepare_ui
        self._widget: QWidget | None = None
        self._pending_widget: QWidget | None = None
        self._created_callbacks: list[Callable[[QWidget], None]] = []
        self._creating = False
        self._load_requested = False
        self._shutdown_requested = False
        self._shutdown_called = False
        self._prepare_thread: QThread | None = None
        self._prepare_worker: _LazyToolPrepareWorker | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._loading_widget = QWidget(self)
        self._loading_widget.setObjectName("LazyToolLoadingState")
        loading_layout = QVBoxLayout(self._loading_widget)
        loading_layout.addStretch(1)
        self._loading_progress = QProgressBar(self._loading_widget)
        self._loading_progress.setObjectName("LazyToolLoadingProgress")
        self._loading_progress.setRange(0, 0)
        self._loading_progress.setTextVisible(False)
        self._loading_progress.setFixedWidth(240)
        loading_layout.addWidget(
            self._loading_progress,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )
        loading_layout.addStretch(1)
        self._loading_widget.hide()
        self._layout.addWidget(self._loading_widget)

    def widget_if_created(self) -> QWidget | None:
        return self._widget

    def when_created(self, callback: Callable[[QWidget], None]) -> None:
        if self._widget is not None:
            callback(self._widget)
        else:
            self._created_callbacks.append(callback)

    def ensure_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget
        if self._creating or self._pending_widget is not None or self._factory is None:
            raise RuntimeError("Lazy tool widget construction re-entered.")
        self._load_requested = True
        self._creating = True
        try:
            widget = self._factory()
            if not isinstance(widget, QWidget):
                raise TypeError("Lazy tool factory must return QWidget.")
            self._pending_widget = widget
            self._factory = None
            widget.hide()
            self._layout.addWidget(widget)
            return self._publish_pending_widget()
        finally:
            self._creating = False

    def request_widget(self) -> None:
        """Begin first-use loading and return before imports or construction run."""

        if (
            self._widget is not None
            or self._pending_widget is not None
            or self._load_requested
            or self._shutdown_requested
        ):
            return
        self._load_requested = True
        self._loading_widget.show()
        QTimer.singleShot(0, self._start_prepare)

    @Slot()
    def _start_prepare(self) -> None:
        if self._widget is not None or self._pending_widget is not None or self._shutdown_requested:
            return
        if self._prepare is None:
            self._schedule_ui_preparation()
            return
        owner_thread = self.thread()
        thread = QThread()
        worker = _LazyToolPrepareWorker(self._prepare, owner_thread)
        worker.moveToThread(thread)
        worker.done.connect(self._prepare_completed, Qt.ConnectionType.QueuedConnection)
        worker.done.connect(
            worker.return_to_owner_thread,
            Qt.ConnectionType.DirectConnection,
        )
        thread.finished.connect(
            self._prepare_thread_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        thread.started.connect(worker.run)
        self._prepare_thread = thread
        self._prepare_worker = worker
        thread.start(QThread.Priority.LowPriority)

    @Slot()
    def _prepare_completed(self) -> None:
        if self._shutdown_requested or self._widget is not None or self._pending_widget is not None:
            return
        self._schedule_ui_preparation()

    def _schedule_ui_preparation(self) -> None:
        if self._prepare_ui is None:
            QTimer.singleShot(0, self._construct_requested_widget)
            return
        QTimer.singleShot(0, self._run_ui_preparation)

    @Slot()
    def _run_ui_preparation(self) -> None:
        if self._shutdown_requested or self._widget is not None or self._pending_widget is not None:
            return
        prepare_ui = self._prepare_ui
        self._prepare_ui = None
        if prepare_ui is not None:
            prepare_ui()
        QTimer.singleShot(0, self._construct_requested_widget)

    @Slot()
    def _prepare_thread_finished(self) -> None:
        thread = self.sender()
        if isinstance(thread, QThread):
            self._retire_prepare_thread(thread)

    def _retire_prepare_thread(self, thread: QThread) -> None:
        try:
            stopped = thread.wait(0)
        except RuntimeError:
            stopped = True
        if not stopped:
            QTimer.singleShot(1, lambda thread=thread: self._retire_prepare_thread(thread))
            return
        if self._prepare_thread is not thread:
            return
        worker = self._prepare_worker
        self._prepare_thread = None
        self._prepare_worker = None
        if worker is not None:
            worker.deleteLater()
        thread.deleteLater()

    @Slot()
    def _construct_requested_widget(self) -> None:
        if self._shutdown_requested or self._widget is not None or self._pending_widget is not None:
            return
        if self._creating or self._factory is None:
            return
        self._creating = True
        try:
            widget = self._factory()
            if not isinstance(widget, QWidget):
                raise TypeError("Lazy tool factory must return QWidget.")
            self._pending_widget = widget
            self._factory = None
            widget.hide()
            self._layout.addWidget(widget)
        finally:
            self._creating = False
        QTimer.singleShot(0, self._finish_requested_widget)

    @Slot()
    def _finish_requested_widget(self) -> None:
        if self._pending_widget is None:
            return
        self._publish_pending_widget()

    def _publish_pending_widget(self) -> QWidget:
        widget = self._pending_widget
        if widget is None:
            raise RuntimeError("Lazy tool widget construction re-entered.")
        self._pending_widget = None
        self._widget = widget
        callbacks = () if self._shutdown_requested else tuple(self._created_callbacks)
        self._created_callbacks.clear()
        for callback in callbacks:
            callback(widget)
        self._load_requested = False
        self._loading_widget.hide()
        if not self._shutdown_requested:
            widget.show()
        return widget

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        self.request_widget()
        super().showEvent(event)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") or "_factory" not in self.__dict__:
            raise AttributeError(name)
        return getattr(self.ensure_widget(), name)

    def iter_shutdown_workers(self) -> Iterable[tuple[object, object, object]]:
        workers: list[tuple[object, object, object]] = []
        if self._prepare_thread is not None:
            workers.append(("lazy tool preload", self._prepare_thread, self._prepare_worker))
        widget = self._widget or self._pending_widget
        iterator = getattr(widget, "iter_shutdown_workers", None) if widget is not None else None
        if callable(iterator):
            workers.extend(tuple(iterator()))
        return tuple(workers)

    def request_shutdown(self) -> None:
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        if self._prepare_thread is not None:
            self._prepare_thread.requestInterruption()
        widget = self._widget or self._pending_widget
        request = getattr(widget, "request_shutdown", None) if widget is not None else None
        if callable(request):
            request()

    def shutdown(self) -> None:
        if self._shutdown_called:
            return
        self._shutdown_called = True
        self.request_shutdown()
        widget = self._widget or self._pending_widget
        shutdown = getattr(widget, "shutdown", None) if widget is not None else None
        if callable(shutdown):
            shutdown()

    def flush_settings_save(self) -> None:
        widget = self._widget or self._pending_widget
        flush = getattr(widget, "flush_settings_save", None) if widget is not None else None
        if callable(flush):
            flush()


def created_tool_widget(widget: object) -> QWidget | None:
    if isinstance(widget, LazyToolTab):
        return widget.widget_if_created()
    return widget if isinstance(widget, QWidget) else None


def as_label(title: str) -> str:
    """A tool title as Qt should *draw* it, not read it.

    Tab bars and menu items treat `&` as a mnemonic marker: it vanishes and underlines the
    next letter. "Placement & Animation Studio" therefore appeared as
    "Placement_Animation Studio", which read as the tool's actual name. Doubling escapes it.

    Titles are stored unescaped — window titles and labels do not interpret `&`, and would
    show the doubled one literally — so escaping belongs at the two places that draw them.
    """

    return str(title).replace("&", "&&")


__all__ = ["LazyToolTab", "as_label", "created_tool_widget"]
