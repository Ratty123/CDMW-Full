"""Send to DMM runs in a child process so the window does not lag while items compose."""
import sys
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services import dmm_send_process as owner
from tests.test_dmm_send import _dmm


def _files(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def test_a_send_in_the_child_process_writes_the_same_mod_as_one_in_process(tmp_path, monkeypatch):
    from cdmw.services.dmm_send import send_item_packages
    from tests.test_virtual_loader import packages
    # The child does not see this process's patches: keep its history and logs in tmp_path.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    root, files = packages(tmp_path)
    _install, mods = _dmm(tmp_path)
    logs, steps = [], []
    result = owner.send_item_packages_in_subprocess(files, root, mods, "Two items", on_log=logs.append,
                                                    on_progress=lambda value, total, detail: steps.append(value))
    assert result.folder == mods / "Two items" and not result.replaced
    child = _files(result.folder)
    assert logs and steps and steps[-1] == 100
    again = send_item_packages(files, root, mods, "Two items")
    assert again.replaced
    # Identities are kept between sends, so both ways write the same mod byte for byte.
    assert _files(again.folder) == child
    assert not [p for p in mods.parent.iterdir() if p.name.startswith(".cdmw-send-")]


def test_cancel_stops_the_child_and_removes_its_staging_folder(tmp_path, monkeypatch):
    _install, mods = _dmm(tmp_path)
    started = tmp_path / "started"
    script = (
        "import pathlib, sys, time\n"
        f"pathlib.Path({str(mods.parent / '.cdmw-send-child')!r}).mkdir()\n"
        f"pathlib.Path({str(started)!r}).write_text('yes')\n"
        "time.sleep(60)\n"
    )
    monkeypatch.setattr(owner, "_worker_command", lambda *_args: [sys.executable, "-c", script])
    stop = threading.Event()

    def cancel_when_started():
        for _ in range(400):
            if started.exists():
                break
            threading.Event().wait(0.05)
        stop.set()

    threading.Thread(target=cancel_when_started, daemon=True).start()
    with pytest.raises(RunCancelled):
        owner.send_item_packages_in_subprocess([tmp_path / "item.cdmw"], tmp_path / "game", mods, "Items",
                                               stop_event=stop)
    assert not (mods.parent / ".cdmw-send-child").exists()


def test_a_failure_in_the_child_shows_its_message(tmp_path, monkeypatch):
    _install, mods = _dmm(tmp_path)
    script = "import sys\nprint('Wolf Trial: incompatible game dependency x.dds.', file=sys.stderr)\nsys.exit(1)\n"
    monkeypatch.setattr(owner, "_worker_command", lambda *_args: [sys.executable, "-c", script])
    with pytest.raises(owner.DmmSendProcessError, match="incompatible game dependency"):
        owner.send_item_packages_in_subprocess([tmp_path / "item.cdmw"], tmp_path / "game", mods, "Items")


@pytest.mark.parametrize("frozen", [False, True])
def test_worker_routes_before_gui_or_single_instance_startup(tmp_path, monkeypatch, frozen):
    from cdmw.app import bootstrap

    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    request, result = tmp_path / "request.json", tmp_path / "result.json"
    command = owner._worker_command(request, result)
    assert ("cdmw_app.py" in " ".join(command)) is not frozen
    calls = []
    monkeypatch.setattr(owner, "run_dmm_send_worker", lambda *args: calls.append(args) or 0)
    monkeypatch.setattr(bootstrap, "bind_process_tree_to_app_lifetime", lambda: pytest.fail("worker entered GUI bootstrap"))
    assert bootstrap.main(command[command.index("--dmm-send-worker"):]) == 0
    assert calls == [(request, result)]
