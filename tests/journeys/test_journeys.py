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


def _editor_ready(run):
    run.wait(lambda: (run.state()["mesh_editor"] or {}).get("ready"), timeout=90, what="the editor to be ready")


def _one_edit(run, before: int) -> int:
    """Delete a few faces through the editor's own commands, as the palette runs them."""

    for command in ("selection.target.face", "session.select_all", "selection.shrink", "selection.shrink",
                    "selection.shrink", "topology.delete_selection"):
        run.call("run_editor_command", id=command)
    return run.wait(lambda: (run.state()["mesh_editor"]["revision"] > before) and run.state()["mesh_editor"]["revision"],
                    timeout=60, what="the edit to be accepted")


def test_journey_3_an_edit_through_the_bridge_in_browse_and_in_the_mesh_workspace(run):
    """P15 step 5a (step 5 item 7): an edit sent through the bridge lands while the edit
    is in Browse's view, and again after the rail switched to the Mesh Editor, which
    keeps the same window. The restart-and-recover half of the stage B journey is
    not written yet."""

    run.select(driver.SWORD)
    hwnd = run.state()["browse_frame_hwnd"]
    run.open_mesh_editor()
    _editor_ready(run)
    assert run.state()["mesh_editor"]["in_browse"]
    first = _one_edit(run, run.state()["mesh_editor"]["revision"])
    index = len(run.call("events"))
    run.call("activate_tool", key="mesh_editor")
    state = run.wait(lambda: run.state()["browse_edit_as_mesh"] and run.state(), timeout=20,
                     what="Browse's page to be the Mesh workspace")
    assert state["workspace"] == "mesh_editor" and state["browse_page_visible"], state
    assert state["browse_frame_hwnd"] == hwnd and state["mesh_editor"]["in_browse"], state
    second = _one_edit(run, first)
    assert second > first
    assert not [e for e in run.call("events", since=index) if e["event"] == "preview:edit_entered"]
    assert run.call("end_edit", answer="discard")


def test_journey_4_switch_workspaces_around_one_window(run):
    """P15 step 5a (step 5 item 7, and stage B's journey 4): switching Browse, the Mesh
    Editor and Create New Item and back keeps Browse's window, its selection and its
    picture, uploads nothing, and never shows two 3D views; a capture requested as
    the switch starts still completes."""

    run.select(driver.SWORD)
    first = run.state()
    hwnd, selected = first["browse_frame_hwnd"], run.call("selection").get("selected", "")
    assert hwnd and first["visible_viewports"] == 1, first
    index = len(run.call("events"))
    assert run.call("capture", path=str(run.profile / "captures" / "before.png"))
    run.call("activate_tool", key="mesh_editor")
    captured = run.wait(lambda: [e for e in run.call("events", since=index) if e["event"] == "preview:capture_result"],
                        timeout=60, what="the capture requested before the switch")
    assert captured[-1].get("status") == "captured", captured
    state = run.state()
    assert state["mesh_page_visible"] and not state["browse_page_visible"] and state["visible_viewports"] <= 1, state
    run.call("activate_tool", key="new_item_studio")
    run.wait(lambda: not run.state()["mesh_page_visible"], timeout=60, what="Create New Item to show")
    assert run.state()["visible_viewports"] == 0
    run.call("activate_tool", key="archive_browser")
    back = run.wait(lambda: run.state()["browse_page_visible"] and run.state(), timeout=30, what="Browse to show")
    assert back["browse_frame_hwnd"] == hwnd and back["visible_viewports"] == 1, back
    assert run.call("selection").get("selected", "") == selected
    loads = [e for e in run.call("events", since=index)
             if e["event"].startswith("preview:package") or e["event"] == "preview:edit_entered"]
    assert not loads, loads
    # With an edit in Browse's view, the Mesh workspace is Browse's page and window.
    run.open_mesh_editor()
    _editor_ready(run)
    index = len(run.call("events"))
    run.call("activate_tool", key="mesh_editor")
    mesh = run.wait(lambda: run.state()["browse_edit_as_mesh"] and run.state(), timeout=20,
                    what="Browse's page to be the Mesh workspace")
    assert mesh["browse_frame_hwnd"] == hwnd and mesh["visible_viewports"] == 1 and not mesh["mesh_page_visible"], mesh
    run.call("activate_tool", key="new_item_studio")
    run.wait(lambda: not run.state()["browse_page_visible"], timeout=60, what="Create New Item to show")
    assert run.state()["visible_viewports"] == 0
    run.call("activate_tool", key="mesh_editor")
    again = run.wait(lambda: run.state()["browse_edit_as_mesh"] and run.state(), timeout=20,
                     what="the Mesh workspace in Browse's page again")
    assert again["browse_frame_hwnd"] == hwnd and again["mesh_editor"]["in_browse"], again
    run.call("activate_tool", key="archive_browser")
    browse = run.wait(lambda: not run.state()["browse_edit_as_mesh"] and run.state(), timeout=20, what="Browse again")
    assert browse["browse_frame_hwnd"] == hwnd and browse["mesh_editor"]["in_browse"], browse
    assert not [e for e in run.call("events", since=index) if e["event"] == "preview:edit_entered"]
    assert run.call("end_edit", answer="discard")


def test_journey_5_a_preview_setting_changed_once_reaches_every_viewport(run):
    run.select(driver.SWORD)
    run.open_mesh_editor()
    settings = run.state()["preview_settings"]
    flipped = {"ground_grid": not settings["shared"]["ground_grid"],
               "shadows": not settings["shared"]["shadows"],
               # P4 V3: one view mode and one background for every viewport.
               "view_mode": "wire" if settings["shared"]["view_mode"] != "wire" else "textured",
               "background_color": "#203040" if settings["shared"]["background_color"] != "#203040" else "#3B3B3B"}
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
    # P4 V4: the editor showed Browse's model before its session was ready.
    viewing = [e for e in run.call("events", since=index) if e["event"] == "preview:edit_viewing"]
    assert viewing and viewing[0]["i"] < entered["i"], "the view did not come before the session"
    assert viewing[0]["install_ms"] < 500
    assert entered["texture_uploads_after"] == entered["texture_uploads_before"], entered
    assert entered["edit_camera_yaw"] == pytest.approx(entered["browse_camera_yaw"], abs=1e-4)
    assert entered["edit_camera_distance"] == pytest.approx(entered["browse_camera_distance"], rel=1e-4)
    # P4 V5: Promote to tab moves the edit as it is; Browse previews again.
    assert run.call("promote_edit")
    run.wait(lambda: not run.state()["mesh_editor"]["in_browse"], timeout=30, what="the edit to move to the tab")
    state = run.state()["mesh_editor"]
    assert state["process_id"] == browse_pid and state["ready"], state
    index = len(run.call("events"))
    assert run.call("end_edit", answer="discard")
    run.wait(lambda: any(e["event"] == "preview:edit_left" for e in run.call("events", since=index)),
             timeout=30, what="the helper to leave edit mode")
    assert run.state()["browse_process_id"] == browse_pid


def test_journey_7_two_documents_edit_in_one_process(run):
    """P15: a second mesh opens beside an open edit as a document tab, in Browse's process."""

    run.select(driver.SWORD)
    browse_pid = run.state()["browse_process_id"]
    run.open_mesh_editor()
    run.wait(lambda: run.state()["mesh_editor"]["ready"], timeout=60, what="the first edit to be ready")
    # Browse's view holds the first edit, so the second file is selected, not previewed.
    run.call("select_entry", path=driver.UPPER)
    run.wait(lambda: run.call("selection").get("selected", "").casefold() == driver.UPPER.casefold(),
             timeout=30, what="the second file to be selected")

    def two_open():
        return len(run.state()["mesh_documents"]["documents"]) == 2

    # The second file's related files are prepared first ("Open in Mesh Editor again
    # when its preview finishes"), as a user who opens it again would see.
    for _attempt in range(4):
        run.call("open_mesh_editor")
        try:
            run.wait(two_open, timeout=20, what="a second document")
            break
        except TimeoutError:
            run.wait(lambda: not run.state()["browse"]["worker_busy"], timeout=120, what="Browse to prepare the file")

    def two_ready():
        documents = run.state()["mesh_documents"]["documents"]
        return len(documents) == 2 and all(document["ready"] for document in documents) and documents

    try:
        documents = run.wait(two_ready, timeout=90, what="both documents to be ready")
    except TimeoutError as timeout:
        state = run.state()
        raise AssertionError(f"{timeout}: {state['mesh_documents']} editor {state['mesh_editor']}") from timeout
    # Both edits are in Browse's process: one in its view, one in a window of its own.
    assert {document["process_id"] for document in documents} == {browse_pid}, documents
    assert [document["in_browse"] for document in documents].count(True) <= 1
    assert run.call("show_document", index=0)
    assert run.state()["mesh_documents"]["shown"] == 0
    assert run.state()["mesh_editor"]["ready"]  # the first document kept its edit loaded
    assert run.call("show_document", index=1)
    assert run.call("end_edit", answer="discard")
    assert run.call("show_document", index=0)
    assert run.call("end_edit", answer="discard")
    assert run.state()["browse_process_id"] == browse_pid
