"""P4 V1: the pre-started Mesh Editor helper is adopted, replaced or released safely.

A stand-in helper script plays the helper's side of ``--cdmw-session-pending``:
it says ``pending_ready``, then echoes the ``open_session`` it receives.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from cdmw.services.mesh_rust_contract import RUST_MESH_EDITOR_PROTOCOL
from cdmw.ui.mesh_editor.tab_rust_process import _RustEditorSpare

HELPER = f'''
import json, sys, time
mode, delay = sys.argv[1], float(sys.argv[2])
assert sys.argv[3:5] == ["--cdmw-session-pending", "--embedded-parent-hwnd"], sys.argv
if mode == "crash_before":
    time.sleep(delay)
    sys.exit(3)
time.sleep(delay)
print(json.dumps({{"event": "pending_ready", "protocol": "{RUST_MESH_EDITOR_PROTOCOL}",
                  "child_hwnd": 11, "embedded_parent_hwnd": int(sys.argv[5])}}), flush=True)
if mode == "crash_after":
    sys.exit(4)
line = sys.stdin.readline()
print(json.dumps({{"event": "received", "line": json.loads(line) if line else None}}), flush=True)
sys.stdin.readline()
'''


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, condition, timeout=15.0):
    deadline = time.time() + timeout
    while not condition():
        if time.time() > deadline:
            raise AssertionError("timed out")
        app.processEvents()
        time.sleep(0.01)


def start(spare, tmp_path, mode, delay=0.0):
    script = tmp_path / "helper.py"
    script.write_text(HELPER, encoding="utf-8")
    process = QProcess()
    spare.start(process, Path(sys.executable), "signature", 5, arguments_prefix=(str(script), mode, str(delay)))
    return process


def test_a_waiting_spare_is_handed_over_and_receives_its_session(app, tmp_path):
    spare = _RustEditorSpare()
    process = start(spare, tmp_path, "ok")
    wait_for(app, lambda: spare.state == "pending")
    assert spare.matches(Path(sys.executable), "signature", 5)
    assert not spare.matches(Path(sys.executable), "other", 5) and not spare.matches(Path(sys.executable), "signature", 6)
    adopted = []
    assert spare.adopt(lambda p, announcement: adopted.append((p, announcement)), lambda: adopted.append("failed"))
    assert adopted[0][0] is process and adopted[0][1]["child_hwnd"] == 11
    assert spare.state == "idle" and spare.process is None
    received = []
    process.readyReadStandardOutput.connect(lambda: received.append(bytes(process.readAllStandardOutput())))
    process.write(json.dumps({"event": "open_session", "manifest": "m.json"}).encode() + b"\n")
    wait_for(app, lambda: received)
    assert json.loads(received[0])["line"]["manifest"] == "m.json"
    process.closeWriteChannel()
    assert process.waitForFinished(10_000)


def test_an_open_while_the_spare_is_still_starting_waits_for_it(app, tmp_path):
    spare = _RustEditorSpare()
    process = start(spare, tmp_path, "ok", delay=0.5)
    adopted = []
    assert spare.state == "starting"
    assert spare.adopt(lambda p, _a: adopted.append(p), lambda: adopted.append("failed"))
    assert adopted == []
    wait_for(app, lambda: adopted)
    assert adopted == [process]
    process.kill()
    process.waitForFinished(5_000)


def test_a_spare_that_exits_while_an_open_waits_hands_the_open_back(app, tmp_path):
    spare = _RustEditorSpare()
    start(spare, tmp_path, "crash_before", delay=0.3)
    outcome = []
    assert spare.adopt(lambda p, _a: outcome.append("ready"), lambda: outcome.append("failed"))
    wait_for(app, lambda: outcome)
    assert outcome == ["failed"] and spare.state == "idle" and spare.process is None


def test_a_spare_that_exits_while_pending_is_dropped(app, tmp_path):
    spare = _RustEditorSpare()
    start(spare, tmp_path, "crash_after", delay=0.1)
    wait_for(app, lambda: spare.process is None)
    assert spare.state == "idle" and not spare.matches(Path(sys.executable), "signature", 5)
    # The next open finds nothing to adopt and launches as before.
    assert not spare.adopt(lambda p, _a: None, lambda: None)


def test_releasing_a_waiting_spare_stops_it(app, tmp_path):
    spare = _RustEditorSpare()
    process = start(spare, tmp_path, "ok")
    wait_for(app, lambda: spare.state == "pending")
    spare.release()
    assert spare.process is None and spare.state == "idle"
    wait_for(app, lambda: process.state() == QProcess.ProcessState.NotRunning)


def test_the_unit_suite_turns_the_spare_off_and_journeys_leave_it_on():
    import os

    from cdmw.ui.mesh_editor import tab_rust_process

    assert os.environ.get(tab_rust_process.EDITOR_SPARE_ENV) == "0"
    assert not tab_rust_process.editor_spare_enabled()
    source = (Path(__file__).resolve().parents[1] / "cdmw" / "automation" / "client.py").read_text(encoding="utf-8")
    assert '"CDMW_EDITOR_SPARE"' in source
