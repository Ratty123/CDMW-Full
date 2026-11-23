"""AI connections: Mesh Editor tools that looked covered but failed at runtime, each driven
through the real server and bridge against a real host session behind the editor's own
protocol code (the stand-in helper turns a ``cdmw_command`` into the request its button sends)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hashlib
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from cdmw.mcp import approvals  # noqa: F401  (the approvals module is loaded as the app loads it)
from tests.test_mcp_area_tools import app, connect, profile, settings  # noqa: F401  (fixtures)
from tests.test_archive_live_catalogue_workflows import SESSION, _Bridge, _dto, _LookupService
from tests.test_automation_authoring_commands import editor  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


@pytest.fixture
def answered(editor, connect):  # noqa: F811
    """The stand-in editor whose helper answers every command, with the connection around it."""

    from PySide6.QtCore import QTimer

    from tests.test_mesh_rust_authoring_exact_output import _request

    ui, host = editor.ui, editor.host
    next_id = [30]

    def helper(message):
        # As the helper does: the command comes back as its button's request, numbered in
        # order as the editor's handler records it, and queued for the editor's worker.
        editor.sent.append(dict(message))
        if message.get("event") == "cdmw_command":
            next_id[0] += 1

            def request(request_id=next_id[0], command=message["command"], arguments=message["arguments"]):
                ui.standalone_rust_last_client_request_id = request_id
                ui.standalone_rust_protocol_queue.append({**_request(host, "command_request", request_id),
                                                         "command": command, "arguments": arguments})
                ui._start_next_rust_protocol_worker()

            QTimer.singleShot(0, request)
        return True

    ui._send_rust_message = helper
    ui.standalone_rust_host_edit_commands_supported = True
    ui.standalone_rust_host_output_commands_supported = True
    ui.standalone_rust_host_panel_commands_supported = True
    editor.mcp = connect(editor.window)
    # A call that waits for the editor answers within the call, not as a job to follow.
    editor.mcp.controller.server.quick_result_s = 60.0
    yield editor


def _select_part_vertices(editor, part: int = 0, count: int = 3) -> None:
    mcp = editor.mcp
    selected = mcp.ok("mesh_select", {"vertices": {str(part): list(range(count))}})
    assert selected["done"], selected
    assert selected["selection"]["vertices"] == count


# ----- 1. Vertex Parameters ---------------------------------------------------------------
def test_vertex_inspect_reads_the_selection_and_its_token_edits_it(answered) -> None:
    editor, mcp = answered, answered.mcp
    service, session_id = editor.host.shadow_service, editor.host.shadow_session_id
    empty = mcp.ok("mesh_vertex_inspect")
    assert empty["count"] == 0 and empty["rows"] == [] and "select" in empty["message"]

    _select_part_vertices(editor, count=3)
    page = mcp.ok("mesh_vertex_inspect")
    part = service.working_mesh(session_id).submeshes[0]
    assert page["count"] == 3 and page["pages"] == 1 and page["page_size"] == 128
    row = page["rows"][0]
    assert (row["part"], row["vertex"]) == (0, 0)
    assert row["position"] == pytest.approx(list(part.vertices[0]))
    assert row["uv0"] == pytest.approx(list(part.uvs[0]))
    assert set(row) >= {"normal", "tangent", "weights", "cloth", "source", "part_name"}
    assert row["weights"]["influences"] and {"slot", "bone", "name", "weight"} <= set(row["weights"]["influences"][0])
    capabilities = page["capabilities"]
    assert set(capabilities) >= {"position", "uv0", "normal", "tangent", "weights", "cloth", "uv1", "colours"}
    assert all("reason" in value and "editable" in value for value in capabilities.values())
    token = page["token"]
    assert set(token) == {"session_id", "mesh_revision", "selection_revision", "topology_generation"}
    # Paged as the inspector pages: one vertex a page here.
    second = mcp.ok("mesh_vertex_inspect", {"page": 1, "page_size": 1})
    assert second["pages"] == 3 and [r["vertex"] for r in second["rows"]] == [1]
    assert mcp.error("mesh_vertex_inspect", {"page_size": 129})["code"] == "invalid_arguments"

    # The token as it came back: the edit is one History step through the inspector's own Apply.
    assert capabilities["position"]["editable"], capabilities["position"]
    before = part.vertices[1][2]
    edited = mcp.ok("mesh_vertex_edit", {"token": token, "edits": {"position": {"mode": "offset",
                                                                                "values": [None, None, 0.25]}}})
    assert edited["done"], edited
    assert edited["history"]["undo"] == edited["history_before"]["undo"] + 1
    after = service.working_mesh(session_id).submeshes[0]
    assert after.vertices[1][2] == pytest.approx(before + 0.25)
    # A text token, or one from before the edit, is refused.
    assert mcp.error("mesh_vertex_edit", {"token": "abc", "edits": {"position": {"values": [0, 0, 0]}}})[
        "code"] == "invalid_arguments"
    stale = mcp.ok("mesh_vertex_edit", {"token": token, "edits": {"position": {"values": [None, None, 0.0]}}})
    assert stale["history"]["undo"] == stale["history_before"]["undo"]
    assert service.working_mesh(session_id).submeshes[0].vertices[1][2] == pytest.approx(before + 0.25)



# ----- 2. Refit and Cloth archive pickers --------------------------------------------------
class _PickerService(_LookupService):
    """The catalogue service the pickers read: lookups, and Prepare for a collision input."""

    def __init__(self, catalogue, prepared_folder) -> None:
        super().__init__(catalogue)
        self.current_session = SimpleNamespace(session_id=SESSION)
        self.prepared_folder = prepared_folder
        self.prepared: list[int] = []

    def prepare_entry(self, request, *, ui_generation: int, dmm_overlay: bool = True) -> str:
        from PySide6.QtCore import QTimer

        from cdmw.domain.archives.catalogue import ArchiveEntryRef
        from cdmw.domain.archives.catalogue_operations import PrepareEntryResult

        dto = next(dto for dto in self.catalogue if dto.entry_id == request.entry_id)
        self.prepared.append(dto.entry_id)
        data = b"pabv" * 4
        path = self.prepared_folder / f"prepared-{dto.entry_id}{dto.extension}"
        path.write_bytes(data)
        request_id = f"prepare-{len(self.prepared)}"
        result = PrepareEntryResult(ArchiveEntryRef(dto.session_id, dto.entry_id, dto.identity, dto.path), str(path),
                                    len(data), hashlib.sha256(data).hexdigest())
        QTimer.singleShot(0, lambda: self.result_ready.emit(request_id, "prepare_entry", result))
        return request_id


class _Dependencies(QObject):
    """The dependency provider the Refit picker prepares a source with, answering at once."""

    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, service, parent=None, **_kwargs) -> None:
        super().__init__(parent)
        self.service = service

    def request(self, selected, *, ui_request_id: int, **_kwargs) -> bool:
        from PySide6.QtCore import QTimer

        from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet

        entry = self.service.compatibility_entry(selected)
        payload = ArchivePreviewDependencySet(selected.session_id, selected.entry_id, (entry,),
                                              {entry.path.casefold(): (entry,)}, {entry.basename.casefold(): (entry,)},
                                              1, False)
        QTimer.singleShot(0, lambda: self.ready.emit(ui_request_id, payload))
        return True

    def cancel(self, *, clear_snapshot: bool = False) -> None:
        pass


@pytest.fixture
def pickers(answered, tmp_path, monkeypatch):
    """Loaded archives behind the editor, and both pickers made to fail the test if they open."""

    from cdmw.ui.archive_browser import remote_preview_dependencies
    from cdmw.ui.mesh_editor import replace_from_archive_dialog
    from cdmw.ui.replace_assistant import archive_picker

    def opened(dialog, *_args, **_kwargs):
        raise AssertionError(f"the picker {type(dialog).__name__} opened")

    monkeypatch.setattr(replace_from_archive_dialog.ReplaceFromArchivePickerDialog, "exec", opened)
    monkeypatch.setattr(archive_picker.RemoteArchiveOriginalDialog, "exec", opened)
    monkeypatch.setattr(remote_preview_dependencies, "ArchiveRemotePreviewDependencyProvider", _Dependencies)
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    service = _PickerService([_dto(7, "character/model/cd_phm_00_body.pac"),
                              _dto(8, "character/bin__/cd_phm_00_body.pabv"),
                              _dto(9, "character/model/cd_weapon_sword.pac")], prepared)
    answered.ui.archive = SimpleNamespace(archive_catalogue_service=service, archive_remote_bridge=_Bridge())
    answered.service_archives = service
    yield answered
    answered.ui.archive = None


def _commands(editor) -> list[tuple[str, dict]]:
    return [(m["command"], m["arguments"]) for m in editor.sent if m.get("event") == "cdmw_command"]


def test_an_archive_picker_command_without_a_path_is_refused_before_anything_is_sent(pickers) -> None:
    editor, mcp = pickers, pickers.mcp
    for tool, arguments in (("mesh_refit", {"action": "choose_archive", "arguments": {"role": "body"}}),
                            ("mesh_cloth", {"action": "collision_input",
                                            "arguments": {"role": "body", "source": "archive"}})):
        error = mcp.error(tool, arguments)
        assert error["code"] == "invalid_arguments" and "archive_path" in error["message"], error
    assert _commands(editor) == []
    missing = mcp.error("mesh_cloth", {"action": "collision_input",
                                       "arguments": {"role": "body", "archive_path": "character/none.pabv"}})
    assert missing["code"] == "not_found" and _commands(editor) == []
    wrong = mcp.error("mesh_cloth", {"action": "collision_input", "arguments": {
        "role": "weapon", "archive_path": "character/bin__/cd_phm_00_body.pabv"}})
    assert wrong["code"] == "invalid_arguments" and ".pac" in wrong["message"]
    assert _commands(editor) == []


def test_an_archive_path_answers_the_refit_and_cloth_pickers_without_opening_them(pickers, monkeypatch) -> None:
    editor, mcp = pickers, pickers.mcp
    ui = editor.ui
    reached: dict[str, dict] = {}

    def refit_source(args, _stop_event):
        reached["refit"] = dict(args)
        raise ValueError("Recorded the Refit source.")

    def collision_input(_authoring, args, _stop_event):
        reached["cloth"] = dict(args)
        raise ValueError("Recorded the collision input.")

    monkeypatch.setattr("cdmw.workers.mesh_archive_refit_worker.prepare_archive_refit_source", refit_source)
    monkeypatch.setattr("cdmw.services.mesh_rust_jiggle.set_cloth_collision_input", collision_input)

    body = "character/model/cd_phm_00_body.pac"
    refit = mcp.ok("mesh_refit", {"action": "choose_archive", "arguments": {"role": "body", "archive_path": body}})
    assert refit["done"] and refit["archive_path"] == body and not refit.get("asked"), refit
    # The helper carried the button's own arguments; the file went to the worker host-side only.
    assert _commands(editor)[-1] == ("refit_choose_archive", {"role": "body"})
    # The worker's refusal comes back as the status line, as after the picker.
    assert "Recorded the Refit source." in refit["status"]
    source = reached["refit"]
    assert source["role"] == "body" and source["_archive_entry"].path == body
    assert source["_archive_dependencies"].selected_entry.path == body
    assert source["_primary_entry"].identity == ui._current_target_entry().identity

    volumes = "character/bin__/cd_phm_00_body.pabv"
    cloth = mcp.ok("mesh_cloth", {"action": "collision_input", "arguments": {"role": "body", "archive_path": volumes}})
    assert cloth["done"] and not cloth.get("asked"), cloth
    assert _commands(editor)[-1] == ("cloth_collision_input", {"role": "body", "source": "archive"})
    assert "Recorded the collision input." in cloth["status"]
    given = reached["cloth"]
    assert set(given) == {"role", "_archive_entry", "_archive_prepared"} and given["_archive_entry"].entry_id == 8
    assert editor.service_archives.prepared == [8]
    # Each offer was used once; none is left to answer the user's next click on either button.
    assert not getattr(ui, "_host_archive_choices", None)
    assert not getattr(ui, "_archive_refit_picker_active", False)



def test_a_refit_choice_is_prepared_by_the_real_dependency_provider(tmp_path) -> None:
    """The Refit picker's own provider resolves the file and its dependency set: the
    choice is what the picker would return, and the provider is released afterwards."""

    import time
    from dataclasses import replace

    from PySide6.QtWidgets import QApplication, QWidget

    from cdmw.domain.archives.catalogue import ArchiveAssociationResult, ArchiveDurableIdentity, ArchiveEntryRef
    from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult, PrepareEntryResult
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
    from cdmw.ui.mesh_editor import host_archive_choice

    class Service(_LookupService):
        progress = Signal(str, object)

        def __init__(self, catalogue) -> None:
            super().__init__(catalogue)
            self.current_session = SimpleNamespace(session_id=SESSION)
            self.asked: list[str] = []

        def find_association_candidates(self, request, *, ui_generation: int) -> str:
            self.asked.append("association")
            return "association-1"

        def prepare_entries(self, request, *, ui_generation: int, dmm_overlay: bool = True) -> str:
            self.asked.append("prepare")
            self.prepare_request = request
            return "prepare-1"

    pamt, paz = tmp_path / "0.pamt", tmp_path / "0.paz"
    pamt.write_bytes(b"owned catalogue")
    paz.write_bytes(b"owned archive")
    body = replace(_dto(7, "character/model/cd_phm_00_body.pac"), source_pamt=str(pamt), paz_file=str(paz),
                   identity=ArchiveDurableIdentity("character/model/cd_phm_00_body.pac", str(pamt).casefold(), 0, 700))
    target = _dto(9, "character/model/cd_cloak.pac")
    service = Service([body, target])

    class Tab(QWidget):
        def window(self):  # noqa: D401 - the owner, as a detached tab's window gives it
            return owner

    owner = SimpleNamespace(archive=SimpleNamespace(archive_catalogue_service=service, archive_remote_bridge=_Bridge()))
    tab = Tab()
    tab._current_target_entry = lambda: ArchiveCatalogueService.compatibility_entry(target)
    box: dict[str, object] = {}
    app = QApplication.instance()

    def pump(until, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not until() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert until(), box

    try:
        host_archive_choice.start(tab, host_archive_choice.REFIT_COMMAND, "body", body.path,
                                  on_done=lambda choice: box.update(choice=choice),
                                  on_failed=lambda message: box.update(error=message))
        pump(lambda: "association" in service.asked or "error" in box)
        service.result_ready.emit("association-1", "find_association_candidates",
                                  ArchiveAssociationResult(SESSION, 7, (), 0, False))
        pump(lambda: "prepare" in service.asked or "error" in box)
        payload = b"owned source " * 4
        source = tmp_path / "7.pac"
        source.write_bytes(payload)
        prepared = PrepareEntryResult(ArchiveEntryRef(SESSION, 7, body.identity, body.path), str(source),
                                      len(payload), hashlib.sha256(payload).hexdigest(), "owned fixture")
        service.result_ready.emit("prepare-1", "prepare_entry",
                                  PrepareEntriesResult(SESSION, (prepared,), 1, 1, len(payload)))
        pump(lambda: "choice" in box or "error" in box)
        assert "error" not in box, box
        choice = box["choice"]
        assert choice.role == "body" and choice.path == body.path
        context = choice.arguments["_archive_dependencies"]
        assert context.selected_entry.path == body.path and context.remote
        assert choice.arguments["_archive_entry"] is context.selected_entry
        # The provider is released once the choice is made, and nothing is left running.
        from PySide6.QtCore import QEvent

        # deleteLater runs once the event loop has it; the app's loop does, the test flushes it.
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert all(type(child).__name__ != "ArchiveRemotePreviewDependencyProvider" for child in tab.children())
    finally:
        tab.deleteLater()
        app.processEvents()


# ----- 3. Layers: Copy ------------------------------------------------------------------
def test_a_layer_copy_sent_by_name_copies_the_current_selection(answered) -> None:
    editor, mcp = answered, answered.mcp
    service, session_id = editor.host.shadow_service, editor.host.shadow_session_id
    faces = len(service.working_mesh(session_id).submeshes[0].faces)
    assert mcp.ok("mesh_select", {"faces": {"0": list(range(faces))}})["done"]
    copied = mcp.ok("mesh_layers", {"action": "copy"})
    assert copied["done"], copied
    # The copy carried no selection: the session's own was copied, not an empty one.
    sent = [m for m in editor.sent if m.get("event") == "cdmw_command"][-1]
    assert (sent["command"], sent["arguments"]) == ("layer_copy", {})
    assert service._session(session_id).native_clipboard_ready, copied["status"]


# ----- 5. Export and Import Replacement wait for the editor -------------------------------
def test_export_and_import_replacement_wait_for_the_editor_and_say_how_it_went(answered, profile) -> None:  # noqa: F811
    editor, mcp = answered, answered.mcp
    exported = profile / "exchange" / "part.obj"
    exported.parent.mkdir(parents=True, exist_ok=True)
    result = mcp.ok("mesh_export", {"path": str(exported)})
    assert result["sent"] and result["done"], result
    assert exported.is_file()

    imported = mcp.ok("mesh_replacement_import", {"path": str(exported)})
    assert imported["done"], imported
    pending = mcp.ok("mesh_replacement_state")["pending"]
    assert pending is not None and pending["sources"] and pending["targets"], pending
    cancelled = mcp.ok("mesh_replacement_cancel")
    assert cancelled["done"] and mcp.ok("mesh_replacement_state")["pending"] is None


# ----- 7. Geometry channels ----------------------------------------------------------------
def test_geometry_reads_skinning_tangents_colours_extra_uvs_morphs_and_refuses_other_lods(answered) -> None:
    editor, mcp = answered, answered.mcp
    service, session_id = editor.host.shadow_service, editor.host.shadow_session_id
    part = service._session(session_id).working_mesh.submeshes[0]
    count = len(part.vertices)

    def rows(what, **more):
        return mcp.ok("mesh_geometry", {"part": 0, "what": what, "limit": 500, **more})

    indices = rows("bone_indices")
    assert indices["rows"] == [list(row) for row in part.bone_indices][:500] and indices["total"] == count
    # Slots, not bones: with no skeleton attached the reason is said, not a guess.
    assert "palette" in indices or "palette_reason" in indices
    weights = rows("bone_weights")
    assert weights["rows"][0] == pytest.approx(list(part.bone_weights[0]))
    tangents = rows("tangents")
    assert tangents["total"] == len(part.tangents)
    colours = rows("vertex_colors")
    if not part.vertex_colors:
        assert colours["rows"] == [] and "not decoded" in colours["message"]
    assert mcp.error("mesh_geometry", {"part": 0, "what": "uv_sets"})["code"] == "not_found"
    assert mcp.error("mesh_geometry", {"part": 0, "what": "morph_targets", "morph": "smile"})["code"] == "not_found"
    saved = (dict(part.uv_sets), dict(part.morph_targets))
    part.uv_sets[1] = [(0.5, 0.25)] * count
    part.morph_targets["smile"] = [(0.0, 0.0, 0.01)] * count
    try:
        summary = mcp.ok("mesh_geometry", {"part": 0})
        assert summary["extra_uv_sets"] == [1] and summary["morphs"] == ["smile"] and summary["lod"] == 0
        assert rows("uv_sets", uv_set=1)["rows"][0] == pytest.approx([0.5, 0.25])
        smile = rows("morph_targets", morph="smile")
        assert smile["morph"] == "smile" and smile["rows"][0] == pytest.approx([0.0, 0.0, 0.01])
    finally:
        part.uv_sets.clear()
        part.uv_sets.update(saved[0])
        part.morph_targets.clear()
        part.morph_targets.update(saved[1])
    # The shown LOD is the working edit; a PAC's other LODs are not decoded, and that is said.
    assert mcp.ok("mesh_geometry", {"part": 0, "lod": 0})["vertices"] == count
    other = mcp.error("mesh_geometry", {"part": 0, "lod": 1})
    assert other["code"] == "unavailable" and "PAMLOD" in other["message"]


def test_a_pamlods_other_levels_are_read_from_the_file_as_stored() -> None:
    from cdmw.mcp.errors import ToolError
    from cdmw.mcp.mesh_tools import _lod_parts
    from cdmw.modding.mesh_parser import parse_pamlod
    from tests.static_mesh_fixtures import shipped_pamlod

    data = shipped_pamlod(version=4, packed=False)
    stored = parse_pamlod(data, "object/stone.pamlod")
    assert len(stored.lod_levels) > 1
    shown = SimpleNamespace(submeshes=stored.lod_levels[0], lod_levels=[], format="pamlod", path="object/stone.pamlod")
    service = SimpleNamespace(working_mesh=lambda _sid: shown,
                              _session=lambda _sid: SimpleNamespace(original_data=data))
    view = SimpleNamespace(lod_index=0, mesh_format="pamlod")
    parts, source = _lod_parts(service, "s", view, 0)
    assert source == "working" and parts == list(stored.lod_levels[0])
    parts, source = _lod_parts(service, "s", view, 1)
    assert source == "file" and [len(p.vertices) for p in parts] == [len(p.vertices) for p in stored.lod_levels[1]]
    with pytest.raises(ToolError) as refused:
        _lod_parts(service, "s", view, len(stored.lod_levels) + 3)
    assert refused.value.code == "not_found"


# ----- 8. The docked Texture Editor's Close ----------------------------------------------
def test_close_panel_hides_the_docked_texture_editor_and_keeps_its_edits(connect, tmp_path) -> None:  # noqa: F811
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication, QWidget

    from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget
    from tests.test_mesh_editor_texture_panels_shown import _FakeEditor, _manifest, _settle
    from tests.test_mesh_rust_embedding import _tab

    tab = _tab(tmp_path)
    holder = QWidget()
    try:
        workspace = tab.standalone_workspace
        textures, tools = workspace.textures_dock, workspace.texture_tools_dock
        tools._editor_factory = _FakeEditor
        tab.resize(1400, 800)
        tab.show()
        workspace.setEnabled(True)
        tab.textures_toggle_button.click()
        textures.set_manifest(_manifest(), session_root=tmp_path)
        session = tab.live_edit._live_texture_session_id()
        tools.open_target(LiveTextureTarget(session_id=session, source_path=str(tmp_path / "a.dds"),
                                            source_sha256="ab" * 32, channel="base_color", display_name="a.dds"))
        image = QImage(4, 4, QImage.Format.Format_RGBA8888)
        image.fill(QColor("#336699"))
        tab.live_edit._on_texture_window_edit(session, "ab" * 32, image, True)
        _settle()
        target = tools.target
        assert tools.isVisible() and target is not None
        holder.active = tab
        mcp = connect(SimpleNamespace(shell=SimpleNamespace(mesh_editor_tab=holder)))
        closed = mcp.ok("textures_close_panel")
        _settle()
        assert closed["closed"] and not closed["shown"] and closed["texture"] == "a.dds", closed
        assert not tools.isVisible() and textures.isVisible() and tools.target is target
        assert tab.live_edit._live_texture_updates.edited_textures()
        # Hidden already: said so, nothing pressed.
        assert mcp.error("textures_close_panel")["code"] == "unavailable"
    finally:
        holder.deleteLater()
        tab.deleteLater()
        QApplication.processEvents()


# ----- 6. The panel tools' arguments, typed ----------------------------------------------
def test_every_panel_command_has_its_own_typed_shape_matching_the_hosts_tables() -> None:
    from cdmw.mcp.mesh_edit_tools import PANEL_COMMANDS
    from cdmw.mcp.mesh_panel_schemas import PANELS, PARAMS
    from cdmw.services.mesh_rust_authoring import _HOST_MESH_ACTION_PARAMS, _HOST_TOPOLOGY_ACTION_PARAMS

    # Every command the panel tools send has a shape, and no shape names a command they do not send.
    assert {family: set(table) for family, table in PANELS.items()} == {
        family: set(PANEL_COMMANDS[family]) for family in PANELS}
    assert "hair" not in PANELS  # Hair Tools' shapes are another change's
    # The params the host takes for each topology and mesh action, exactly.
    assert {name: set(shape["properties"]) for name, shape in PARAMS["topology"].items()} == {
        name: set(keys) for name, keys in _HOST_TOPOLOGY_ACTION_PARAMS.items()}
    assert {name: set(shape["properties"]) for name, shape in PARAMS["mesh_action"].items()} == {
        name: set(keys) for name, keys in _HOST_MESH_ACTION_PARAMS.items()}
    for table in (*PANELS.values(), *PARAMS.values()):
        for shape in table.values():
            assert set(shape["required"]) <= set(shape["properties"])
            assert "selection" not in shape["properties"] and not any(k.startswith("_") for k in shape["properties"])
    # The fields named in the audit, with their documented shapes.
    shader = PANELS["replacement"]["shader_controls"]["properties"]
    assert shader["texture_files"]["type"] == "object" and "parameter: path" in shader["texture_files"]["description"]
    assert {"jiggle", "physics_profile", "collision_volumes", "weapon_collisions"} <= set(PANELS["replacement"])
    assert PANELS["morph"]["create"]["properties"]["definition"]["required"] == [
        "profile_id", "profile_name", "definition_id", "label"]
    assert "definition" in PANELS["morph"]["capture_authored"]["required"]


def test_the_tool_list_shows_each_actions_fields_and_a_wrong_field_is_refused_before_sending(answered) -> None:
    editor, mcp = answered, answered.mcp
    listed = {tool["name"]: tool for tool in mcp.request("tools/list")["result"]["tools"]}
    refit = listed["mesh_refit"]
    assert "configure {submesh_indices, enabled?" in refit["description"]
    assert refit["inputSchema"]["properties"]["arguments"]["properties"]["clearance_percent"]["maximum"] == 5
    part = listed["mesh_part_options"]["inputSchema"]["properties"]["arguments"]["properties"]
    assert "texture_files" in part and "shader_controls" in part
    params = listed["mesh_topology"]["inputSchema"]["properties"]["params"]["properties"]
    assert params["cuts"]["maximum"] == 16
    assert listed["mesh_hair"]["inputSchema"]["properties"]["arguments"] == {"type": "object"}

    sent = len(_commands(editor))
    # A field another action takes is not this one's; a required one left out; a value of the wrong type.
    wrong_field = mcp.error("mesh_layers", {"action": "rename", "arguments": {"layer_id": "base", "visible": True}})
    assert wrong_field["code"] == "invalid_arguments" and "layer_id, name" in wrong_field["message"]
    missing = mcp.error("mesh_weights", {"action": "adjust_weight", "arguments": {}})
    assert missing["code"] == "invalid_arguments" and "delta" in missing["message"]
    typed = mcp.error("mesh_cloth", {"action": "pin_set", "arguments": {"value": 0.5}})
    assert typed["code"] == "invalid_arguments" and "boolean" in typed["message"]
    params_wrong = mcp.error("mesh_topology", {"action": "inset", "params": {"offset": [0, 0, 1]}})
    assert params_wrong["code"] == "invalid_arguments" and "amount" in params_wrong["message"]
    nested = mcp.error("mesh_part_options", {"action": "jiggle", "arguments": {"part_ids": ["a"], "rule": {}}})
    assert nested["code"] == "invalid_arguments" and "below_y" in nested["message"]
    assert len(_commands(editor)) == sent
    # A right one goes through as before.
    assert mcp.ok("mesh_layers", {"action": "visibility", "arguments": {"layer_id": "base", "visible": True}})[
        "history"] is not None
    assert _commands(editor)[-1] == ("layer_visibility", {"layer_id": "base", "visible": True})


def _sample(schema, every=False):
    """The smallest value ``schema`` takes: required fields only (or ``every`` field), the first enum value,
    in range."""

    kinds = schema.get("type")
    kind = next((k for k in (kinds if isinstance(kinds, list) else [kinds]) if k != "null"), "null")
    if "enum" in schema:
        return schema["enum"][0]
    if kind == "object":
        names = list(schema.get("properties") or ()) if every else list(schema.get("required") or ())
        return {name: _sample(schema["properties"][name], every) for name in names}
    if kind == "array":
        item = schema.get("items") or {"type": "integer"}
        return [_sample(item, every) for _ in range(int(schema.get("minItems", 0)))]
    if kind == "string":
        return "x" * max(1, int(schema.get("minLength", 1)))
    if kind == "integer":
        return int(schema.get("minimum", 0))
    if kind == "number":
        return float(schema.get("minimum", 0))
    if kind == "boolean":
        return False
    return None


#: The Python handlers that refuse unknown fields themselves: a shape listing a field they do not take
#: shows here as their own "unsupported arguments" refusal.
_STRICT_WORDS = ("unsupported arguments", "Unsupported vertex", "Invalid experimental shader",
                 "Invalid island inclusion request", "Invalid guide creation request",
                 "Choose whether to create or restore weapon colliders", "Choose a collision volume set to edit")


@pytest.mark.parametrize("every", [False, True], ids=["required", "every-field"])
def test_one_call_per_panel_action_passes_its_shape_and_reaches_the_host(answered, every) -> None:
    from cdmw.mcp.mesh_panel_schemas import PANELS, PARAMS

    mcp = answered.mcp
    tools = {"rig": "mesh_weights", "morph": "mesh_morph", "refit": "mesh_refit", "cloth": "mesh_cloth",
             "layer": "mesh_layers", "replacement": "mesh_part_options"}
    calls = [(tools[family], {"action": action, "arguments": _sample({"type": "object", **shape}, every)})
             for family, table in PANELS.items() for action, shape in table.items()]
    calls += [(f"mesh_{family}", {"action": action, "params": _sample({"type": "object", **shape}, every)})
              for family, table in PARAMS.items() for action, shape in table.items()]
    checked = []
    for tool, arguments in calls:
        result = mcp.call(tool, arguments)
        content = result["structuredContent"]
        if result["isError"]:
            # Refused before sending, but never by the shape check (its messages name the tool's family or
            # the params): the archive choices need loaded archives, and Cloth's inputs are one shape at a time.
            message = str(content["error"]["message"])
            assert not (message.startswith("mesh ") or " params for " in message), (tool, arguments, content)
            continue
        status = str(content.get("status") or "")
        assert not any(word in status for word in _STRICT_WORDS), (tool, arguments, status)
        checked.append(tool)
    assert len(checked) > 80
