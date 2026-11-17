"""The automation bridge's authoring commands: Import Replacement, Export Mesh File and
Create New Item's painting template, each driven as its button would be with only the
file chooser's answer given (they let the built exe's pass prove issue 31's reporter
case and the painting template)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from cdmw.automation import authoring_commands
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.models import ArchiveEntry
from cdmw.ui.mesh_editor import replacement_flow

_APP = QApplication.instance() or QApplication([])


def _wait(predicate, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _APP.processEvents()
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("timed out")


@pytest.fixture
def profile(monkeypatch, tmp_path):
    import cdmw.app.app_folder as app_folder

    root = tmp_path / "profile"
    root.mkdir()
    monkeypatch.setattr(app_folder, "cdmw_folder", lambda: root.resolve())
    return root


@pytest.fixture
def editor(tmp_path, monkeypatch, profile):
    """A real host session behind the Mesh Editor's real protocol code, with a stand-in
    helper: a ``cdmw_command`` becomes the ``command_request`` its button would send."""

    from tests.test_mesh_rejection_logging import _Editor
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request

    _source, service, host = _open_exact_session(tmp_path / "session")
    ui = _Editor()
    ui._initialize_rust_editor_runtime_state()
    ui.standalone_rust_authoring_session = host
    ui.standalone_rust_ready = True
    ui.standalone_rust_host_commands_supported = True
    entry = ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0)
    ui._current_target_entry = lambda: entry
    ui.window = lambda: ui
    monkeypatch.setattr(replacement_flow, "archive_workflow_dependency_context",
                        lambda _owner, _target: SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={}))

    def no_chooser(*_args, **_kwargs):
        raise AssertionError("the file chooser was asked")

    monkeypatch.setattr(replacement_flow.QFileDialog, "getOpenFileName", staticmethod(no_chooser))
    sent: list[dict] = []
    next_id = [30]

    def helper(message):
        sent.append(dict(message))
        if message.get("event") == "cdmw_command":
            next_id[0] += 1

            def request(request_id=next_id[0], command=message["command"], arguments=message["arguments"]):
                ui.standalone_rust_protocol_queue.append({**_request(host, "command_request", request_id),
                                                         "command": command, "arguments": arguments})
                ui._start_next_rust_protocol_worker()

            QTimer.singleShot(0, request)
        return True

    ui._send_rust_message = helper
    holder = QWidget()
    holder.active = ui
    window = SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder))
    yield SimpleNamespace(ui=ui, host=host, service=service, window=window, sent=sent)
    replacement_flow.source_path_override = None
    if ui.standalone_rust_protocol_thread is not None:
        host.request_cancel()
        ui.standalone_rust_protocol_thread.quit()
        ui.standalone_rust_protocol_thread.wait(5000)
    if not host.closed:
        host.cancel()
    service.close_edit_session(host.authoritative_session_id)
    ui.standalone_status_label.deleteLater()
    ui.deleteLater()
    holder.deleteLater()
    _APP.processEvents()


def _idle(editor):
    return _wait(lambda: (lambda s: not s["busy"] and s)(authoring_commands.replacement_state(editor.window, {})))


# Transfer from Original runs in the native mesh core (CDMW_MESH_CORE_BIN names a built one).
@pytest.mark.skipif(not native_mesh_core_available(), reason="the native mesh core is not built")
def test_export_then_import_with_an_added_piece_takes_the_real_host_path(editor, profile):
    window = editor.window
    exported = profile / "exchange" / "part.obj"
    assert authoring_commands.mesh_export(window, {"path": str(exported)}) == {"sent": True, "busy": False}
    assert editor.sent[-1]["event"] == "cdmw_command" and editor.sent[-1]["command"] == "export_mesh"
    assert editor.sent[-1]["arguments"] == {"path": str(exported), "format": "obj"}
    _wait(lambda: exported.is_file() and not authoring_commands.replacement_state(window, {})["busy"])
    original = authoring_commands.replacement_state(window, {})
    assert original["available"] and original["pending"] is None and not original["has_import"]
    parts = len(original["parts"])

    # The app's own export, with a piece added: a triangle away from the model.
    text = exported.read_text(encoding="utf-8")
    vertices = text.count("\nv ")
    exported.write_text(text + f"\no added_piece\nv 40 40 40\nv 41 40 40\nv 40 41 40\n"
                               f"f {vertices + 1} {vertices + 2} {vertices + 3}\n", encoding="utf-8")
    assert authoring_commands.replacement_import(window, {"path": str(exported)}) == {"sent": True, "busy": False}
    assert editor.sent[-1]["arguments"] == {"scope": "entire", "part_ids": []}
    pending = _wait(lambda: authoring_commands.replacement_state(window, {}).get("pending"))
    assert replacement_flow.source_path_override is None  # the chooser's answer was used once
    assert pending["source"] == "part.obj" and pending["sources"][-1] == "added_piece"
    assert len(pending["sources"]) == parts + 1

    # The export keeps the game weights; the added piece has none. Apply, as its button,
    # needs a weights choice then: Transfer from Original weights both from the part.
    assert pending["rigged"] and not pending["weights"]["default"]
    with pytest.raises(ValueError, match="Choose how to handle the imported weights"):
        authoring_commands.replacement_apply(window, {})
    assert "transfer" in [option["policy"] for option in pending["weights"]["options"] if option["enabled"]]
    applied = authoring_commands.replacement_apply(window, {"weights": "transfer"})
    assert applied["sent"] and len(applied["targets"]) == parts + 1 and all(applied["targets"])
    assert editor.sent[-1]["arguments"]["token"] == pending["token"]
    _idle(editor)
    assert not editor.ui.responses, editor.ui.responses[-1][1]
    after = authoring_commands.replacement_state(window, {})
    assert after["has_import"]
    assert after["pending"] is None
    mesh = editor.host.shadow_service.working_mesh(editor.host.shadow_session_id)
    assert any((40.0, 40.0, 40.0) == tuple(map(float, vertex)) for part in mesh.submeshes for vertex in part.vertices)
    # Every request the stand-in helper sent was answered as the helper expects.
    results = [m for m in editor.sent if m.get("event") == "command_result"]
    assert len(results) == 3 and all(m["ok"] for m in results)


@pytest.mark.skipif(not native_mesh_core_available(), reason="the native mesh core is not built")
def test_cancel_import_leaves_the_mapping_step_and_the_mesh_as_it_was(editor, tmp_path):
    window = editor.window
    model = tmp_path / "model.obj"
    model.write_text("o replacement\nv 12 3 7\nv 16 3 7\nv 12 5 8\nf 1 2 3\n")
    before = [list(part.vertices) for part in
              editor.host.shadow_service.working_mesh(editor.host.shadow_session_id).submeshes]
    assert authoring_commands.replacement_import(window, {"path": str(model)})["sent"]
    pending = _wait(lambda: authoring_commands.replacement_state(window, {}).get("pending"))
    assert pending["sources"] == ["replacement"]
    assert authoring_commands.replacement_cancel(window, {}) == {"sent": True, "busy": False}
    assert editor.sent[-1]["command"] == "replacement_cancel" and editor.sent[-1]["arguments"] == {}
    _wait(lambda: editor.sent[-1].get("event") == "command_result")
    after = _idle(editor)
    assert after["pending"] is None and not after["has_import"]
    assert [list(part.vertices) for part in
            editor.host.shadow_service.working_mesh(editor.host.shadow_session_id).submeshes] == before
    assert not editor.ui.responses


def test_replacement_commands_refuse_what_the_pass_must_not_do(editor, profile, tmp_path):
    window = editor.window
    fbx = tmp_path / "model.fbx"
    fbx.write_bytes(b"fbx")
    with pytest.raises(ValueError, match="FBX"):
        authoring_commands.replacement_import(window, {"path": str(fbx)})
    with pytest.raises(ValueError, match="existing OBJ"):
        authoring_commands.replacement_import(window, {"path": str(tmp_path / "missing.obj")})
    with pytest.raises(ValueError, match="inside the run's own profile"):
        authoring_commands.mesh_export(window, {"path": str(tmp_path / "elsewhere.obj")})
    with pytest.raises(ValueError, match="OBJ or GLB"):
        authoring_commands.mesh_export(window, {"path": str(profile / "x.fbx")})
    with pytest.raises(RuntimeError, match="mapping step"):
        authoring_commands.replacement_apply(window, {})
    model = tmp_path / "model.obj"
    model.write_text("o a\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    # A request already being worked on: nothing is sent, the chooser's answer is not left behind.
    editor.ui.standalone_rust_protocol_queue.append({"event": "command_request"})
    assert authoring_commands.replacement_import(window, {"path": str(model)}) == {"sent": False, "busy": True}
    assert replacement_flow.source_path_override is None
    editor.ui.standalone_rust_protocol_queue.clear()
    # An older helper would treat the message as a protocol failure: refused before sending.
    editor.ui.standalone_rust_host_commands_supported = False
    with pytest.raises(RuntimeError, match="older than this app"):
        authoring_commands.replacement_import(window, {"path": str(model)})
    assert not [m for m in editor.sent if m.get("event") == "cdmw_command"]


def test_the_chooser_answer_is_used_by_one_import_only(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(replacement_flow.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *args: asked.append(args) or ("", "")))
    entry = ArchiveEntry("a.pac", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 0, 0, 0, 0)
    session = SimpleNamespace(shadow_session_id="s", shadow_service=SimpleNamespace(
        _session=lambda _sid: SimpleNamespace(replacement_state=object())))
    tab = SimpleNamespace(standalone_rust_authoring_session=session, standalone_rust_closing=False,
                          _current_target_entry=lambda: entry, window=lambda: None)
    replacement_flow.source_path_override = str(tmp_path / "model.obj")
    event = {"command": "replacement_choose", "arguments": {"scope": "entire"}}
    first = replacement_flow.prepare_replacement_event(tab, session, event)
    assert first["arguments"]["source_path"] == str(tmp_path / "model.obj") and not asked
    second = replacement_flow.prepare_replacement_event(tab, session, event)
    assert second["arguments"]["cancelled"] is True and len(asked) == 1


def test_archive_find_reports_the_index_s_entries_by_token(monkeypatch):
    from cdmw.domain.archives.catalogue import ArchiveLookupKind
    from cdmw.ui.archive_browser import remote_entry_lookup

    started = []

    def lookup(owner, attribute, requests, *, on_done, on_error):
        started.append((owner, attribute, requests))
        dto = SimpleNamespace(path="character/model/a/cd_x.pac", entry_id=7, package="0009", is_active_override=False)
        QTimer.singleShot(0, lambda: on_done(SimpleNamespace(entries=(dto,), truncated=False)))

    monkeypatch.setattr(remote_entry_lookup, "start_live_catalogue_lookup", lookup)
    archive = SimpleNamespace(archive_remote_bridge=SimpleNamespace(current_session=SimpleNamespace(session_id="s1")))
    token = authoring_commands.archive_find(SimpleNamespace(archive=archive), {"basenames": ["cd_x.pac"]})["token"]
    assert started[0][2][0].kind is ArchiveLookupKind.BASENAMES
    assert authoring_commands.archive_find_result(None, {"token": token}) == {"done": False}
    found = _wait(lambda: (lambda r: r["done"] and r)(authoring_commands.archive_find_result(None, {"token": token})))
    assert found["entries"] == [{"path": "character/model/a/cd_x.pac", "entry_id": 7, "package": "0009", "active": False}]
    assert "error" in authoring_commands.archive_find_result(None, {"token": "nope"})


# ----- the painting template --------------------------------------------------------
class _Controller(QObject):
    log_message = Signal(str)

    def __init__(self, frames):
        super().__init__()
        self.frames = frames
        self.builds = []
        self.snapshot = object()
        self.busy = False

    def start_painting_frames(self, on_done, _on_error):
        QTimer.singleShot(0, lambda: on_done((SimpleNamespace(frames=self.frames, left_out=()), {})))
        return True

    def start_painting_build(self, requests, folder, title, on_done, _on_error):
        self.builds.append((tuple(requests), Path(folder), title))
        result = SimpleNamespace(plan=SimpleNamespace(summary_lines=["1 painting"]),
                                 paintings=[{"names": {"eng": requests[0].names["eng"]}}],
                                 export=SimpleNamespace(package_root=Path(folder)))
        QTimer.singleShot(0, lambda: (self.log_message.emit("Writing the mod"), on_done(result)))
        return True

    def cancel_operation(self, _lane=""):
        return False


def _frame(stem, aspect):
    return SimpleNamespace(mesh=f"object/00_common/interior/decopropw/{stem}.pam", stem=stem,
                           label=f"{stem} (1.0 x {1 / aspect:.1f} m)", texture_size=(512, 256),
                           size_m=(1.2, 1.2 / aspect),
                           canvas=SimpleNamespace(aspect=aspect, size_m=(1.0, 1.0 / aspect)),
                           source=SimpleNamespace(name="CD_Painting_01"), shipped_paintings=2)


@pytest.fixture
def studio(profile):
    from cdmw.ui.new_item.painting_dialog import PaintingDialog

    controller = _Controller([_frame("cd_in_dpw_picture_01", 1.5), _frame("cd_in_dpw_picture_07", 2.0)])
    panel = QWidget()
    panel._painting_dialog = None
    panel.painting_button = QPushButton("New painting...", panel)

    def open_dialog():
        if panel._painting_dialog is None:
            panel._painting_dialog = PaintingDialog(controller, panel)
        panel._painting_dialog.open()

    panel.painting_button.clicked.connect(open_dialog)
    holder = QWidget()
    holder.workflow = SimpleNamespace(template_panel=panel, controller=controller, _panels_built=True,
                                      start_snapshot=lambda: None)
    shown = []
    window = SimpleNamespace(shell=SimpleNamespace(new_item_studio_tab=holder, _activate_tool_key=shown.append))
    yield SimpleNamespace(window=window, controller=controller, panel=panel, shown=shown)
    if panel._painting_dialog is not None:
        panel._painting_dialog.done(0)
    panel.deleteLater()
    holder.deleteLater()
    _APP.processEvents()


def test_painting_commands_fill_the_dialog_as_a_user_would_and_build(studio, profile, tmp_path):
    from PIL import Image

    window = studio.window
    picture = tmp_path / "my_landscape.png"
    Image.new("RGB", (300, 200), (30, 90, 160)).save(picture)
    opened = authoring_commands.painting_open(window, {})
    assert studio.shown == ["new_item_studio"] and opened["open"]
    state = _wait(lambda: (lambda s: s["frames"] and not s["building"] and s)(authoring_commands.painting_state(window, {})))
    assert [frame["stem"] for frame in state["frames"]] == ["cd_in_dpw_picture_01", "cd_in_dpw_picture_07"]
    folder = profile / "mods" / "paintings"
    state = authoring_commands.painting_set(window, {
        "frame": "cd_in_dpw_picture_07", "picture": str(picture), "fit": "whole",
        "texts": {"eng": {"name": "Blue Field", "description": "A test picture."},
                  "ger": {"name": "Blaues Feld"}},
        "mod_name": "Driven paintings", "folder": str(folder)})
    painting = state["paintings"][0]
    assert painting["frame"].endswith("cd_in_dpw_picture_07.pam") and painting["picture"] == str(picture)
    assert painting["fit"] == "whole"
    assert painting["names"] == {"eng": "Blue Field", "ger": "Blaues Feld"}
    assert painting["descriptions"] == {"eng": "A test picture."}
    assert state["listed"] == ["1. Blue Field (cd_in_dpw_picture_07)"] and state["folder"] == str(folder)
    _wait(lambda: authoring_commands.painting_state(window, {})["preview_shown"])
    # A second painting, by its frame's full mesh path, the name taken from the picture.
    state = authoring_commands.painting_set(window, {"add": True, "frame": state["frames"][0]["mesh"],
                                                     "picture": str(picture)})
    assert [p["names"] for p in state["paintings"]] == [{"eng": "Blue Field", "ger": "Blaues Feld"},
                                                        {"eng": "my landscape"}]

    assert authoring_commands.painting_build(window, {})["started"]
    done = _wait(lambda: (lambda s: not s["building"] and s)(authoring_commands.painting_state(window, {})))
    requests, built_folder, title = studio.controller.builds[0]
    assert built_folder == folder and title == "Driven paintings" and len(requests) == 2
    assert done["status"].startswith("Wrote 1 painting(s) to") and "Writing the mod" in done["log"]
    assert authoring_commands.painting_close(window, {})
    assert not authoring_commands.painting_state(window, {})["open"]


def test_painting_commands_refuse_a_folder_outside_the_profile_and_unknown_choices(studio, tmp_path):
    window = studio.window
    with pytest.raises(RuntimeError, match="not open"):
        authoring_commands.painting_set(window, {"fit": "fill"})
    authoring_commands.painting_open(window, {})
    _wait(lambda: authoring_commands.painting_state(window, {})["frames"])
    with pytest.raises(ValueError, match="inside the run's own profile"):
        authoring_commands.painting_set(window, {"folder": str(tmp_path / "elsewhere")})
    with pytest.raises(ValueError, match="No frame"):
        authoring_commands.painting_set(window, {"frame": "cd_gimmick_picture_01"})
    with pytest.raises(ValueError, match="fill or whole"):
        authoring_commands.painting_set(window, {"fit": "stretch"})
    with pytest.raises(ValueError, match="inside the run's own profile"):
        authoring_commands.painting_build(window, {})
    assert not studio.controller.builds


def test_painting_open_waits_for_the_page_and_the_archive_tables(studio):
    workflow = studio.window.shell.new_item_studio_tab.workflow
    workflow._panels_built = False
    assert authoring_commands.painting_open(studio.window, {})["waiting"].startswith("The Template page")
    workflow._panels_built = True
    studio.controller.snapshot = None
    reads = []
    workflow.start_snapshot = lambda: reads.append(True)
    assert authoring_commands.painting_open(studio.window, {})["waiting"].startswith("Create New Item is reading")
    assert reads == [True] and studio.panel._painting_dialog is None


def test_the_bridge_lists_the_authoring_commands(monkeypatch, tmp_path):
    import secrets

    from cdmw.app import app_folder
    from cdmw.automation import policy
    from cdmw.automation.bridge import AutomationBridge

    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path / "profile"))
    monkeypatch.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    app_folder._reset_for_tests()
    try:
        bridge = AutomationBridge(policy.automation_settings())
    finally:
        app_folder._reset_for_tests()
    assert set(authoring_commands.ui_commands(bridge)) <= set(bridge._ui_commands)
    assert {"replacement_import", "replacement_apply", "mesh_export", "painting_build"} <= set(bridge._ui_commands)


@pytest.mark.parametrize("announced", [False, True])
def test_the_editor_learns_from_the_helper_s_hello_whether_it_takes_cdmw_commands(tmp_path, announced):
    """A helper that does not announce host_cdmw_command_v1 would end its session on the
    event, so the bridge only sends to one whose hello names it."""
    from cdmw.services.mesh_rust_contract import (
        RUST_HOST_CDMW_COMMAND_CAPABILITY, RUST_MESH_EDIT_BACKEND, RUST_MESH_RENDERER)
    from tests.test_mesh_rust_embedding import _tab

    tab = _tab(tmp_path)
    try:
        tab.standalone_rust_process = SimpleNamespace(processId=lambda: 77)
        tab.standalone_native_host_frame.attach_child_window = lambda *_args: (True, "")
        tab._send_rust_message = lambda _payload: True
        assert tab.standalone_rust_host_commands_supported is False
        capabilities = ["embedded_child_window_v1", *([RUST_HOST_CDMW_COMMAND_CAPABILITY] if announced else [])]
        tab._handle_rust_hello({"renderer": RUST_MESH_RENDERER, "edit_backend": RUST_MESH_EDIT_BACKEND,
                                "capabilities": capabilities, "child_hwnd": 123, "embedded_parent_hwnd": 456})
        assert tab.standalone_rust_host_commands_supported is announced
        # A helper started again forgets it until its own hello.
        tab._reset_rust_protocol_state()
        assert tab.standalone_rust_host_commands_supported is False
    finally:
        tab.deleteLater()
        _APP.processEvents()
