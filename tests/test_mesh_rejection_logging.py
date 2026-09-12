from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit

from cdmw.domain.mesh.export_validation import MeshExportValidationIssue, describe_mesh_export_issue
from cdmw.services.mesh_rust_authoring import _validation_blockers
from cdmw.ui.mesh_editor.tab_rust_editor import MeshEditorRustEditorMixin
from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
from cdmw.ui.shell.log_controller import LogControllerMixin


def _issue():
    return MeshExportValidationIssue(
        "blocker", "invalid_bone_index", "Vertex references an invalid or missing bone.",
        "skeleton", expected="0..24", actual=25, submesh_index=2, vertex_index=13,
    )


def test_validation_rejection_keeps_precise_coordinates_and_bounded_values():
    message = _validation_blockers(SimpleNamespace(blockers=(_issue(),)))[0]
    assert message == describe_mesh_export_issue(_issue())
    for detail in ("submesh_index=2", "vertex_index=13", "expected=0..24", "actual=25"):
        assert detail in message
    assert "face_index" not in message
    large = MeshExportValidationIssue("blocker", "large", "Mismatch", actual="x" * 10000)
    assert len(describe_mesh_export_issue(large)) < 200
    assert describe_mesh_export_issue(SimpleNamespace(message="Plain error")) == "Plain error"


class _Shell(LogControllerMixin):
    def __init__(self):
        self.textures = SimpleNamespace(error_message_value=QLabel(), log_view=QPlainTextEdit())
        self.compact_workspace = None

    def _refresh_dashboard(self):
        pass


class _Editor(QObject, MeshEditorRustEditorMixin, MeshEditorRustProcessMixin):
    status_message_requested = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self.standalone_status_label = QLabel()
        self.standalone_rust_protocol_request_id = 7
        self.standalone_rust_active_event = {"event": "command_request", "command": "refit_load_mesh"}
        self.standalone_rust_closing = False
        self.responses = []

    def _send_rust_error_response(self, request, message, *, recovery):
        self.responses.append((request, message, recovery))

    def _send_rust_message(self, response):
        self.responses.append(response)


def test_mesh_rejection_reaches_log_and_activity_once_through_status_signal(monkeypatch):
    app = QApplication.instance() or QApplication([])
    shell, editor = _Shell(), _Editor()
    activities = []
    monkeypatch.setattr(
        "cdmw.ui.shell.compact.workspace.append_compact_activity",
        lambda owner, message, **fields: activities.append((message, fields)),
    )
    editor.status_message_requested.connect(
        lambda message, error: shell.set_status_message(message, error=error, tool_key="mesh_editor")
    )
    try:
        message = describe_mesh_export_issue(_issue())
        editor._handle_rust_protocol_worker_error(7, 1, "command_request", message, {})
        assert len(editor.responses) == 1
        assert shell.textures.log_view.toPlainText().count(message) == 1
        assert len(activities) == 1
        assert activities[0][1]["severity"] == "error"
        assert activities[0][1]["tool_key"] == "mesh_editor"
        assert editor.standalone_status_label.text().endswith(message)
        editor._handle_rust_protocol_worker_error(6, 1, "command_request", "Stale error", {})
        assert "Stale error" not in shell.textures.log_view.toPlainText()
        assert len(activities) == 1
        editor._set_rust_status("Mesh Editor command completed.")
        assert "command completed" not in shell.textures.log_view.toPlainText()
        assert len(activities) == 2
    finally:
        for widget in (shell.textures.error_message_value, shell.textures.log_view, editor.standalone_status_label):
            widget.close()
            widget.deleteLater()
        editor.deleteLater()
        app.processEvents()


def test_archive_source_geometry_notice_survives_protocol_completion():
    app = QApplication.instance() or QApplication([])
    editor = _Editor()
    notices = []
    editor.status_message_requested.connect(lambda message, error: notices.append((message, error)))
    warning = "Loaded source geometry. Character appearance is unavailable."
    response = {"payload": {"result": {"appearance_warning": warning}}}
    try:
        editor._handle_rust_protocol_completed(6, 1, response, False)
        assert not notices
        editor._handle_rust_protocol_completed(7, 1, response, False)
        assert notices == [(warning, False)]
        assert editor.standalone_status_label.text() == warning
    finally:
        editor.standalone_status_label.close()
        editor.standalone_status_label.deleteLater()
        editor.deleteLater()
        app.processEvents()
