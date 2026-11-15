"""Character Finder thumbnails rendered in a running preview process (P4 V5)."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from cdmw.services.engine_capture import (
    PACKAGE_CAPTURE_CAPABILITY, CaptureUnavailable, EngineCaptureRouter,
)


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class FakeController(QObject):
    protocol_event = Signal(object)
    state_changed = Signal(str, str)

    def __init__(self, *, capable=True, answer="captured", message=""):
        super().__init__()
        self.is_running = True
        self.capabilities = frozenset({PACKAGE_CAPTURE_CAPABILITY} if capable else ())
        self.sent = []
        self.answer = answer
        self.message = message

    def send_correlated(self, event, payload):
        self.sent.append((event, dict(payload)))
        request_id = len(self.sent)
        if self.answer:
            Path(payload["output"]).write_bytes(b"BM")
            QTimer.singleShot(10, lambda: self.protocol_event.emit({
                "event": "package_capture_result", "request_id": request_id,
                "status": self.answer, "message": self.message}))
        return request_id


def _capture_on_a_worker(app, router, tmp_path, **kwargs):
    outcome = {}

    def run():
        try:
            router.capture(tmp_path / "package" / "manifest.json", tmp_path / "out.bmp",
                           tmp_path / "report.json", **kwargs)
            outcome["result"] = "captured"
        except Exception as exc:  # noqa: BLE001 - the test reads the type
            outcome["result"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    while thread.is_alive():
        QCoreApplication.processEvents()
        thread.join(0.01)
    return outcome["result"]


def test_a_capture_from_a_worker_thread_is_rendered_by_the_capable_process(app, tmp_path):
    router = EngineCaptureRouter()
    plain, capable = FakeController(capable=False), FakeController()
    router.register(plain)
    router.register(capable)

    assert _capture_on_a_worker(app, router, tmp_path, size=256) == "captured"
    assert plain.sent == []
    (event, payload), = capable.sent
    assert event == "package_capture_request"
    assert payload == {"manifest": str(tmp_path / "package" / "manifest.json"),
                       "output": str(tmp_path / "out.bmp"), "report": str(tmp_path / "report.json"), "size": 256}
    assert router.pending_count() == 0


def test_without_a_capable_process_the_capture_is_unavailable_at_once(app, tmp_path):
    router = EngineCaptureRouter()
    router.register(FakeController(capable=False))
    stopped = FakeController()
    stopped.is_running = False
    router.register(stopped)

    assert isinstance(_capture_on_a_worker(app, router, tmp_path), CaptureUnavailable)


def test_a_failed_capture_raises_and_a_stopped_process_hands_its_captures_back(app, tmp_path):
    router = EngineCaptureRouter()
    failing = FakeController(answer="error", message="no adapter")
    router.register(failing)
    result = _capture_on_a_worker(app, router, tmp_path)
    assert isinstance(result, RuntimeError) and "no adapter" in str(result)

    silent = FakeController(answer="")
    router.register(silent)

    def stop_soon():
        silent.is_running = False
        silent.state_changed.emit("failed", "renderer exited")

    QTimer.singleShot(50, stop_soon)
    assert isinstance(_capture_on_a_worker(app, router, tmp_path), CaptureUnavailable)
    assert router.pending_count() == 0


def test_the_finder_uses_its_own_process_only_when_no_preview_process_takes_it(tmp_path, monkeypatch):
    from cdmw.models import ModelPreviewRenderSettings
    from cdmw.services import engine_capture
    from cdmw.workers.character_finder_workers import CharacterFinderRenderWorker

    worker = CharacterFinderRenderWorker(1, SimpleNamespace(detail=None), cache_root=tmp_path,
                                         fingerprint="fp", settings=ModelPreviewRenderSettings())
    own = []
    monkeypatch.setattr(worker, "_capture_in_own_process", lambda *args: own.append(args))
    monkeypatch.setattr(worker, "_publish_thumbnail", lambda capture, report, key: capture)
    package = SimpleNamespace(manifest_path=tmp_path / "manifest.json")

    def engine(manifest, output, report="", **_kwargs):
        Path(output).write_bytes(b"BM")

    monkeypatch.setattr(engine_capture, "capture_in_engine", engine)
    worker._capture(package, "key")
    assert own == []

    def unavailable(*_args, **_kwargs):
        raise CaptureUnavailable("no preview host")

    monkeypatch.setattr(engine_capture, "capture_in_engine", unavailable)
    worker._capture(package, "key")
    assert len(own) == 1

    def failed(*_args, **_kwargs):
        raise RuntimeError("device lost")

    monkeypatch.setattr(engine_capture, "capture_in_engine", failed)
    worker._capture(package, "key")
    assert len(own) == 2
