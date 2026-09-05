"""Effect indexing crosses a cancellable process boundary without losing facts."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services import effect_catalogue_process as owner
from cdmw.services.effect_catalogue import build_effect_catalogue
from cdmw.services.new_item_snapshot import EFFECT_DIR

FIXTURE = Path(__file__).parent / "fixtures" / "effects" / "fx_hit_common_fire_attach_a_loop.pae"


def _snapshot(reader=None):
    data = FIXTURE.read_bytes()
    entries = {
        f"{EFFECT_DIR}{stem}.pae": SimpleNamespace(stem=stem, orig_size=len(data))
        for stem in ("good", "malformed", "unreadable")
    }

    def read(entry):
        if entry.stem == "unreadable":
            raise OSError("owned fixture read failed")
        return data if entry.stem == "good" else b"broken"

    return SimpleNamespace(
        effect_stems=frozenset(("good", "malformed", "unreadable", "missing")),
        entries=entries, has_entry=lambda path: path in entries,
        entry=entries.__getitem__, read_entry=reader or read,
    )


def _own_temporary_files(monkeypatch, tmp_path):
    monkeypatch.setattr(owner, "TemporaryDirectory", lambda **kwargs: tempfile.TemporaryDirectory(dir=tmp_path, **kwargs))


def test_real_child_preserves_facts_read_errors_and_progress(monkeypatch, tmp_path):
    snapshot = _snapshot()
    expected = build_effect_catalogue(snapshot)
    progress, logs = [], []
    _own_temporary_files(monkeypatch, tmp_path)

    def reject_parent_decode(*args, **kwargs):
        pytest.fail("CPU-bound effect decoding ran in the parent interpreter")

    monkeypatch.setattr("cdmw.services.effect_catalogue.decode_effect_binary", reject_parent_decode)
    actual = owner.build_effect_catalogue_in_subprocess(
        snapshot, on_progress=lambda *values: progress.append(values), on_log=logs.append,
    )
    assert actual == expected
    assert progress[0] == (0, 4, "good")
    assert progress[-1] == (3, 3, "unreadable")
    assert logs == ["Indexed 3 effects; 2 did not decode."]
    assert not tuple(tmp_path.iterdir())


def test_cancellation_while_reading_never_starts_a_child(monkeypatch, tmp_path):
    stop = threading.Event()
    _own_temporary_files(monkeypatch, tmp_path)

    def read(entry):
        stop.set()
        return FIXTURE.read_bytes()

    monkeypatch.setattr(owner, "run_process_with_cancellation", lambda *a, **kw: pytest.fail("child started after cancellation"))
    with pytest.raises(RunCancelled):
        owner.build_effect_catalogue_in_subprocess(_snapshot(read), stop_event=stop)
    assert not tuple(tmp_path.iterdir())


def test_lane_does_not_report_process_cancellation_as_an_indexing_failure(monkeypatch):
    from cdmw.workers import effect_catalogue_worker

    def cancelled(*args, **kwargs):
        raise RunCancelled("Processing stopped by user.")

    monkeypatch.setattr(effect_catalogue_worker, "build_effect_catalogue", cancelled)
    lane = effect_catalogue_worker.EffectCatalogueIndexLane(synchronous=True)
    failures, completed = [], []
    lane.failed.connect(failures.append)
    lane.completed.connect(lambda *args: completed.append(args))
    assert lane.start(_snapshot())
    assert not failures and not completed


def test_cancel_running_child_reaps_it_before_spool_cleanup(monkeypatch, tmp_path):
    stop = threading.Event()
    _own_temporary_files(monkeypatch, tmp_path)
    ready = tmp_path / "child-started"
    exited = tmp_path / "child-finished"
    script = (
        "from pathlib import Path; import time; "
        f"Path({str(ready)!r}).write_text('started'); "
        "time.sleep(30); "
        f"Path({str(exited)!r}).write_text('finished')"
    )
    monkeypatch.setattr(owner, "_worker_command", lambda *args: [sys.executable, "-c", script])
    original = owner.run_process_with_cancellation

    def run(command, **kwargs):
        poll = kwargs["on_poll"]

        def cancel_when_started():
            poll()
            if ready.exists():
                stop.set()

        kwargs["on_poll"] = cancel_when_started
        kwargs["timeout_seconds"] = 10
        return original(command, **kwargs)

    monkeypatch.setattr(owner, "run_process_with_cancellation", run)
    with pytest.raises(RunCancelled):
        owner.build_effect_catalogue_in_subprocess(_snapshot(), stop_event=stop)
    assert ready.exists()
    assert not exited.exists()
    assert not tuple(tmp_path.glob("cdmw_effect_catalogue_*"))


@pytest.mark.parametrize("failure", ("exit", "missing", "incomplete", "late_cancel"))
def test_failed_or_cancelled_child_result_is_not_published(monkeypatch, tmp_path, failure):
    stop = threading.Event()
    _own_temporary_files(monkeypatch, tmp_path)

    def run(command, **kwargs):
        if failure == "exit":
            return 7, "", "owned child failure"
        output = Path(command[command.index("--output") + 1])
        if failure in {"incomplete", "late_cancel"}:
            owner.run_effect_catalogue_worker(Path(command[command.index("--input") + 1]), output)
            if failure == "incomplete":
                payload = json.loads(output.read_text(encoding="utf-8"))
                payload["effects"].pop()
                output.write_text(json.dumps(payload), encoding="utf-8")
            else:
                stop.set()
        return 0, "", ""

    monkeypatch.setattr(owner, "run_process_with_cancellation", run)
    with pytest.raises(RunCancelled if failure == "late_cancel" else RuntimeError):
        owner.build_effect_catalogue_in_subprocess(_snapshot(), stop_event=stop)
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize("frozen", (False, True))
def test_worker_mode_routes_before_gui_and_single_instance_setup(monkeypatch, tmp_path, frozen):
    from cdmw.app import bootstrap

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    command = owner._worker_command(request, result)
    assert command[0] == sys.executable
    assert ("cdmw_app.py" in " ".join(command)) is not frozen
    calls = []
    monkeypatch.setattr(owner, "run_effect_catalogue_worker", lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(bootstrap, "bind_process_tree_to_app_lifetime", lambda: pytest.fail("worker entered main-app startup"))
    assert bootstrap.main(command[command.index("--effect-catalogue-worker"):]) == 0
    assert calls == [(request, result)]
