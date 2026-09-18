"""Experimental jiggle edits change one lane and survive the real editor flow."""

from contextlib import ExitStack
import copy
from dataclasses import replace
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.domain.mesh.jiggle import PacJiggleRule
from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_jiggle import apply_pac_jiggle_rules
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from tests.test_mesh_cloth_influence import apply_rule, cloth_fixture, shadow_output
from tests.test_mesh_editor_replacement_regressions import _distinct_lods
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command, prepare_source


def jiggle_fixture(source=None):
    data = bytearray(cloth_fixture() if source is None else source)
    for lod, mesh in enumerate(pac_cloth_lods(data)):
        for part in mesh.submeshes:
            for vertex, offset in enumerate(part.source_vertex_offsets):
                data[offset + 36:offset + 39] = bytes((40 + vertex, 100 + lod, 249 + vertex % 7))
    return bytes(data)


@pytest.fixture
def jiggle_session(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: jiggle_fixture())
    source, service, host = _open_exact_session(tmp_path / "session")
    yield source, service, host
    if not host.closed:
        host.cancel()
    service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def archive_context(host):
    return {
        "_archive_entry": ArchiveEntry("owned-rust-exact.pac", host.root / "0009/0.pamt",
                                       host.root / "0009/0.paz", 0, 0, 0, 0, 0),
        "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={}),
    }


def set_jiggle(host, below_y=None, *, reset=False):
    key = host.state_payload()["jiggle"]["parts"][0]["id"]
    return command(host, "replacement_jiggle", {
        "part_ids": [key], "rule": {"below_y": below_y}, "reset": reset, **archive_context(host),
    })


@pytest.mark.parametrize("below_y", [None, .5])
def test_selected_region_changes_only_byte_38_at_every_lod(below_y):
    source = jiggle_fixture(_distinct_lods())
    result = apply_pac_jiggle_rules(source, {0: PacJiggleRule(below_y)})
    expected_addresses = set()
    for level in pac_cloth_lods(source):
        part = level.submeshes[0]
        expected_at_lod = {offset + 38 for point, offset in zip(part.vertices, part.source_vertex_offsets)
                           if below_y is None or point[1] < below_y}
        assert expected_at_lod
        expected_addresses.update(expected_at_lod)
    assert len(result) == len(source)
    assert {i for i, (a, b) in enumerate(zip(source, result)) if a != b} == expected_addresses
    assert all(result[address] == 255 for address in expected_addresses)
    assert apply_pac_jiggle_rules(result, {0: PacJiggleRule(below_y)}) == result
    assert apply_pac_jiggle_rules(source, {}) == source


@pytest.mark.parametrize("neutral", [False, True])
def test_authoring_undo_restore_finish_and_recovered_draft(tmp_path, monkeypatch, neutral):
    source = jiggle_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    with ExitStack() as stack:
        _, service, host = _open_exact_session(tmp_path / "session", neutral_appearance=appearance)
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        before = service.session_view(host.authoritative_session_id).revision
        state = host.state_payload()["jiggle"]
        assert state["available"] and state["lod_count"] == 4
        below_y = 11. if neutral else .5
        set_jiggle(host, below_y)
        expected = apply_pac_jiggle_rules(source, {0: PacJiggleRule(.5)})
        assert shadow_output(host) == expected
        assert service.session_view(host.authoritative_session_id).revision == before
        command(host, "undo")
        assert shadow_output(host) == source
        command(host, "redo")
        assert shadow_output(host) == expected
        set_jiggle(host, reset=True)
        assert shadow_output(host) == source
        set_jiggle(host, below_y)
        host.finish(_request(host, "finish_request", 22))
        final = service.capture_export_snapshot(host.authoritative_session_id)
        assert service.rebuild_result_from_snapshot(final)[0].data == expected
        assert final.original_data == source
        draft = tmp_path / "draft" / "mesh_layers.json"
        service._session(host.authoritative_session_id).mesh_layer_project_path = draft
        service.retry_mesh_layer_autosave(host.authoritative_session_id)
        assert json.loads(draft.read_text())["format"] == "mesh_layer_project_v7"
        reopened, sid = open_editor(stack, source, final.mesh.path, draft)
        restored = reopened.capture_export_snapshot(sid)
        assert restored.replacement_state.parts[0].jiggle == PacJiggleRule(below_y)
        assert reopened.rebuild_result_from_snapshot(restored)[0].data == expected


def test_jiggle_preserves_cloth_and_imported_output(jiggle_session, tmp_path):
    source, _, host = jiggle_session
    apply_rule(host, tmp_path, PacClothRule(.5))
    cloth_output = shadow_output(host)
    set_jiggle(host, .5)
    assert shadow_output(host) == apply_pac_jiggle_rules(cloth_output, {0: PacJiggleRule(.5)})
    set_jiggle(host, reset=True)
    assert shadow_output(host) == cloth_output
    pending = prepare_source(host, tmp_path)
    key = pending["state"]["replacement"]["pending"]["targets"][0]["id"]
    command(host, "replacement_apply", {"targets": [key], "materials": "original"})
    imported = shadow_output(host)
    set_jiggle(host)
    disabled = shadow_output(host)
    assert disabled == apply_pac_jiggle_rules(imported, {0: PacJiggleRule()})
    set_jiggle(host, reset=True)
    assert shadow_output(host) == imported
    assert host.shadow_service.capture_export_snapshot(host.shadow_session_id).original_data == source


def test_jiggle_draft_roundtrip_rejects_downgrade_and_keeps_older_payloads(jiggle_session, tmp_path):
    _, _, host = jiggle_session
    set_jiggle(host, .5)
    state = host.shadow_service.capture_export_snapshot(host.shadow_session_id).replacement_state
    directory = tmp_path / "generation"
    directory.mkdir()
    payload = save_replacement_state(state, tmp_path, directory)
    assert payload["version"] == 5
    assert load_replacement_state(payload, tmp_path) == state
    payload["version"] = 4
    with pytest.raises(ValueError, match="version 5"):
        load_replacement_state(payload, tmp_path)
    old = replace(state, parts=tuple(replace(part, jiggle=None) for part in state.parts))
    assert load_replacement_state(save_replacement_state(old, tmp_path, directory), tmp_path) == old


@pytest.mark.parametrize("extra", [
    {"part_ids": []}, {"part_ids": ["wrong"]}, {"part_ids": [0]},
    {"rule": {"below_y": float("nan")}}, {"rule": {"below_y": True}},
    {"rule": {"below_y": None, "strength": .5}}, {"reset": "true"},
])
def test_invalid_command_leaves_output_and_history_unchanged(jiggle_session, extra):
    source, _, host = jiggle_session
    before = host.shadow_service.session_view(host.shadow_session_id)
    key = host.state_payload()["jiggle"]["parts"][0]["id"]
    with pytest.raises(ValueError):
        command(host, "replacement_jiggle", {"part_ids": [key], "rule": {"below_y": .5},
                                               **archive_context(host), **extra})
    after = host.shadow_service.session_view(host.shadow_session_id)
    assert (after.revision, after.undo_count) == (before.revision, before.undo_count)
    assert shadow_output(host) == source


@pytest.mark.parametrize("fault", ["missing", "downgrade"])
def test_recovered_draft_cannot_silently_lose_jiggle(jiggle_session, tmp_path, fault):
    from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
    source, _, host = jiggle_session
    set_jiggle(host, .5)
    shadow = host.shadow_service
    draft = tmp_path / "draft" / "mesh_layers.json"
    shadow._session(host.shadow_session_id).mesh_layer_project_path = draft
    shadow.retry_mesh_layer_autosave(host.shadow_session_id)
    descriptor = json.loads(draft.read_text())
    path = draft.parent / descriptor["current_generation"] / "generation.json"
    generation = json.loads(path.read_text())
    if fault == "missing":
        generation["replacement"]["parts"][0].pop("jiggle")
    else:
        descriptor["format"] = "mesh_layer_project_v2"
        generation["format"] = "mesh_layer_generation_v2"
    path.write_text(json.dumps(generation), encoding="utf-8")
    descriptor["current_generation_manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    draft.write_text(json.dumps(descriptor), encoding="utf-8")
    mesh = shadow.capture_export_snapshot(host.shadow_session_id).mesh
    before = copy.deepcopy(mesh)
    with pytest.raises((ValueError, RuntimeError), match="[Jj]iggle"):
        load_mesh_layer_project(mesh, draft, expected_source_asset_sha256=hashlib.sha256(source).hexdigest())
    assert mesh == before


def test_missing_lower_lod_is_rejected_without_publishing(tmp_path, monkeypatch):
    source = bytearray(jiggle_fixture())
    stored_size = struct.unpack_from("<I", source, 0x1c)[0]
    struct.pack_into("<II", source, 0x18, stored_size, stored_size + 8)
    source = bytes(source)
    with pytest.raises(ValueError, match="PAC sections"):
        apply_pac_jiggle_rules(source, {0: PacJiggleRule()})
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / "damaged")
    try:
        ui = host.state_payload()["jiggle"]
        assert not ui["available"] and "PAC sections" in ui["reason"]
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)
