"""User journeys through the real app (P13 stage B). Opt in: -Area journeys."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.journeys import driver

pytestmark = [pytest.mark.real_game, pytest.mark.skipif(bool(driver.skip_reason()), reason=driver.skip_reason() or "-")]

# Places outside the CDMW folder an app run might touch. Graphics drivers keep
# their shader caches under %LOCALAPPDATA%; those are the one listed exception.
_DRIVER_CACHE_NAMES = re.compile(r"(?i)^(D3DSCache|NVIDIA|AMD|Intel|Microsoft|Temp|Packages|CrashDumps)$")
_OURS = re.compile(r"(?i)(cdmw|crimson ?desert ?mod|_MEI\d|\.rust-preview-)")
# Other sessions on this machine also run CDMW's own tests and tools.
_OTHER_RUNS = re.compile(r"(?i)^cdmw-pytest-")


def _outside_snapshot() -> dict[str, set[str]]:
    roots = {
        "TEMP": Path(os.environ.get("CDMW_SYSTEM_TEMP") or os.environ["TEMP"]),
        "APPDATA": Path(os.environ["APPDATA"]),
        "LOCALAPPDATA": Path(os.environ["LOCALAPPDATA"]),
        "Documents": Path(os.environ["USERPROFILE"]) / "Documents",
    }
    snapshot = {}
    for label, root in roots.items():
        try:
            snapshot[label] = {entry.name for entry in os.scandir(root)}
        except OSError:
            snapshot[label] = set()
    from tests.test_app_folder import _registry_snapshot

    snapshot["registry"] = {f"{k}={v}" for k, v in (_registry_snapshot() or {}).items()}
    return snapshot


def _new_outside_writes(before: dict[str, set[str]], after: dict[str, set[str]]) -> list[str]:
    found = []
    for label, names in after.items():
        for name in sorted(names - before.get(label, set())):
            if label == "registry":
                found.append(f"registry: {name}")
            elif label == "LOCALAPPDATA" and _DRIVER_CACHE_NAMES.match(name):
                continue
            elif _OURS.search(name) and not _OTHER_RUNS.match(name):
                found.append(f"{label}: {name}")
    return found


@pytest.fixture
def run(request):
    name = request.node.name.replace("[", "-").replace("]", "")
    profile = driver.make_profile(name)
    app = driver.Run(profile)
    try:
        app.wait_usable()
        app.call("activate_tool", key="archive_browser")
        yield app
    finally:
        app.close()
        driver.keep_log_and_remove(profile, name)


def test_journey_1_browse_then_open_in_the_mesh_editor_textured():
    """Browse a model, open it in the Mesh Editor; ready, textured, nothing written outside.

    The edit and Finish steps wait for a way to send the editor's own commands
    from outside its window (P12's registry mirrors them); until then this
    journey stops at a ready, textured editor.
    """

    before = _outside_snapshot()
    profile = driver.make_profile("journey-1")
    app = driver.Run(profile)
    try:
        app.wait_usable()
        app.call("activate_tool", key="archive_browser")
        shown = app.select(driver.SWORD)
        assert shown["browse"]["textures_visible"]
        editor = app.open_mesh_editor()
        assert editor["texture_unavailable_reason"] == "", editor
        assert Path(editor["session_manifest"]).is_file()
        assert Path(editor["session_manifest"]).resolve().is_relative_to(profile.resolve())
    finally:
        app.close()
        driver.keep_log_and_remove(profile, "journey-1")
    after = _outside_snapshot()
    assert _new_outside_writes(before, after) == []


def test_journey_2_a_five_file_set_opens_textured(run):
    shown = run.select(driver.HONOR_GUARD_SET)
    assert shown["browse"]["set_members"] == 5
    editor = run.open_mesh_editor(item_set=True)
    assert editor["texture_unavailable_reason"] == "", (
        "the set opened untextured: " + editor["texture_unavailable_reason"])


def test_journey_3_edit_restart_recover_the_draft():
    pytest.skip("The app offers a draft only when the same file is opened again, and an edit cannot yet be "
                "sent from outside the editor's window; written with P4 V4 (and its history with P14).")


def test_journey_5_a_preview_setting_changed_once_reaches_every_viewport(run):
    run.select(driver.SWORD)
    run.open_mesh_editor()
    settings = run.state()["preview_settings"]
    flipped = {"ground_grid": not settings["shared"]["ground_grid"],
               "shadows": not settings["shared"]["shadows"]}
    run.call("set_preview_settings", values=flipped)

    def everywhere():
        now = run.state()["preview_settings"]
        return all(view and all(view.get(k) == v for k, v in flipped.items())
                   for view in (now["shared"], now["browse"], now["mesh_editor"])) and now

    reached = run.wait(everywhere, what="the change to reach Browse and the Mesh Editor")
    assert reached["shared"]["shadows"] == flipped["shadows"]


def test_journey_6_edit_in_browse_in_its_own_process_and_return(run):
    """P4 V3: Open in Mesh Editor edits in Browse's viewport, in Browse's process, with
    no texture uploaded again; Discard hands the view back to Browse."""

    run.select(driver.UPPER)
    browse_pid = run.state()["browse_process_id"]
    index = len(run.call("events"))
    editor = run.open_mesh_editor()
    assert editor["texture_unavailable_reason"] == "", editor
    state = run.state()["mesh_editor"]
    assert state["in_browse"] and state["process_id"] == browse_pid
    entered = run.wait(lambda: [e for e in run.call("events", since=index) if e["event"] == "preview:edit_entered"],
                       what="the edit to report its uploads")[-1]
    assert entered["texture_uploads_after"] == entered["texture_uploads_before"], entered
    assert entered["edit_camera_yaw"] == pytest.approx(entered["browse_camera_yaw"], abs=1e-4)
    assert entered["edit_camera_distance"] == pytest.approx(entered["browse_camera_distance"], rel=1e-4)
    index = len(run.call("events"))
    assert run.call("end_edit", answer="discard")
    run.wait(lambda: not run.state()["mesh_editor"]["in_browse"], timeout=60, what="the edit to leave Browse")
    run.wait(lambda: any(e["event"] == "preview:edit_left" for e in run.call("events", since=index)),
             timeout=30, what="the helper to leave edit mode")
    assert run.state()["browse_process_id"] == browse_pid
