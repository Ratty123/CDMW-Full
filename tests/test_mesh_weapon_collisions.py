"""Owned single-root weapons: collider geometry, output, history and inputs."""

from contextlib import ExitStack
from dataclasses import replace
import math
import struct
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth_guides import PacClothGuideRule
from cdmw.domain.mesh.replacement import MeshReplacementState, ReplacementPart
from cdmw.models import ArchiveEntry
from cdmw.modding.mesh_parser import _parse_par_sections, parse_pac
from cdmw.modding.pabv_parser import decode_pac_embedded_volumes
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_cloth_guide_builder import create_pac_cloth_guides
from cdmw.modding.pac_weapon_collisions import create_weapon_colliders, preview_weapon_colliders, weapon_collision_layout
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from tests.test_pac_cloth_guide_builder import PALETTE, guide_free_pac
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_cloth_influence import shadow_output
from tests.test_mesh_jiggle_decoded_preview import rig_session, decoded
from tests.test_mesh_cloth_decoded_preview import collision_session
from tests.test_mesh_jiggle import jiggle_session


def weapon_fixture(*, parts=2):
    source = guide_free_pac(parts=parts)
    old = decode_pac_embedded_volumes(source)
    palette = old.file_offset - 24 - 2 - 4*len(old.bone_palette)
    bounds = old.file_offset - 24
    identity = tuple(float(i//4 == i%4) for i in range(16))
    name = b"B_Weapon_0001"
    bone = (struct.pack("<IB", PALETTE[0], len(name)) + name + struct.pack("<i", -1)
            + struct.pack("<64f3f4f3f", *(identity*4), 1, 1, 1, 0, 0, 0, 1, 0, 0, 0))
    block = struct.pack("<I", 1) + bone + b"\x01" + struct.pack("<HI", 1, PALETTE[0])
    result = bytearray(source[:palette] + block + source[bounds:])
    delta = len(result) - len(source)
    struct.pack_into("<I", result, 80, 0x41)
    struct.pack_into("<2I", result, 16, 0, _parse_par_sections(source)[0]["size"] + delta)
    for i in range(8):
        offset = 85 + 4*i
        struct.pack_into("<I", result, offset, struct.unpack_from("<I", source, offset)[0] + delta)
    for level in pac_cloth_lods(result):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                struct.pack_into("<2I", result, offset+20, 0, 0)
                result[offset+28:offset+34] = bytes((255, 0, 0, 0, 0, 0))
    return bytes(result)


def test_embedded_weapon_bones_locate_empty_and_generated_collision_sets():
    source = weapon_fixture()
    decoded = decode_pac_embedded_volumes(source)
    assert decoded.bone_palette == (PALETTE[0],)
    assert decoded.model_bones[0].name == "B_Weapon_0001"
    assert decoded.volumes == ()
    output = create_weapon_colliders(source)
    volumes = decode_pac_embedded_volumes(output)
    assert [v.flags for v in volumes.volumes] == [0, 1, 0, 1]
    assert all(v.bone_key == PALETTE[0] and v.usage == 1 and v.shape_type == 5 for v in volumes.volumes)
    assert create_weapon_colliders(output) == output
    before, after = _parse_par_sections(source), _parse_par_sections(output)
    assert all(source[a["offset"]:a["offset"]+a["size"]] == output[b["offset"]:b["offset"]+b["size"]]
               for a, b in zip(before[1:], after[1:]))
    assert source[decoded.file_end:80+before[0]["size"]] == output[volumes.file_end:80+after[0]["size"]]


def test_capsules_cover_rigid_geometry_and_exclude_guide_bound_parts():
    source = weapon_fixture()
    capsules = preview_weapon_colliders(source)
    for part, capsule in zip(pac_cloth_lods(source)[0].submeshes, capsules):
        a, b = capsule["center1"], capsule["center2"]
        edge = [y-x for x, y in zip(a, b)]
        for point in part.vertices:
            t = max(0., min(1., sum((p-x)*v for p, x, v in zip(point, a, edge))/sum(v*v for v in edge)))
            assert math.dist(point, [x+t*v for x, v in zip(a, edge)]) <= capsule["radius"] + 1e-6
    guided = create_pac_cloth_guides(source, {0: PacClothGuideRule(0, .4, (PALETTE[0],))})
    assert [row["source_ordinal"] for row in preview_weapon_colliders(guided)] == [1]
    assert len(decode_pac_embedded_volumes(create_weapon_colliders(guided)).volumes) == 2


def test_unknown_bones_footer_and_edited_binding_fail_without_mutating_source():
    source = weapon_fixture()
    end = decode_pac_embedded_volumes(source).model_bones[0].file_end
    bad = bytearray(source)
    bad[end] = 2
    with pytest.raises(ValueError, match="footer"):
        decode_pac_embedded_volumes(bytes(bad))
    mesh = parse_pac(source)
    mesh.submeshes[0].bone_indices[0] = (1,)
    with pytest.raises(ValueError, match="attachments"):
        preview_weapon_colliders(source, parts=mesh.submeshes)
    assert create_weapon_colliders(source) != source


def test_inconsistent_inverse_bind_is_rejected_and_existing_volumes_are_preserved():
    source = weapon_fixture()
    bone = decode_pac_embedded_volumes(source).model_bones[0]
    matrix_offset = bone.file_offset + 4 + 1 + len(bone.name.encode("ascii")) + 4
    invalid = bytearray(source)
    struct.pack_into("<f", invalid, matrix_offset + 64 + 12*4, 1.)
    with pytest.raises(ValueError, match="mutual inverses"):
        weapon_collision_layout(bytes(invalid))
    existing = bytearray(create_weapon_colliders(source))
    records = decode_pac_embedded_volumes(existing)
    struct.pack_into("<f", existing, records.volumes[0].file_offset + 70, .75)
    existing = bytes(existing)
    result = create_weapon_colliders(existing)
    new_records = decode_pac_embedded_volumes(result)
    assert len(new_records.volumes) == len(records.volumes) + 1
    assert existing[records.file_offset+2:records.file_end] == result[new_records.file_offset+2:records.file_end]
    assert create_weapon_colliders(result) == result


def test_weapon_intent_round_trips_only_in_version_14_drafts(tmp_path):
    generation = tmp_path / "generation"
    generation.mkdir()
    state = MeshReplacementState("owned.pac", "a"*64, (ReplacementPart("owned", 0),), weapon_collisions=True)
    payload = save_replacement_state(state, tmp_path, generation)
    assert payload["version"] == 14 and load_replacement_state(payload, tmp_path) == state
    for bad in ({**payload, "version": 13}, {**payload, "weapon_collisions": 1}, {**payload, "weapon_collisions": False}):
        with pytest.raises(ValueError, match="weapon collision"):
            load_replacement_state(bad, tmp_path)
    legacy = save_replacement_state(replace(state, weapon_collisions=False), tmp_path, generation)
    assert legacy["version"] == 2 and not load_replacement_state(legacy, tmp_path).weapon_collisions


def test_shadow_weapon_colliders_export_undo_restore_and_preserve_source(tmp_path, monkeypatch):
    source = weapon_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    with ExitStack() as stack:
        _, service, host = _open_exact_session(tmp_path / "session")
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        assert host.state_payload()["weapon_collisions"]["available"]
        entry = ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0)
        response = command(host, "replacement_weapon_collisions", {"enabled": True, "_archive_entry": entry,
            "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})})
        assert response["state"]["weapon_collisions"]["active"]
        assert len(decode_pac_embedded_volumes(shadow_output(host)).volumes) == 4
        session = host.shadow_service._session(host.shadow_session_id)
        assert session.original_data == source and session.replacement_state.weapon_collisions
        generation = tmp_path / "draft"
        generation.mkdir()
        restored = load_replacement_state(save_replacement_state(session.replacement_state, tmp_path, generation), tmp_path)
        assert restored.weapon_collisions
        command(host, "undo")
        assert host.shadow_service._session(host.shadow_session_id).replacement_state is None
        command(host, "redo")
        command(host, "replacement_weapon_collisions", {"enabled": False})
        assert shadow_output(host) == source


def test_weapon_colliders_use_qt_preparation_worker_finish_and_loose_mod_output(tmp_path, monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from tests.test_mesh_rejection_logging import _Editor
    from tests.test_mesh_rust_authoring_exact_output import _request

    source = weapon_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    app = QApplication.instance() or QApplication([])
    with ExitStack() as stack:
        _, service, host = _open_exact_session(tmp_path / "session")
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        entry = ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0)
        dependencies = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
        monkeypatch.setattr("cdmw.ui.mesh_editor.replacement_flow.archive_workflow_dependency_context", lambda owner, target: dependencies)
        ui = _Editor()
        ui._initialize_rust_editor_runtime_state()
        ui.standalone_rust_authoring_session = host
        ui._current_target_entry = lambda: entry
        ui.window = lambda: ui
        try:
            for enabled in (True, False, True):
                ui.standalone_rust_protocol_queue.append({**_request(host, "command_request", 40),
                    "command": "replacement_weapon_collisions", "arguments": {"enabled": enabled}})
                ui._start_next_rust_protocol_worker()
                deadline = time.monotonic() + 15
                while ui.standalone_rust_protocol_thread is not None and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.001)
                assert ui.standalone_rust_protocol_thread is None
                assert ui.responses[-1]["ok"], ui.responses[-1]
                assert bool(decode_pac_embedded_volumes(shadow_output(host)).volumes) is enabled
            host.finish(_request(host, "finish_request", 50))
            worker = MeshDirectOutputWorker(1, service, host.authoritative_session_id, entry,
                                           kind="loose_mod", output_path=tmp_path / "mod")
            errors, completed = [], []
            worker.error.connect(lambda *args: errors.append(args))
            worker.completed.connect(lambda *args: completed.append(args))
            worker.run()
            assert completed and not errors, errors
            output = (tmp_path / "mod" / entry.path).read_bytes()
            assert len(decode_pac_embedded_volumes(output).volumes) == 4
            assert service._session(host.authoritative_session_id).original_data == source
        finally:
            if ui.standalone_rust_protocol_thread is not None:
                host.request_cancel()
                ui.standalone_rust_protocol_thread.quit()
                assert ui.standalone_rust_protocol_thread.wait(5000)
            ui.standalone_status_label.deleteLater()


def test_weapon_reference_placement_and_clear_preserve_mesh_source_and_output(collision_session, tmp_path):
    import copy
    from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
    original, session, host = collision_session
    before = decoded(host)
    mesh, output = copy.deepcopy(session.working_mesh), shadow_output(host)
    history = (len(session.undo_stack), len(session.redo_stack))
    path = tmp_path / "weapon.pac"
    source = weapon_fixture()
    path.write_bytes(source)
    result = command(host, "cloth_collision_input", {"role": "weapon", "path": str(path)})
    assert result["result"]["changed"]
    assert result["state"]["jiggle"]["collision_inputs"] == {"weapon": "weapon.pac"}
    state = decoded(host)
    colliders = read_owned_payload_reference(host.root, state["file"])["cloth"]["weapon_colliders"]
    assert len(colliders) == 2 and state["cloth"]["weapon_collider_source"] == "reference"
    placement = {"offset": [3., 4., 5.], "rotation": [0., 0., 90.]}
    result = command(host, "cloth_collision_input", {"weapon_placement": placement})
    moved = read_owned_payload_reference(host.root, decoded(host)["file"])["cloth"]["weapon_colliders"]
    for a, b in zip(colliders, moved):
        for key in ("center1", "center2"):
            x, y, z = a[key]
            assert b[key] == pytest.approx([3-y, 4+x, 5+z])
        assert b["radius"] == a["radius"]
    assert result["state"]["jiggle"]["weapon_placement"] == {key: tuple(value) for key, value in placement.items()}
    revision = session.revision
    assert not command(host, "cloth_collision_input", {"weapon_placement": placement})["result"]["changed"]
    assert session.revision == revision
    path.write_bytes(b"changed externally")
    host.jiggle_source_cache = None
    assert decoded(host)["file"] == result["state"]["jiggle"]["decoded"]["file"]
    command(host, "cloth_collision_input", {"clear": True})
    assert decoded(host) == before
    assert session.working_mesh == mesh and session.original_data == original
    assert shadow_output(host) == output and (len(session.undo_stack), len(session.redo_stack)) == history


@pytest.mark.parametrize("failure", ["invalid", "cancel", "publish", "placement"])
def test_weapon_reference_failure_preserves_last_valid_input(collision_session, tmp_path, monkeypatch, failure):
    from cdmw.modding import pac_weapon_collisions
    from cdmw.services import mesh_rust_authoring
    from tests.test_mesh_rust_authoring_exact_output import _request

    original, session, host = collision_session
    path = tmp_path / "weapon.pac"
    path.write_bytes(weapon_fixture())
    command(host, "cloth_collision_input", {"role": "weapon", "path": str(path)})
    before = decoded(host)
    contents = (host.root / "jiggle-rig.json").read_bytes()
    inputs, revision = dict(host.cloth_collision_inputs), session.revision
    stop = threading.Event()
    args = {"role": "weapon", "path": str(path)}
    path.write_bytes(weapon_fixture(parts=1))
    if failure == "invalid":
        path.write_bytes(b"unknown PAC layout")
    elif failure == "cancel":
        fit = pac_weapon_collisions.preview_weapon_colliders
        def cancel(data, **kwargs):
            result = fit(data, **kwargs)
            stop.set()
            return result
        monkeypatch.setattr(pac_weapon_collisions, "preview_weapon_colliders", cancel)
    elif failure == "publish":
        def fail(*args, **kwargs):
            raise OSError("owned payload write failed")
        monkeypatch.setattr(mesh_rust_authoring, "_atomic_write_payload", fail)
    else:
        args = {"weapon_placement": {"offset": [float("nan"), 0., 0.], "rotation": [0., 0., 0.]}}
    with pytest.raises((ValueError, OSError, mesh_rust_authoring.RustMeshCancellationError)):
        host.run_command({**_request(host, "command_request", 3), "command": "cloth_collision_input",
                          "arguments": args}, stop_event=stop)
    assert host.cloth_collision_inputs == inputs and session.revision == revision
    assert decoded(host) == before and (host.root / "jiggle-rig.json").read_bytes() == contents
    assert session.original_data == original
