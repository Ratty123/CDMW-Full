"""Resizable, worker-rendered body/armor comparison for the archive picker."""

from __future__ import annotations

from pathlib import PurePosixPath

from PySide6.QtCore import QEvent, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout

from cdmw.models import ModelPreviewData
from cdmw.rendering.static_model_thumbnail import render_static_model_comparison_image
from cdmw.workers.utility_workers import UtilityWorker


class ArchiveMeshComparisonPreview(QFrame):
    """Retain decoded meshes and allow at most one render worker at a time."""

    idle = Signal()

    def __init__(self, parent=None, *, refit_role: str = "armor") -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._models = (None, None)
        self._generation = 0
        self._active = None
        self._pending = None
        self._closed = False
        self.image: QImage | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        controls = QGridLayout()
        layout.addLayout(controls)
        target_title = QLabel("Current target")
        source_title = QLabel("Body" if refit_role == "body" else "Armour")
        target_title.setStyleSheet("color: #abb8c7;")
        source_title.setStyleSheet("color: #f5b054;")
        self.target_mode_combo = QComboBox()
        self.source_mode_combo = QComboBox()
        for combo in (self.target_mode_combo, self.source_mode_combo):
            combo.addItems(["Solid", "Wire"])
        if refit_role == "armor":
            self.source_mode_combo.setCurrentIndex(1)
        else:
            self.target_mode_combo.setCurrentIndex(1)
        self._target_name = QLabel()
        self._source_name = QLabel()
        for label in (self._target_name, self._source_name):
            label.setObjectName("HintLabel")
            label.setWordWrap(True)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        controls.addWidget(target_title, 0, 0)
        controls.addWidget(self.target_mode_combo, 0, 1)
        controls.addWidget(source_title, 0, 2)
        controls.addWidget(self.source_mode_combo, 0, 3)
        controls.addWidget(self._target_name, 1, 0, 1, 2)
        controls.addWidget(self._source_name, 1, 2, 1, 2)
        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(2, 1)

        self.image_label = QLabel("Loading preview...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setMinimumSize(240, 260)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.image_label, 1)
        self._status = QLabel()
        self._status.setObjectName("HintLabel")
        # Reserve one line so loading/idle text cannot resize the image and
        # trigger another render indefinitely.
        self._status.setMinimumHeight(self._status.fontMetrics().lineSpacing())
        self._status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(self._status)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._queue_render)
        self.image_label.installEventFilter(self)
        self.target_mode_combo.currentIndexChanged.connect(self._queue_render)
        self.source_mode_combo.currentIndexChanged.connect(self._queue_render)

    @property
    def has_live_workers(self) -> bool:
        return self._active is not None

    def iter_shutdown_workers(self):
        if self._active is None:
            return ()
        _generation, worker, thread = self._active
        return (("comparison", thread, worker),)

    def set_models(
        self, target: ModelPreviewData | None, source: ModelPreviewData | None,
        *, target_note: str = "", source_note: str = "",
    ) -> None:
        if self._closed:
            return
        changed = target is not self._models[0] or source is not self._models[1]
        self._models = (target, source)
        for label, model, note in zip(
            (self._target_name, self._source_name), self._models, (target_note, source_note),
        ):
            path = str(model.path or "") if model is not None else ""
            label.setText(PurePosixPath(path.replace("\\", "/")).name if path else note)
            label.setToolTip(path or note)
        if changed or not any(model is not None for model in self._models):
            self.image = None
            self.image_label.setText("Loading preview...")
            self._queue_render()

    def _queue_render(self, *_args) -> None:
        if self._closed:
            return
        self._resize_timer.stop()
        self._generation += 1
        if not any(model is not None for model in self._models):
            self._pending = None
            if self._active is not None:
                self._active[1].stop()
            self.image = None
            self.image_label.setText("No preview available.")
            self._status.clear()
            return
        ratio = self.image_label.devicePixelRatioF()
        size = self.image_label.contentsRect().size()
        modes = ("solid", "wireframe")
        self._pending = (
            self._generation, self._models,
            max(320, min(2048, round(size.width() * ratio))),
            max(260, min(2048, round(size.height() * ratio))),
            modes[self.target_mode_combo.currentIndex()],
            modes[self.source_mode_combo.currentIndex()],
        )
        self._status.setText("Loading preview...")
        self._status.setToolTip("")
        if self._active is not None:
            self._active[1].stop()
        else:
            self._start_pending_render()

    def _start_pending_render(self) -> None:
        if self._closed or self._active is not None or self._pending is None:
            return
        generation, models, width, height, target_mode, source_mode = self._pending
        self._pending = None

        def render(_log, stop_event):
            image = render_static_model_comparison_image(
                *models, width=width, height=height,
                target_mode=target_mode, source_mode=source_mode, stop_event=stop_event,
            )
            return generation, image

        worker = UtilityWorker(render, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._completed)
        worker.error.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._active = generation, worker, thread
        thread.start()

    def _completed(self, payload) -> None:
        generation, image = payload
        if self._closed or generation != self._generation:
            return
        if not isinstance(image, QImage) or image.isNull():
            self.image = None
            self.image_label.setText("No preview available.")
            self._status.setText("No preview available.")
            return
        self.image = image
        self._sync_pixmap()
        self._status.clear()

    def _failed(self, message: str) -> None:
        if self._closed or self._active is None or self._active[0] != self._generation:
            return
        self.image = None
        self.image_label.setText("Preview unavailable.")
        self._status.setText("Preview unavailable.")
        self._status.setToolTip(str(message or "Preview unavailable."))

    def _thread_finished(self) -> None:
        self._active = None
        self._start_pending_render()
        if self._active is None:
            self.idle.emit()

    def _sync_pixmap(self) -> None:
        if self.image is None:
            return
        ratio = self.image_label.devicePixelRatioF()
        size = self.image_label.contentsRect().size() * ratio
        pixmap = QPixmap.fromImage(self.image).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap.setDevicePixelRatio(ratio)
        self.image_label.setPixmap(pixmap)

    def eventFilter(self, watched, event):
        if watched is self.image_label and event.type() == QEvent.Resize and not self._closed:
            self._sync_pixmap()
            self._resize_timer.start()
        return super().eventFilter(watched, event)

    def request_shutdown(self) -> None:
        self._closed = True
        self._generation += 1
        self._pending = None
        self._resize_timer.stop()
        if self._active is not None:
            self._active[1].stop()
