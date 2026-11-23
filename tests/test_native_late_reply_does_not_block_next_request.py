"""A given-up job's large late reply no longer blocks the next request (2026-11-23).

On Windows the client reads the service's stdout only while it waits for a reply. A
job it gave up on (the Mesh Editor's deferred Morph query on the Demenissian Council
Robes, after 5 s) still owes its reply; a reply larger than the stdout pipe holds
left the service blocked writing it, so it never read stdin again. The next request
(the select's native session open) then blocked writing stdin under the client's
lock, and the select, every later edit and the editor's state waited for good.

A stand-in service answers in the real protocol's order: one line per request, each
reply written whole before the next request is read.
"""

from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from cdmw.core.common import ProcessTimeoutExpired
from cdmw.modding import mesh_native_client as client

# Larger than the stdout pipe holds, so the service blocks writing it: the replies of
# set-wide edits pass the pipe's size.
LATE_REPLY_BYTES = 3 * client._WINDOWS_STDOUT_PIPE_BYTES
REQUEST_BYTES = 1024 * 1024

SERVICE = r'''
import json, sys, time
sys.stdout.write(json.dumps({"event": "ready"}) + "\n")
sys.stdout.flush()
for line in sys.stdin:
    request = json.loads(line)
    if request.get("command") == "shutdown":
        break
    payload = request.get("payload") or {}
    if payload.get("slow"):
        time.sleep(0.5)
        report = {"pad": "x" * %d}
    else:
        report = {"request_bytes": len(line)}
    sys.stdout.write(json.dumps({"status": "ok", "inline_report": report}) + "\n")
    sys.stdout.flush()
''' % LATE_REPLY_BYTES


@pytest.fixture
def stand_in_service(tmp_path, monkeypatch):
    script = tmp_path / "service.py"
    script.write_text(SERVICE, encoding="utf-8")
    binary = tmp_path / "cdmw-mesh-core.exe"
    popen = subprocess.Popen

    def start(args, *rest, **kwargs):
        if args and str(args[0]) == str(binary):
            args = [sys.executable, "-I", str(script)]
        return popen(args, *rest, **kwargs)

    monkeypatch.setattr(client.subprocess, "Popen", start)
    service = client.NativeMeshCoreServiceClient(binary)
    try:
        yield service
    finally:
        process = service._process
        if process is not None and process.poll() is None:
            process.kill()  # frees a writer still blocked on the lock, if the fix regressed
        service.shutdown()


def test_the_next_request_takes_the_late_reply_instead_of_blocking(stand_in_service) -> None:
    service = stand_in_service
    with pytest.raises(ProcessTimeoutExpired):
        service.run_inline_job("probe", {"slow": True}, timeout_seconds=0.1)
    assert service._late_replies == 1
    process = service._process
    assert process is not None and process.poll() is None

    replies: list[dict] = []
    second = threading.Thread(
        target=lambda: replies.append(
            service.run_inline_job("probe", {"pad": "y" * REQUEST_BYTES}, timeout_seconds=20.0)),
        daemon=True,
    )
    second.start()
    second.join(30.0)
    assert not second.is_alive(), "the request after a given-up job blocked writing to the service"

    assert replies and replies[0]["inline_report"]["request_bytes"] > REQUEST_BYTES
    assert service._late_replies == 0
    assert service._process is process and process.poll() is None  # the service was kept


def test_a_late_reply_that_never_comes_times_the_next_job_out_without_sending_it(stand_in_service) -> None:
    service = stand_in_service
    with pytest.raises(ProcessTimeoutExpired):
        service.run_inline_job("probe", {"slow": True}, timeout_seconds=0.1)
    service._late_replies += 1  # a reply the service will never write
    with pytest.raises(ProcessTimeoutExpired):
        service.run_inline_job("probe", {}, timeout_seconds=1.0)
    # The real late reply was taken; the missing one is still owed, and the service kept.
    assert service._late_replies == 1
    assert service._process is not None and service._process.poll() is None
