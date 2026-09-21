"""Guide creation through shadow edits, preview, history, drafts and Build Mod."""

from contextlib import ExitStack
from dataclasses import replace
import json
import threading
from types import SimpleNamespace

import pytest

from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.modding.pac_cloth import decode_pac_cloth_binding, pac_cloth_lods
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_draft import save_replacement_state, load_replacement_state
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, read_owned_payload_reference
from cdmw.ui.mesh_editor.replacement_flow import prepare_replacement_event
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_cloth_influence import shadow_output
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_pac_cloth_guide_builder import guide_free_pac, PALETTE


@pytest.fixture
def guide_host(tmp_path, monkeypatch):
    data = guide_free_pac()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: data)
    source, service, host = _open_exact_session(tmp_path / "session")
    session = host.shadow_service._session(host.shadow_session_id)
    identity = tuple(float(i == j) for i in range(4) for j in range(4))
    bones = [Bone(index=i, name=f"bone{i}", name_hash=value, parent_index=-1,
                  bind_matrix=identity, inv_bind_matrix=identity, local_bind_matrix=identity, inv_local_bind_matrix=identity)
             for i, value in enumerate(reversed(PALETTE))]
    session.skeleton = Skeleton(path="owned.pab", bones=bones, bone_count=8, parser_mode="fixed")
    entry = ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0)
    keys = [part["id"] for part in host.state_payload()["replacement"]["parts"]]
    args = {"part_ids": keys, "source_lod": 0, "fixed_above": .5, "_archive_entry": entry,
            "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})}
    yield SimpleNamespace(source=source, service=service, host=host, session=session, entry=entry, args=args)
    if not host.closed:
        host.cancel()
    service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def test_create_preview_history_restore_finish_draft_and_build_mod(guide_host, tmp_path):
    case, host = guide_host, guide_host.host
    state = host.state_payload()
    assert state["cloth_guides"]["available"] and not state["cloth"]["available"]
    initial_revision = case.service.session_view(host.authoritative_session_id).revision
    response = command(host, "replacement_guides", case.args)
    state = response["state"]
    assert state["cloth"]["available"] and state["cloth"]["parts"][0]["lod_counts"] == [4]*4
    assert case.service.session_view(host.authoritative_session_id).revision == initial_revision
    result = shadow_output(host)
    guides = decode_pac_cloth_guides(result)
    assert len(guides.vertices) == 4
    decoded = state["jiggle"]["decoded"]
    assert decoded["available"] and decoded["cloth"]["guide_count"] == 4, decoded
    payload = read_owned_payload_reference(host.root, decoded["file"])
    assert payload["rig"]["bone_palette"] == list(reversed(range(8)))
    assert payload["cloth"]["fixed"] == [False, False, True, True]
    records = [bytes.fromhex(row) for row in payload["parts"][0]["records"]]
    assert all(decode_pac_cloth_binding(row, 0) for row in records)
    preview = state["jiggle"]["overlay_parts"][0]["preview"]
    assert preview["original_cloth_bytes"] == [63]*4 and preview["current_cloth_bytes"] == [0]*4
    assert case.session.original_data == case.source
    revision = case.session.revision
    command(host, "replacement_guides", case.args)
    assert case.session.revision == revision
    command(host, "undo")
    assert shadow_output(host) == case.source
    command(host, "redo")
    assert shadow_output(host) == result
    command(host, "replacement_guides", {"part_ids": case.args["part_ids"], "reset": True})
    assert shadow_output(host) == case.source and not host.state_payload()["cloth"]["available"]
    command(host, "undo")
    assert shadow_output(host) == result
    host.finish(_request(host, "finish_request", 22))
    sid = host.authoritative_session_id
    final = case.service.capture_export_snapshot(sid)
    draft = tmp_path / "draft" / "mesh_layers.json"
    case.service._session(sid).mesh_layer_project_path = draft
    case.service.retry_mesh_layer_autosave(sid)
    with ExitStack() as stack:
        reopened, recovered_sid = open_editor(stack, case.source, final.mesh.path, draft)
        recovered = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=reopened, active_session_id=recovered_sid),
                                                   tmp_path / "recovered", process_generation=2)
        stack.callback(lambda: recovered.cancel() if not recovered.closed else None)
        assert recovered.shadow_service._session(recovered.shadow_session_id).skeleton is None
        assert shadow_output(recovered) == result
        assert recovered.state_payload()["cloth_guides"]["available"]
        tab = SimpleNamespace(standalone_rust_authoring_session=recovered, standalone_rust_closing=False)
        event = prepare_replacement_event(tab, recovered, {**_request(recovered, "command_request", 23),
            "command": "replacement_guides", "arguments": {"part_ids": case.args["part_ids"], "reset": True}})
        recovered.run_command(event)
        assert shadow_output(recovered) == case.source
        command(recovered, "undo")
        recovered.finish(_request(recovered, "finish_request", 24))
        from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
        worker = MeshDirectOutputWorker(1, reopened, recovered_sid, case.entry, kind="loose_mod", output_path=tmp_path / "mod")
        errors, completed = [], []
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, value: completed.append(value))
        worker.run()
        assert not errors and completed
        assert (tmp_path / "mod" / case.entry.path).read_bytes() == result


def test_generated_bindings_survive_disable_restore_and_comparison(guide_host):
    host, args = guide_host.host, guide_host.args
    command(host, "replacement_guides", args)
    enabled = shadow_output(host)
    command(host, "replacement_cloth", {"part_ids": args["part_ids"], "rule": {"amount": 0, "fixed_above": None, "fade": 0}})
    disabled = shadow_output(host)
    assert decode_pac_cloth_guides(disabled) == decode_pac_cloth_guides(enabled)
    assert all(decode_pac_cloth_binding(disabled, offset) is None for level in pac_cloth_lods(disabled)
               for offset in level.submeshes[0].source_vertex_offsets)
    state = host.state_payload()
    assert state["jiggle"]["overlay_parts"][0]["preview"]["current_cloth_bytes"] == [63]*4
    payload = read_owned_payload_reference(host.root, state["jiggle"]["decoded"]["file"])
    assert all(decode_pac_cloth_binding(bytes.fromhex(row), 0) for row in payload["parts"][0]["records"])
    command(host, "replacement_compare", {"mode": "original"})
    assert not host.state_payload()["jiggle"]["decoded"]["cloth"]["available"]
    command(host, "replacement_compare", {"mode": "edit"})
    assert host.state_payload()["jiggle"]["decoded"]["cloth"]["available"]
    command(host, "replacement_cloth", {"part_ids": args["part_ids"], "reset": True})
    assert shadow_output(host) == enabled
    command(host, "replacement_guides", {"part_ids": args["part_ids"], "reset": True})
    assert shadow_output(host) == guide_host.source


@pytest.mark.parametrize("fault", ["no_rig", "ambiguous_rig", "nonfinite", "lod", "all_fixed", "missing_pin", "bad_part", "duplicate", "cancel", "stale"])
def test_invalid_creation_is_inert(guide_host, fault):
    host, args, session = guide_host.host, dict(guide_host.args), guide_host.session
    request = _request(host, "command_request", 4)
    event = None
    if fault == "no_rig":
        session.skeleton = None
    elif fault == "ambiguous_rig":
        session.skeleton.bones[1].name_hash = session.skeleton.bones[0].name_hash
    elif fault == "nonfinite":
        args["fixed_above"] = float("nan")
    elif fault == "lod":
        args["source_lod"] = True
    elif fault == "all_fixed":
        args["fixed_above"] = -1
    elif fault == "missing_pin":
        args["fixed_above"] = 2
    elif fault == "bad_part":
        args["part_ids"] = ["missing"]
    elif fault == "duplicate":
        args["part_ids"] *= 2
    elif fault == "cancel":
        event = threading.Event()
        event.set()
    elif fault == "stale":
        request["base_revision"] -= 1
    before = session.revision
    with pytest.raises(Exception):
        host.run_command({**request, "command": "replacement_guides", "arguments": args}, stop_event=event)
    assert session.revision == before and session.replacement_state is None
    assert host.shadow_service.session_view(host.shadow_session_id).undo_count == 0
    assert shadow_output(host) == guide_host.source


def test_draft_version_checks_preserve_guides_and_existing_rules(guide_host, tmp_path):
    from cdmw.domain.mesh.jiggle import PacJiggleRule
    command(guide_host.host, "replacement_guides", guide_host.args)
    state = guide_host.session.replacement_state
    state = replace(state, parts=(replace(state.parts[0], jiggle=PacJiggleRule()),))
    directory = tmp_path / "generation"
    directory.mkdir()
    payload = save_replacement_state(state, tmp_path, directory)
    assert payload["version"] == 9 and load_replacement_state(payload, tmp_path) == state
    downgraded = json.loads(json.dumps(payload))
    downgraded["version"] = 8
    with pytest.raises(ValueError, match="version 9"):
        load_replacement_state(downgraded, tmp_path)
    payload["parts"][0].pop("cloth_guides")
    with pytest.raises(ValueError, match="no guide"):
        load_replacement_state(payload, tmp_path)


def test_cancel_after_generation_keeps_history_and_both_sessions_unchanged(guide_host, monkeypatch):
    import cdmw.services.mesh_replacement_import as owner
    case, stop = guide_host, threading.Event()
    original = owner.prepare_replacement_output
    def prepare(snapshot):
        output = original(snapshot)
        stop.set()
        return output
    monkeypatch.setattr(owner, "prepare_replacement_output", prepare)
    before = case.session.revision
    with pytest.raises(Exception, match="cancelled"):
        case.host.run_command({**_request(case.host, "command_request", 30), "command": "replacement_guides",
                               "arguments": case.args}, stop_event=stop)
    assert case.session.revision == before and case.session.replacement_state is None
    assert case.service._session(case.host.authoritative_session_id).replacement_state is None
    assert case.host.shadow_service.session_view(case.host.shadow_session_id).undo_count == 0


def test_guides_use_real_qt_preparation_and_worker(guide_host, monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from tests.test_mesh_rejection_logging import _Editor
    case, host = guide_host, guide_host.host
    app = QApplication.instance() or QApplication([])
    ui = _Editor()
    ui._initialize_rust_editor_runtime_state()
    ui.standalone_rust_authoring_session = host
    ui._current_target_entry = lambda: case.entry
    ui.window = lambda: ui
    monkeypatch.setattr("cdmw.ui.mesh_editor.replacement_flow.archive_workflow_dependency_context",
                        lambda owner, target: case.args["_archive_dependencies"])
    try:
        for reset in (False, True):
            args = {key: value for key, value in case.args.items() if not key.startswith("_")}
            args["reset"] = reset
            ui.standalone_rust_protocol_queue.append({**_request(host, "command_request", 40+reset),
                "command": "replacement_guides", "arguments": args})
            ui._start_next_rust_protocol_worker()
            deadline = time.monotonic()+15
            while ui.standalone_rust_protocol_thread is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            assert ui.standalone_rust_protocol_thread is None
            assert ui.responses[-1]["ok"], ui.responses[-1]
            assert (decode_pac_cloth_guides(shadow_output(host)) is None) is reset
        assert case.service._session(host.authoritative_session_id).replacement_state is None
    finally:
        if ui.standalone_rust_protocol_thread is not None:
            host.request_cancel()
            ui.standalone_rust_protocol_thread.quit()
            assert ui.standalone_rust_protocol_thread.wait(5000)
        ui.standalone_status_label.deleteLater()
        ui.deleteLater()
        app.processEvents()
