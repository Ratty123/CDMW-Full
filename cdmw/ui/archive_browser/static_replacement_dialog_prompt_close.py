"""Save-aware close lifecycle for the static replacement prompt."""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps import (
    install_static_replacement_prompt_dependencies,
)

install_static_replacement_prompt_dependencies(globals())


class _MeshEditorCloseWorker(QObject):
    result = Signal(bool, str)
    finished = Signal()

    def __init__(self, operation, *, force_without_saving: bool) -> None:
        super().__init__()
        self._operation = operation
        self._force_without_saving = bool(force_without_saving)

    @Slot()
    def run(self) -> None:
        try:
            self._operation(self._force_without_saving)
        except Exception as exc:
            self.result.emit(False, f"{type(exc).__name__}: {exc}")
        else:
            self.result.emit(True, "")
        finally:
            self.finished.emit()


class _MeshEditorSaveAwareDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mesh_editor_close_operation = None
        self._mesh_editor_close_success = None
        self._mesh_editor_close_thread = None
        self._mesh_editor_close_worker = None
        self._mesh_editor_close_pending_result = int(QDialog.Rejected)
        self._mesh_editor_close_authorized = False
        self._mesh_editor_close_result = (False, "")

    def configureMeshEditorClose(self, operation, on_success) -> None:
        self._mesh_editor_close_operation = operation
        self._mesh_editor_close_success = on_success

    def done(self, result: int) -> None:
        if self._mesh_editor_close_authorized or not callable(self._mesh_editor_close_operation):
            return super().done(result)
        if self._mesh_editor_close_thread is not None:
            return
        self._mesh_editor_close_pending_result = int(result)
        self._start_mesh_editor_close(force_without_saving=False)

    def closeEvent(self, event) -> None:
        if self._mesh_editor_close_authorized or not callable(self._mesh_editor_close_operation):
            return super().closeEvent(event)
        event.ignore()
        self.done(QDialog.Rejected)

    def _start_mesh_editor_close(self, *, force_without_saving: bool) -> None:
        operation = self._mesh_editor_close_operation
        if not callable(operation) or self._mesh_editor_close_thread is not None:
            return
        self.setEnabled(False)
        self._mesh_editor_close_result = (False, "")
        thread = QThread(self)
        worker = _MeshEditorCloseWorker(
            operation,
            force_without_saving=force_without_saving,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._record_mesh_editor_close_result)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_mesh_editor_close)
        thread.finished.connect(thread.deleteLater)
        self._mesh_editor_close_thread = thread
        self._mesh_editor_close_worker = worker
        thread.start()

    @Slot(bool, str)
    def _record_mesh_editor_close_result(self, succeeded: bool, message: str) -> None:
        self._mesh_editor_close_result = (bool(succeeded), str(message or ""))
        thread = self._mesh_editor_close_thread
        if thread is not None:
            thread.quit()

    @Slot()
    def _finish_mesh_editor_close(self) -> None:
        succeeded, message = self._mesh_editor_close_result
        self._mesh_editor_close_thread = None
        self._mesh_editor_close_worker = None
        self.setEnabled(True)
        if succeeded:
            callback = self._mesh_editor_close_success
            if callable(callback):
                callback()
            self._mesh_editor_close_authorized = True
            QDialog.done(self, self._mesh_editor_close_pending_result)
            return
        self._show_mesh_editor_save_failure(message)

    def _show_mesh_editor_save_failure(self, message: str) -> None:
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Warning)
        prompt.setWindowTitle("Mesh Editor Save Failed")
        prompt.setText("The Mesh Editor still has unsaved geometry or layer changes.")
        prompt.setInformativeText(str(message or "Saving the Mesh Editor draft failed."))
        retry_button = prompt.addButton("Retry", QMessageBox.AcceptRole)
        close_button = prompt.addButton("Close Without Saving", QMessageBox.DestructiveRole)
        prompt.addButton("Cancel", QMessageBox.RejectRole)
        prompt.exec()
        if prompt.clickedButton() is retry_button:
            self._start_mesh_editor_close(force_without_saving=False)
            return
        if prompt.clickedButton() is not close_button:
            return
        confirmed = QMessageBox.question(
            self,
            "Discard Unsaved Mesh Editor Changes?",
            "Close this Mesh Editor session without saving its latest geometry and layer changes?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed == QMessageBox.Yes:
            self._start_mesh_editor_close(force_without_saving=True)


class _EmbeddedAlignmentBuilderDialog(_MeshEditorSaveAwareDialog):
    def keyPressEvent(self, event) -> None:
        if event.key() != Qt.Key_Escape:
            return super().keyPressEvent(event)
        event.accept()


def wire_mesh_editor_session_close(dialog: object, mesh_editor_session_state: object) -> None:
    """Let the dialog close the Mesh Editor session it opened.

    Wired only when the caller passed a session-state dict and the dialog
    actually offers the hook. The same prompt is used where neither holds, and a
    missing hook there is not a fault.
    """

    if not isinstance(mesh_editor_session_state, dict) or not callable(
        getattr(dialog, "configureMeshEditorClose", None)
    ):
        return

    def _close_mesh_editor_session(force_without_saving: bool) -> None:
        session = mesh_editor_session_state.get("session")
        if session is not None and callable(getattr(session, "close", None)):
            session.close(force_without_saving=bool(force_without_saving))

    def _mesh_editor_session_closed() -> None:
        mesh_editor_session_state.clear()

    dialog.configureMeshEditorClose(_close_mesh_editor_session, _mesh_editor_session_closed)


def raise_and_activate_prompt_window(dialog: object, record_open_step) -> None:
    """Bring a standalone prompt window forward once it has been shown.

    Only for the non-embedded path. An embedded builder is revealed by
    activating the Mesh Editor tab instead, and raising it directly would fight
    that.
    """

    record_open_step("raise_before")
    dialog.raise_()
    record_open_step("raise_after")
    record_open_step("activate_before")
    dialog.activateWindow()
    record_open_step("activate_after")

