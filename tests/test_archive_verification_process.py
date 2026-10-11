"""Real child verification, witness handoff, and owned startup cancellation."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

import pytest

from cdmw.core.archive_resident_index import ResidentArchiveIndex
from cdmw.domain.cancellation import RunCancelled
from cdmw.services import archive_verification_process as owner
from cdmw.services.new_item_provenance import SourceTracker, StaleNewItemSource
from cdmw.services.new_item_service import NewItemService
from cdmw.workers.new_item_lookup import NewItemPreloadGate
from cdmw.workers.new_item_workers import snapshot_task
from tests.archive_resident_index_fixtures import write_resident_index
from tests.test_archive_resident_index import catalogue
from tests.test_independent_item_index_witness import index_fixture, replace_index
from tests.test_new_item_service import TEMPLATE, _read


@pytest.fixture(autouse=True)
def owned_spool(monkeypatch, tmp_path):
    monkeypatch.setattr(owner, "TemporaryDirectory", lambda **kw: tempfile.TemporaryDirectory(dir=tmp_path, **kw))
    yield
    assert not tuple(tmp_path.glob("cdmw_archive_verification_*"))


def test_snapshot_uses_real_child_and_reuses_verified_tables(catalogue, monkeypatch):
    root, entries, source = catalogue
    expected = NewItemService().build_snapshot(entries, read_entry=_read)
    runs = []
    original = owner.run_process_with_cancellation

    def run(*args, **kwargs):
        runs.append(True)
        return original(*args, **kwargs)

    def reject_parent_parse(*args, **kwargs):
        pytest.fail("Full index comparison ran in the GUI process")

    monkeypatch.setattr(owner, "run_process_with_cancellation", run)
    monkeypatch.setattr(ResidentArchiveIndex, "verify_parsed_indexes", reject_parent_parse)
    monkeypatch.setattr(SourceTracker, "parse_index", reject_parent_parse)
    service = NewItemService()
    task = snapshot_task((), service=service, read_entry=_read, package_root=root, resident_source=source)
    actual = task(lambda _: None, threading.Event())
    reused = task(lambda _: None, threading.Event())
    assert runs == [True]
    assert actual.rows == expected.rows == reused.rows
    assert actual._template_search_catalogue == expected._template_search_catalogue
    assert actual.provenance.capture().indexes == expected.provenance.capture().indexes
    assert reused is not actual and reused._contexts is not actual._contexts
    assert actual.has_entry("unrelated/textures/image_1.dds")


@pytest.mark.parametrize("change", ["offset", "flags", "path", "duplicate", "missing"])
def test_child_keeps_exact_coordinate_and_inventory_checks(catalogue, tmp_path, change):
    root, entries, _ = catalogue
    rows = list(entries)
    if change == "duplicate":
        rows.append(rows[0])
    elif change == "missing":
        rows.pop()
    else:
        value = {"offset": rows[0].offset + 1, "flags": rows[0].flags ^ 16,
                 "path": rows[0].path + ".changed"}[change]
        rows[0] = replace(rows[0], **{change: value})
    source = write_resident_index(root, rows, tmp_path / "mismatch")
    tracker = SourceTracker(None)
    with pytest.raises(StaleNewItemSource, match="no longer matches|missing"):
        owner.verify_resident_catalogue(source.open(), tracker)
    assert not tracker.capture().indexes


def test_source_replacement_after_child_verification_is_rejected(tmp_path, monkeypatch):
    from cdmw.core.archive_format import parse_archive_pamt

    pamt, original_bytes, changed = index_fixture(tmp_path)
    source = write_resident_index(pamt.parent.parent, parse_archive_pamt(pamt), tmp_path / "generation")
    original = owner.run_process_with_cancellation

    def replace_after_verification(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result[0] == 0
        replace_index(pamt, changed, True)
        return result

    monkeypatch.setattr(owner, "run_process_with_cancellation", replace_after_verification)
    with pytest.raises(StaleNewItemSource, match="index changed since parsing"):
        owner.verify_resident_catalogue(source.open(), SourceTracker(None))
    assert hashlib.sha256(original_bytes).digest() != hashlib.sha256(pamt.read_bytes()).digest()


@pytest.mark.parametrize("failure", ["exit", "missing", "generation", "witness", "late_cancel", "mapping"])
def test_failed_stale_or_cancelled_result_is_not_adopted(catalogue, monkeypatch, failure):
    _, _, source = catalogue
    index = source.open()
    stop = threading.Event()

    def run(command, **kwargs):
        if failure == "exit":
            return 7, "", "owned child failure"
        request = Path(command[command.index("--input") + 1])
        output = Path(command[command.index("--output") + 1])
        if failure == "missing":
            return 0, "", ""
        assert owner.run_archive_verification_worker(request, output) == 0
        result = json.loads(output.read_text())
        if failure == "generation":
            result["source"]["fingerprint"] = "another generation"
        elif failure == "witness":
            result["indexes"] = []
        elif failure == "late_cancel":
            stop.set()
        else:
            monkeypatch.setattr(index, "verification_digest", lambda *args: "changed")
        output.write_text(json.dumps(result))
        return 0, "", ""

    tracker = SourceTracker(None)
    monkeypatch.setattr(owner, "run_process_with_cancellation", run)
    error = RunCancelled if failure == "late_cancel" else (RuntimeError if failure in {"exit", "missing"} else StaleNewItemSource)
    with pytest.raises(error):
        owner.verify_resident_catalogue(index, tracker, stop_event=stop)
    assert not tracker.capture().indexes


@pytest.mark.parametrize("finish", ["resume", "promote", "cancel", "control_failure"])
def test_controller_pauses_real_child_and_retires_it_before_cleanup(catalogue, tmp_path, monkeypatch, finish):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.new_item.controller import NewItemStudioController

    root, _, source = catalogue
    progress = tmp_path / "child-progress"
    child_pid = tmp_path / "child-pid"
    # Hold the real verifier at its cancellation checkpoints long enough to
    # exercise pause/resume and close deterministically with a small fixture.
    script = "\n".join([
        "import os, sys, time",
        "from pathlib import Path",
        "from cdmw.core.archive_resident_index import ResidentArchiveIndex",
        "from cdmw.domain.cancellation import raise_if_cancelled",
        "from cdmw.services.archive_verification_process import run_archive_verification_worker",
        "original = ResidentArchiveIndex.verify_parsed_indexes",
        "def verify(self, parse, *, stop_event=None):",
        f"    Path({str(child_pid)!r}).write_text(str(os.getpid()))",
        "    for step in range(100):",
        "        raise_if_cancelled(stop_event)",
        f"        Path({str(progress)!r}).write_text(str(step))",
        "        time.sleep(.01)",
        "    return original(self, parse, stop_event=stop_event)",
        "ResidentArchiveIndex.verify_parsed_indexes = verify",
        "sys.exit(run_archive_verification_worker(Path(sys.argv[1]), Path(sys.argv[2])))",
    ])
    monkeypatch.setattr(owner, "_worker_command", lambda request, output: [sys.executable, "-c", script, str(request), str(output)])
    original_runner = owner.run_process_with_cancellation
    monkeypatch.setattr(owner, "run_process_with_cancellation", lambda *a, **kw: original_runner(*a, **kw, timeout_seconds=10))
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(service=NewItemService())
    failures = []
    controller.snapshot_failed.connect(failures.append)
    gate = NewItemPreloadGate()
    ticks = []
    timer = QTimer(); timer.setInterval(10); timer.timeout.connect(lambda: ticks.append(True)); timer.start()

    def pump(predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.001)
        assert predicate()

    try:
        assert controller.start_snapshot((), package_root=root, resident_source=source, preload_gate=gate)
        pump(lambda: progress.exists())
        gate.pause()
        until = time.monotonic() + .4
        pump(lambda: time.monotonic() >= until)
        paused_at, tick_count = progress.read_text(), len(ticks)
        until = time.monotonic() + .15
        pump(lambda: time.monotonic() >= until)
        assert progress.read_text() == paused_at
        assert len(ticks) > tick_count and controller.snapshot is None
        if finish == "cancel":
            controller.request_shutdown()
        elif finish == "control_failure":
            def cannot_write(*args):
                raise OSError("owned control channel failure")
            monkeypatch.setattr(owner, "_write_state", cannot_write)
            gate.resume()
        else:
            getattr(gate, finish)()
        pump(lambda: controller._thread is None)
        if finish in {"cancel", "control_failure"}:
            assert controller.snapshot is None
            assert bool(failures) == (finish == "control_failure")
            if failures:
                assert "Cannot control archive verification" in failures[0]
        else:
            assert TEMPLATE in controller.snapshot.rows
            assert controller.snapshot.provenance.capture().indexes
        from cdmw.services.diagnostics_service import process_is_alive
        assert not process_is_alive(int(child_pid.read_text()))
    finally:
        timer.stop()
        controller.request_shutdown()
        pump(lambda: controller._thread is None)


@pytest.mark.parametrize("frozen", [False, True])
def test_worker_routes_before_gui_or_single_instance_startup(tmp_path, monkeypatch, frozen):
    from cdmw.app import bootstrap

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    command = owner._worker_command(request, result)
    assert ("cdmw_app.py" in " ".join(command)) is not frozen
    calls = []
    monkeypatch.setattr(owner, "run_archive_verification_worker", lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(bootstrap, "bind_process_tree_to_app_lifetime", lambda: pytest.fail("worker entered GUI bootstrap"))
    assert bootstrap.main(command[command.index("--archive-verification-worker"):]) == 0
    assert calls == [(request, result)]
