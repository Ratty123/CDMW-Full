"""Interactive, read-only body/armor comparison for the archive picker."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import tempfile
from uuid import uuid4

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from cdmw.models import ModelPreviewData
from cdmw.services.archive_mesh_comparison import build_archive_mesh_comparison
from cdmw.ui.preview.rust_host import RustPreviewHostFrame
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane, PreviewPackageCleanup
from cdmw.workers.utility_workers import UtilityWorker


class ArchiveMeshComparisonPreview(QFrame):
    """Keep one package worker; camera movement belongs to the resident viewport."""

    idle = Signal()

    def __init__(self, parent=None, *, refit_role: str = "armor") -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._models = (None, None)
        self._framed_models = (None, None)
        self._generation = 0
        self._active = None
        self._pending = None
        self._closed = False
        self._packages = set()
        self._output_root = Path(tempfile.gettempdir()) / "cdmw_archive_comparison"
        self._scene_session_id = f"archive-comparison:{uuid4().hex}"
        self._cleanup_lane = ModelSourceCleanupLane(parent=self)
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.setInterval(50)
        self._cleanup_timer.timeout.connect(self._cleanup_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        controls = QGridLayout()
        layout.addLayout(controls)
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
        controls.addWidget(QLabel("Current target"), 0, 0)
        controls.addWidget(self.target_mode_combo, 0, 1)
        controls.addWidget(QLabel("Body" if refit_role == "body" else "Armour"), 0, 2)
        controls.addWidget(self.source_mode_combo, 0, 3)
        controls.addWidget(self._target_name, 1, 0, 1, 2)
        controls.addWidget(self._source_name, 1, 2, 1, 2)
        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(2, 1)

        self.viewport = RustPreviewHostFrame(self, terminate_on_close=True)
        self.viewport.setMinimumSize(240, 260)
        layout.addWidget(self.viewport, 1)
        self.reset_view_button = QPushButton("Reset view")
        self.reset_view_button.clicked.connect(self.viewport.reset_view)
        controls.addWidget(self.reset_view_button, 0, 4)
        self._status = QLabel()
        self._status.setObjectName("HintLabel")
        self._status.setMinimumHeight(self._status.fontMetrics().lineSpacing())
        self._status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        layout.addWidget(self._status)
        self.viewport.controller.package_applied.connect(self._retire_unused_packages)
        self.target_mode_combo.currentIndexChanged.connect(self._queue_package)
        self.source_mode_combo.currentIndexChanged.connect(self._queue_package)

    @property
    def has_live_workers(self) -> bool:
        return self._active is not None or bool(self._cleanup_lane.iter_shutdown_workers())

    def iter_shutdown_workers(self):
        jobs = self._cleanup_lane.iter_shutdown_workers()
        if self._active is None:
            return jobs
        _generation, worker, thread = self._active
        return (("comparison", thread, worker), *jobs)

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
            self.viewport.clear_preview()
            self._retire_unused_packages()
            self._queue_package()

    def _queue_package(self, *_args) -> None:
        if self._closed:
            return
        self._generation += 1
        if not any(model is not None for model in self._models):
            self._pending = None
            if self._active is not None:
                self._active[1].stop()
            self._status.setText("No preview available.")
            return
        modes = ("solid", "wire")
        self._pending = (
            self._generation, self._models,
            modes[self.target_mode_combo.currentIndex()], modes[self.source_mode_combo.currentIndex()],
        )
        self._status.setText("Loading preview...")
        self._status.setToolTip("")
        if self._active is not None:
            self._active[1].stop()
        else:
            self._start_pending_package()

    def _start_pending_package(self) -> None:
        if self._closed or self._active is not None or self._pending is None:
            return
        generation, models, target_mode, source_mode = self._pending
        self._pending = None
        output_root, scene_id = self._output_root, self._scene_session_id

        def build(_log, stop_event):
            package, display_mode = build_archive_mesh_comparison(
                *models, target_mode=target_mode, source_mode=source_mode,
                output_root=output_root, scene_session_id=scene_id,
                scene_generation=generation, stop_event=stop_event,
            )
            return generation, models, package, display_mode

        worker = UtilityWorker(build, task_accepts_cancel=True)
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
        generation, models, package, display_mode = payload
        self._packages.add(package.package_dir)
        if self._closed or generation != self._generation:
            self._retire_unused_packages()
            return
        self.viewport.set_display_mode("overlay" if all(model is not None for model in models) else "replacement_only")
        self.viewport.set_viewport_display_mode(display_mode)
        reset = any(model is not old for model, old in zip(models, self._framed_models))
        if self.viewport.load_package(package, reset_view=reset):
            self._framed_models = models
            self._status.clear()
        else:
            self._status.setText("Preview unavailable.")
        self._retire_unused_packages()

    def _failed(self, message: str) -> None:
        if self._closed or self._active is None or self._active[0] != self._generation:
            return
        self._status.setText("Preview unavailable.")
        self._status.setToolTip(str(message or "Preview unavailable."))

    def _thread_finished(self) -> None:
        self._active = None
        self._start_pending_package()
        if not self.has_live_workers:
            self.idle.emit()

    def _retire_unused_packages(self, *_args) -> None:
        controller = self.viewport.controller
        keep = ({Path(path) for path in (controller.applied_package_path, controller.desired_package_path) if path}
                if not self._closed else set())
        for package in self._packages - keep:
            self._cleanup_lane.retire(PreviewPackageCleanup(package, self._output_root))
            self._packages.remove(package)
            self._cleanup_timer.start()

    def _cleanup_finished(self) -> None:
        if not self._cleanup_lane.iter_shutdown_workers():
            self._cleanup_timer.stop()
            if self._active is None:
                self.idle.emit()

    def request_shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._pending = None
        if self._active is not None:
            self._active[1].stop()
        self.viewport.controller.shutdown()
        self._retire_unused_packages()
