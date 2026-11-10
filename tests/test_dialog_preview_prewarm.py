import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.preview import dotnet_host_prewarm as prewarm
from cdmw.ui.preview.dotnet_host import RustPreviewHostFrame
from cdmw.ui.preview.dotnet_session import RustPreviewSessionController
from cdmw.ui.preview.profile import DotNetPreviewProfile
from tests.test_dotnet_preview_shared_host import _FakeProcess, _make_ready, _package, _resolution


@pytest.fixture
def spare(tmp_path, monkeypatch):
    application = QApplication.instance()
    executable = tmp_path / "helper.exe"
    executable.write_bytes(b"helper")
    package = _package(tmp_path, "prewarm")
    tasks = []
    processes = []

    def process_factory(parent):
        process = _FakeProcess(parent)
        processes.append(process)
        return process

    monkeypatch.setattr(prewarm.QThreadPool, "globalInstance", lambda: type("Pool", (), {"start": lambda _, task: tasks.append(task)})())
    monkeypatch.setattr(prewarm, "build_rust_preview_prewarm_package", lambda _: package)
    monkeypatch.setattr("cdmw.ui.preview.dotnet_session.resolve_rust_mesh_editor", lambda _: _resolution(executable))
    monkeypatch.setattr("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", lambda _: "")
    monkeypatch.setattr("cdmw.services.mesh_rust_contract.resolve_rust_mesh_editor", lambda _: _resolution(executable))
    monkeypatch.setattr("cdmw.services.mesh_rust_contract.validate_rust_mesh_editor_package", lambda _: "")
    monkeypatch.setattr("cdmw.ui.preview.dotnet_session.RustPreviewSessionController", lambda **kwargs: RustPreviewSessionController(**kwargs, process_factory=process_factory))
    pool = prewarm.DialogPreviewPrewarm(application)
    monkeypatch.setattr(pool, "_reparent", lambda controller, parent_hwnd: True)
    pool.ensure(tmp_path, executable)
    yield pool, tasks, processes, executable
    pool.shutdown()
    if getattr(application, "_cdmw_dialog_preview_prewarm", None) is pool:
        del application._cdmw_dialog_preview_prewarm
    pool.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _ready(pool, tasks):
    tasks.pop().run()
    controller = pool._controller
    _make_ready(controller)
    controller._capabilities.add("dialog_prewarm_hold_v1")
    pool._state_changed("prewarmed", "")
    return controller


def test_one_hidden_spare_is_adopted_by_dialog_without_relaunch(spare, tmp_path):
    pool, tasks, processes, executable = spare
    pool.ensure(tmp_path, executable)
    assert len(tasks) == 1
    controller = _ready(pool, tasks)
    assert not pool._parking.isVisible()
    assert processes[0].writes[-1]["event"] == "prewarm_hold_request"
    QApplication.instance()._cdmw_dialog_preview_prewarm = pool
    host = RustPreviewHostFrame(profile=DotNetPreviewProfile.AUTHORING,
        configured_executable=executable, terminate_on_close=True)
    try:
        assert host.controller is controller
        assert controller.parent() is host
        assert pool._controller is None
        assert len(processes) == 1
        assert controller.set_authoritative_session_id("real-edit-session")
        assert controller.is_running
        assert processes[0].writes[-1]["event"] == "preview_session_state"
        assert processes[0].writes[-1]["session_id"] == "real-edit-session"
        assert controller.process_generation == 1
        pool.shutdown()
        assert controller.is_running  # The adopted dialog owns it now.
    finally:
        host.close()
        shiboken6.delete(host)
    assert not processes[0].state().value


@pytest.mark.parametrize("state", ["not_ready", "real_package", "changed_executable", "failed_transfer", "invalid_provenance"])
def test_unusable_spare_is_never_adopted(spare, tmp_path, state, monkeypatch):
    pool, tasks, processes, executable = spare
    controller = _ready(pool, tasks)
    if state == "not_ready":
        controller._renderer_ready = False
    elif state == "real_package":
        controller._desired_package = _package(tmp_path, "real")
    elif state == "changed_executable":
        executable.write_bytes(b"changed")
    elif state == "failed_transfer":
        monkeypatch.setattr(pool, "_reparent", lambda *_: False)
    else:
        monkeypatch.setattr("cdmw.services.mesh_rust_contract.validate_rust_mesh_editor_package", lambda _: "changed manifest")
    owner = QWidget()
    try:
        assert pool.take(parent=owner, host_hwnd=lambda: 1, profile="preview",
            configured=executable, terminate_on_close=True, direct_authoring=False) is None
        assert controller.parent() is pool
        if state in {"changed_executable", "failed_transfer", "invalid_provenance"}:
            assert not controller.is_running
    finally:
        shiboken6.delete(owner)


def test_shutdown_ignores_late_background_completion(spare):
    pool, tasks, processes, _ = spare
    pool.shutdown()
    tasks.pop().run()
    assert not processes
    assert pool._controller is None


def test_failed_launch_leaves_no_waiting_helper(spare, monkeypatch):
    pool, tasks, processes, _ = spare
    monkeypatch.setattr("cdmw.ui.preview.dotnet_session.validate_rust_mesh_editor_package", lambda _: "invalid provenance")
    tasks.pop().run()
    assert not processes
    assert pool._controller is None


def test_exited_spare_is_discarded_and_can_be_prepared_again(spare, tmp_path):
    pool, tasks, processes, executable = spare
    controller = _ready(pool, tasks)
    processes[0].terminate()
    processes[0].finished.emit(1, None)
    assert pool._controller is None
    pool.ensure(tmp_path, executable)
    assert len(tasks) == 1
