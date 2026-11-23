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
