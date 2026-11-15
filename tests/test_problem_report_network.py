"""The problem report's standard-library transport, against a local HTTP server."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from cdmw.workers.problem_report_network import (
    ReportHttpResult,
    ReportNetworkRequest,
    _active_requests,
    send_report_request,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout: float = 5.0) -> None:
    start = time.monotonic()
    while not predicate():
        assert time.monotonic() - start < timeout
        QTest.qWait(1)
        time.sleep(0.005)


class _Recorder(BaseHTTPRequestHandler):
    seen: list[dict] = []
    release = threading.Event()

    def log_message(self, *args) -> None:
        pass

    def _record(self, body: bytes) -> None:
        type(self).seen.append(
            {
                "method": self.command,
                "path": self.path,
                "content_type": self.headers.get("Content-Type"),
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )

    def _answer(self, status: int, payload: bytes, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _route(self, body: bytes) -> None:
        self._record(body)
        if self.path == "/ok":
            self._answer(200, b'{"status":"accepted"}')
        elif self.path == "/created":
            self._answer(201, b'{"status":"accepted"}')
        elif self.path == "/limit":
            self._answer(429, b'{"retry_after":30}', {"Retry-After": "7"})
        elif self.path == "/refused":
            self._answer(409, b'{"code":"already_reported"}')
        elif self.path == "/redirect":
            port = self.server.server_port
            self._answer(307, b"", {"Location": f"http://127.0.0.1:{port}/unexpected-destination"})
        elif self.path == "/slow":
            type(self).release.wait(5)
            self._answer(200, b"{}")
        else:
            self._answer(404, b"")

    def do_GET(self) -> None:
        self._route(b"")

    def do_POST(self) -> None:
        self._route(self.rfile.read(int(self.headers.get("Content-Length", "0"))))


@pytest.fixture()
def server():
    _Recorder.seen = []
    _Recorder.release = threading.Event()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        _Recorder.release.set()
        httpd.shutdown()
        httpd.server_close()
        thread.join(2)


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # The transport honours the system proxy like the app's other urllib use;
    # keep a developer's proxy variables away from the local server.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


def test_post_sends_the_exact_body_as_json_with_the_ticket(server):
    payload = json.dumps({"report_id": "r-1", "text": "ü"}).encode("utf-8")
    result = send_report_request(server + "/ok", payload, ticket="r-1.ticket")
    assert result == ReportHttpResult(200, b'{"status":"accepted"}', "", "")
    assert result.ok
    (seen,) = _Recorder.seen
    assert seen == {
        "method": "POST",
        "path": "/ok",
        "content_type": "application/json",
        "authorization": "Bearer r-1.ticket",
        "body": payload,
    }


def test_get_without_ticket_sends_no_authorization(server):
    result = send_report_request(server + "/created")
    assert (result.status, result.ok) == (201, True)
    (seen,) = _Recorder.seen
    assert (seen["method"], seen["authorization"], seen["body"]) == ("GET", None, b"")


def test_http_errors_keep_status_body_and_retry_after(server):
    limited = send_report_request(server + "/limit", b"{}")
    assert limited == ReportHttpResult(429, b'{"retry_after":30}', "7", "")
    assert not limited.ok
    refused = send_report_request(server + "/refused", b"{}")
    assert (refused.status, refused.body, refused.error) == (409, b'{"code":"already_reported"}', "")


def test_redirects_are_returned_not_followed(server):
    result = send_report_request(server + "/redirect", b"{}", ticket="secret")
    assert result.status == 307 and not result.ok and not result.error
    assert [entry["path"] for entry in _Recorder.seen] == ["/redirect"]


def test_no_server_is_status_zero_with_a_reason():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    result = send_report_request(f"http://127.0.0.1:{port}/reports", b"{}", timeout=2)
    assert result.status == 0 and result.body == b"" and result.error


def test_timeout_is_status_zero(server):
    result = send_report_request(server + "/slow", b"{}", timeout=0.2)
    assert result.status == 0 and result.error


def test_request_finishes_once_on_the_ui_thread_and_is_released(server):
    _app()
    request = ReportNetworkRequest(server + "/ok", b"{}")
    results: list[tuple[object, bool]] = []
    request.finished.connect(lambda result: results.append((result, QThread.currentThread() is request.thread())))
    request.start()
    assert request in _active_requests
    _wait_until(lambda: results and request not in _active_requests)
    assert len(results) == 1
    result, on_owner_thread = results[0]
    assert on_owner_thread and isinstance(result, ReportHttpResult) and result.status == 200


def test_shipped_source_does_not_import_qt_network():
    import ast
    from pathlib import Path

    offenders = []
    roots = (Path("cdmw_app.py"), Path("cdmw"), Path("tools/placement_studio"), Path("tools/translation_studio"))
    for root in roots:
        for path in [root] if root.suffix == ".py" else sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
                if any(name == "PySide6.QtNetwork" or name.startswith("PySide6.QtNetwork.") for name in names):
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_abort_finishes_at_once_and_drops_the_late_answer(server):
    _app()
    request = ReportNetworkRequest(server + "/slow", b"{}")
    results: list[ReportHttpResult] = []
    request.finished.connect(results.append)
    request.start()
    _wait_until(lambda: _Recorder.seen)
    request.abort()
    assert results == [ReportHttpResult(error="aborted")]
    assert request.is_finished
    request.abort()
    _Recorder.release.set()
    _wait_until(lambda: request not in _active_requests)
    QTest.qWait(20)
    assert results == [ReportHttpResult(error="aborted")]
