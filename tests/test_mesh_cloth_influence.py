"""Cloth edits own only proven render bindings, at every stored PAC LOD."""

from contextlib import ExitStack
import copy
from dataclasses import replace
import struct
import json
import hashlib
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.mesh_parser import _decode_pac_skin_influences, parse_pac
from cdmw.modding.pac_cloth import apply_pac_cloth_rules, pac_cloth_binding, pac_cloth_lods
from cdmw.modding.mesh_skinning import pack_pac_skin_weights
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_replacement_draft import load_replacement_state, save_replacement_state
from cdmw.services.mesh_replacement_import import initial_replacement_state
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command, prepare_source


def cloth_fixture():
    data = bytearray(_pac_fixture(skinned=True))
    for mesh in pac_cloth_lods(data):
        for part in mesh.submeshes:
            for i, offset in enumerate(part.source_vertex_offsets):
                if i == 0:
                    continue  # A genuinely rigid vertex must never acquire cloth.
                struct.pack_into("<2e", data, offset + 12, 102.0, 103.0)
                struct.pack_into("<I", data, offset + 24, 100 << 10 | 101 << 20 | 0xC0000000)
                data[offset + 32:offset + 36] = bytes((104, 82, 42, 27))
                data[offset + 39] = 0xC0
    return bytes(data)


@pytest.mark.parametrize("rule", [PacClothRule(0), PacClothRule(.5), PacClothRule(1, .5), PacClothRule(.7, .5, .3)])
def test_rules_apply_at_every_lod_and_preserve_all_other_bytes(rule):
    source = cloth_fixture()
    result = apply_pac_cloth_rules(source, {0: rule})
    expected = bytearray(source)
    for mesh in pac_cloth_lods(source):
        for part in mesh.submeshes:
            for position, offset in zip(part.vertices, part.source_vertex_offsets):
                binding = pac_cloth_binding(source, offset)
                if binding is None:
                    continue
                blend = rule.blend(binding[0], position[1])
                if blend == 63:
                    group = struct.unpack_from("<I", source, offset + 24)[0]
                    struct.pack_into("<I", expected, offset + 24, group & 0xC00003FF)
                    expected[offset + 12:offset + 16] = b"\0\0\0\x3c"
                    expected[offset + 32:offset + 36] = bytes(4)
                expected[offset + 39] = 0xC0 | blend
                assert _decode_pac_skin_influences(result, offset) == _decode_pac_skin_influences(source, offset)
    assert result == expected
    assert apply_pac_cloth_rules(source, {0: rule}) == result
    assert apply_pac_cloth_rules(source, {0: PacClothRule()}) == source


def test_boundary_and_fade_have_independent_numerical_contract():
    rule = PacClothRule(1, 2, 1)
    assert [rule.blend(0, y) for y in (3, 2, 1.5, 1, 0)] == [63, 63, 32, 0, 0]
    assert PacClothRule(.5).blend(20, 0) == 42
    assert rule.blend(63, 0) == 63


@pytest.mark.parametrize("values", [dict(amount=-1), dict(amount=2), dict(amount=float("nan")),
    dict(amount=True), dict(fixed_above=float("inf")), dict(fade=-1), dict(fade=1)])
def test_invalid_rules_are_rejected(values):
    with pytest.raises(ValueError):
        PacClothRule(**values)


def test_skin_edits_keep_cloth_guides_and_enforce_four_bone_capacity():
    data = cloth_fixture()
    offset = pac_cloth_lods(data)[0].submeshes[0].source_vertex_offsets[1]
    row = bytearray(data[offset:offset + 40])
    binding = pac_cloth_binding(row, 0)
    pack_pac_skin_weights(row, (1, 2, 3, 4), (.4, .3, .2, .1), context="test")
    assert pac_cloth_binding(row, 0) == binding
    assert _decode_pac_skin_influences(row, 0)[0] == (1, 2, 3, 4)
    before = bytes(row)
    with pytest.raises(ValueError, match="four skeletal"):
        pack_pac_skin_weights(row, (1, 2, 3, 4, 5), (.2,) * 5, context="test")
    assert row == before


def test_unsafe_bindings_and_missing_lods_fail_before_output():
    source = cloth_fixture()
    offset = pac_cloth_lods(source)[0].submeshes[0].source_vertex_offsets[1]
    bad = bytearray(source)
    struct.pack_into("<e", bad, offset + 12, float("nan"))
    with pytest.raises(ValueError, match="guide"):
        apply_pac_cloth_rules(bytes(bad), {0: PacClothRule(0)})
    with pytest.raises(ValueError, match="part"):
        apply_pac_cloth_rules(source, {8: PacClothRule(0)})
    with pytest.raises(ValueError, match="cloth bindings"):
        apply_pac_cloth_rules(_pac_fixture(skinned=True), {0: PacClothRule(0)})
    with pytest.raises((ValueError, struct.error)):
        apply_pac_cloth_rules(source[:200], {0: PacClothRule(0)})


@pytest.mark.parametrize("size_excess", [8, 1000])
def test_unreadable_lower_lod_disables_cloth_without_breaking_editor(tmp_path, monkeypatch, size_excess):
    source = bytearray(cloth_fixture())
    stored_size = struct.unpack_from("<I", source, 0x1c)[0]
    # LOD0 remains readable, but a lower LOD advertises undecoded data extending
    # into its neighbour or beyond the file. Inspection can still recover LOD0.
    struct.pack_into("<II", source, 0x18, stored_size, stored_size + size_excess)
    source = bytes(source)
    assert parse_pac(source, "damaged-lod.pac").total_faces == 2
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, session = _open_exact_session(tmp_path / "damaged-lod")
    try:
        state = session.state_payload()
        assert not state["cloth"]["available"]
        assert "PAC sections" in state["cloth"]["reason"]
        assert state["replacement"]["available"]
        with pytest.raises(ValueError, match="PAC sections"):
            apply_pac_cloth_rules(source, {0: PacClothRule(0)})
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_rejected_import_with_invalid_guides_keeps_session_unchanged(tmp_path, monkeypatch):
    source = bytearray(cloth_fixture())
    for mesh in pac_cloth_lods(source):
        for offset in mesh.submeshes[0].source_vertex_offsets[1:]:
            struct.pack_into("<e", source, offset + 12, float("nan"))
    source = bytes(source)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    _, service, session = _open_exact_session(tmp_path / "invalid-guides")
    try:
        assert not session.state_payload()["cloth"]["available"]
        result = prepare_source(session, tmp_path)
        key = result["state"]["replacement"]["pending"]["targets"][0]["id"]
        before = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        with pytest.raises(ValueError, match="cloth-guide index"):
            command(session, "replacement_apply", {"targets": [key], "materials": "original"})
        after = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        assert after.mesh == before.mesh
        assert after.mesh_revision == before.mesh_revision
        assert after.replacement_state is None
        assert session.shadow_service.session_view(session.shadow_session_id).undo_count == 0
        assert shadow_output(session) == source
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


@pytest.fixture
def cloth_session(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: cloth_fixture())
    source, service, session = _open_exact_session(tmp_path / "session")
    yield source, service, session
    if not session.closed:
        session.cancel()
    service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def apply_rule(session, tmp_path, rule, *, reset=False):
    part_id = session.state_payload()["cloth"]["parts"][0]["id"]
    return command(session, "replacement_cloth", {"part_ids": [part_id], "reset": reset,
        "rule": rule.to_dict(),
        "_archive_entry": ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0),
        "_archive_dependencies": SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})})


def shadow_output(session):
    snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
    if snapshot.replacement_state is None:
        return snapshot.original_data
    return prepare_replacement_output(snapshot).data


def test_authoring_undo_reset_finish_and_draft_reopen(cloth_session, tmp_path):
    from tests.test_mesh_editor_replacement_sequences import open_editor
    source, service, session = cloth_session
    original_revision = service.session_view(session.authoritative_session_id).revision
    ui = session.state_payload()["cloth"]
    assert ui["available"] and ui["lod_count"] == 4
    assert ui["parts"][0]["lod_counts"] == [3, 2, 2, 2]
    result = apply_rule(session, tmp_path, PacClothRule(0))
    assert result["state"]["cloth"]["parts"][0]["rule"]["amount"] == 0
    disabled = shadow_output(session)
    assert disabled == apply_pac_cloth_rules(source, {0: PacClothRule(0)})
    assert service.session_view(session.authoritative_session_id).revision == original_revision
    command(session, "undo")
    assert shadow_output(session) == source
    command(session, "redo")
    assert shadow_output(session) == disabled
    apply_rule(session, tmp_path, PacClothRule(), reset=True)
    assert shadow_output(session) == source
    apply_rule(session, tmp_path, PacClothRule(.6, .5, .25))
    expected = shadow_output(session)
    session.finish(_request(session, "finish_request", 22))
    final = service.capture_export_snapshot(session.authoritative_session_id)
    assert service.rebuild_result_from_snapshot(final)[0].data == expected
    draft = tmp_path / "draft" / "mesh_layers.json"
    service._session(session.authoritative_session_id).mesh_layer_project_path = draft
    service.retry_mesh_layer_autosave(session.authoritative_session_id)
    assert json.loads(draft.read_text())["format"] == "mesh_layer_project_v6"
    with ExitStack() as stack:
        reopened, sid = open_editor(stack, source, final.mesh.path, draft)
        restored = reopened.capture_export_snapshot(sid)
        assert restored.replacement_state.parts[0].cloth == PacClothRule(.6, .5, .25)
        assert reopened.rebuild_result_from_snapshot(restored)[0].data == expected


def test_replacement_import_retains_cloth_and_can_disable_it(cloth_session, tmp_path):
    _, _, session = cloth_session
    result = prepare_source(session, tmp_path)
    key = result["state"]["replacement"]["pending"]["targets"][0]["id"]
    command(session, "replacement_apply", {"targets": [key], "materials": "original"})
    imported = shadow_output(session)
    assert any(pac_cloth_binding(imported, offset) for mesh in pac_cloth_lods(imported)
               for part in mesh.submeshes for offset in part.source_vertex_offsets)
    apply_rule(session, tmp_path, PacClothRule(0))
    assert shadow_output(session) == apply_pac_cloth_rules(imported, {0: PacClothRule(0)})
    apply_rule(session, tmp_path, PacClothRule(), reset=True)
    assert shadow_output(session) == imported


def test_draft_schema_preserves_rules_and_rejects_downgrade(cloth_session, tmp_path):
    _, _, session = cloth_session
    state = initial_replacement_state(session.shadow_service.capture_export_snapshot(session.shadow_session_id))
    state = replace(state, parts=(replace(state.parts[0], cloth=PacClothRule(.5, .5, .2)),))
    directory = tmp_path / "generation"
    directory.mkdir()
    payload = save_replacement_state(state, tmp_path, directory)
    assert payload["version"] == 4
    assert load_replacement_state(payload, tmp_path) == state
    payload["version"] = 2
    with pytest.raises(ValueError, match="version 4"):
        load_replacement_state(payload, tmp_path)


def test_boundary_uses_neutral_display_height_at_every_lod(tmp_path, monkeypatch):
    from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: cloth_fixture())
    source, service, session = _open_exact_session(tmp_path / "neutral", neutral_appearance=appearance)
    try:
        part = session.state_payload()["cloth"]["parts"][0]
        assert part["min_y"] == pytest.approx(10.) and part["max_y"] == pytest.approx(12.)
        rule = PacClothRule(1, 11, .5)
        apply_rule(session, tmp_path, rule)
        expected = apply_pac_cloth_rules(source, {0: PacClothRule(1, .5, .25)})
        assert shadow_output(session) == expected
        session.finish(_request(session, "finish_request", 22))
        assert service.rebuild_result_from_snapshot(service.capture_export_snapshot(session.authoritative_session_id))[0].data == expected
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_topology_requires_identical_guide_bindings_for_derived_vertices():
    from cdmw.modding.mesh_pac_topology_builder import build_pac_topology_rebuild, topology_rebuild_blockers
    from cdmw.domain.mesh.topology import TOPOLOGY_PROTECTED_BYTES_DIVERGE
    from tests.test_mesh_pac_topology_serializer import _subdivided_quad
    source = bytearray(cloth_fixture())
    offsets = pac_cloth_lods(source)[0].submeshes[0].source_vertex_offsets
    # Make both parents cloth-bound, initially with the same binding.
    for a, b in ((12, 16), (24, 28), (32, 36), (39, 40)):
        source[offsets[0] + a:offsets[0] + b] = source[offsets[1] + a:offsets[1] + b]
    original = parse_pac(source, "cloth.pac")
    edited = _subdivided_quad(original)
    assert not topology_rebuild_blockers(original, edited, bytes(source))
    output = build_pac_topology_rebuild(original, edited, bytes(source))
    # The appended midpoint inherits the guide binding exactly.
    parsed = parse_pac(output, "cloth.pac")
    assert pac_cloth_binding(output, parsed.submeshes[0].source_vertex_offsets[-1]) == pac_cloth_binding(source, offsets[0])
    source[offsets[1] + 32] += 1
    original = parse_pac(source, "cloth.pac")
    assert TOPOLOGY_PROTECTED_BYTES_DIVERGE in topology_rebuild_blockers(original, _subdivided_quad(original), bytes(source))


@pytest.mark.parametrize("extra", [{"part_ids": []}, {"part_ids": ["wrong"]},
    {"rule": {"amount": float("nan"), "fixed_above": None, "fade": 0}}, {"reset": "true"}])
def test_invalid_command_is_inert(cloth_session, extra):
    source, _, session = cloth_session
    before = session.shadow_service.session_view(session.shadow_session_id).revision
    key = session.state_payload()["cloth"]["parts"][0]["id"]
    with pytest.raises(ValueError):
        command(session, "replacement_cloth", {"part_ids": [key], "rule": PacClothRule(0).to_dict(), **extra})
    assert session.shadow_service.session_view(session.shadow_session_id).revision == before
    assert shadow_output(session) == source


@pytest.mark.parametrize("command_name", ["replacement_cloth", "replacement_jiggle"])
def test_host_attaches_archive_context_to_cloth_command_without_file_dialog(tmp_path, monkeypatch, command_name):
    from tests.test_mesh_rust_editor_selection import _tab, _dispose, _archive_entry
    from PySide6.QtWidgets import QFileDialog
    tab = _tab(tmp_path)
    target = _archive_entry(tmp_path)
    context = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
    session = SimpleNamespace(shadow_session_id="owned",
        shadow_service=SimpleNamespace(_session=lambda sid: SimpleNamespace(replacement_state=None)))
    tab.standalone_rust_authoring_session = session
    tab._current_target_entry = lambda: target
    monkeypatch.setattr("cdmw.ui.mesh_editor.replacement_flow.archive_workflow_dependency_context", lambda owner, entry: context)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: pytest.fail("Cloth editing must not open a file picker"))
    class ReachedWorker(Exception):
        pass
    def capture_worker(request_id, active, event, **kwargs):
        assert active is session
        assert event["arguments"]["_archive_entry"] is target
        assert event["arguments"]["_archive_dependencies"] is context
        assert event["arguments"]["part_ids"] == ["owned:0"]
        assert kwargs["preparation_error"] == ""
        raise ReachedWorker
    monkeypatch.setattr("cdmw.workers.mesh_rust_editor_workers.MeshRustProtocolWorker", capture_worker)
    try:
        rule = PacClothRule(0).to_dict() if command_name == "replacement_cloth" else {"below_y": 1.2}
        tab.standalone_rust_protocol_queue.append({"event": "command_request", "command": command_name,
            "arguments": {"part_ids": ["owned:0"], "rule": rule}})
        with pytest.raises(ReachedWorker):
            tab._start_next_rust_protocol_worker()
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


@pytest.mark.parametrize("fault", ["missing", "downgrade"])
def test_cloth_draft_cannot_silently_lose_rules_or_downgrade(cloth_session, tmp_path, fault):
    from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
    source, _, session = cloth_session
    apply_rule(session, tmp_path, PacClothRule(.5))
    shadow = session.shadow_service
    draft = tmp_path / "draft" / "mesh_layers.json"
    shadow._session(session.shadow_session_id).mesh_layer_project_path = draft
    shadow.retry_mesh_layer_autosave(session.shadow_session_id)
    descriptor = json.loads(draft.read_text())
    path = draft.parent / descriptor["current_generation"] / "generation.json"
    generation = json.loads(path.read_text())
    if fault == "missing":
        generation["replacement"]["parts"][0].pop("cloth")
    else:
        descriptor["format"] = "mesh_layer_project_v2"
        generation["format"] = "mesh_layer_generation_v2"
    path.write_text(json.dumps(generation))
    descriptor["current_generation_manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    draft.write_text(json.dumps(descriptor))
    mesh = parse_pac(source, "cloth.pac")
    # A rejected generation must not overwrite geometry already loaded by the
    # caller, even when its descriptor disguises it as an older draft format.
    mesh.submeshes[0].vertices[0] = (17., 18., 19.)
    before = copy.deepcopy(mesh)
    with pytest.raises((ValueError, RuntimeError), match="Cloth"):
        load_mesh_layer_project(mesh, draft,
            expected_source_asset_sha256=hashlib.sha256(source).hexdigest())
    assert mesh == before
