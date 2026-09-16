"""Interactive skin edits respect cloth record capacity and undo history."""

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.services.mesh_rust_authoring import RustMeshValidationError
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_cloth import pac_cloth_binding, pac_cloth_lods
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_cloth_influence import apply_rule, cloth_fixture, shadow_output
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command


@pytest.fixture
def rig_session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: cloth_fixture(),
    )
    source, service, host = _open_exact_session(tmp_path / "host", resolved_rig=True)
    try:
        yield source, service, host
    finally:
        if not host.closed:
            host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def adjust(host, vertices, bone, delta):
    command(host, "rig_select_bone", {"bone_index": bone})
    return command(host, "rig_adjust_weight", {
        "selection": {"vertices_by_submesh": {"0": vertices}, "source_indices": []},
        "delta": delta,
    })


def weights(host):
    part = host.shadow_service.capture_export_snapshot(host.shadow_session_id).mesh.submeshes[0]
    return part.bone_indices, part.bone_weights


def history(host):
    view = host.shadow_service.session_view(host.shadow_session_id)
    return view.undo_count, view.redo_count, view.revision


@pytest.mark.parametrize("vertices", [[1], [0, 1]])
def test_fifth_cloth_bone_is_rejected_without_changing_weights_or_history(rig_session, vertices):
    _, _, host = rig_session
    for bone in (0, 1):
        adjust(host, vertices, bone, .1)
    assert len(weights(host)[0][1]) == 4
    # Keep a valid Redo branch while rejecting a mixed rigid/cloth selection.
    adjust(host, vertices, 0, .05)
    valid_redo = weights(host)
    command(host, "undo")
    command(host, "rig_select_bone", {"bone_index": 2})
    before, before_history = weights(host), history(host)
    with pytest.raises(RustMeshValidationError, match="exact PAC contract"):
        command(host, "rig_adjust_weight", {
            "selection": {"vertices_by_submesh": {"0": vertices}, "source_indices": []},
            "delta": .1,
        })
    assert weights(host) == before
    assert history(host) == before_history
    command(host, "redo")
    assert weights(host) == valid_redo


@pytest.mark.parametrize("vertex", [0, 1])
def test_removing_last_bone_preserves_existing_redo(rig_session, vertex):
    _, _, host = rig_session
    adjust(host, [vertex], 3, 1)
    adjust(host, [vertex], 7, .1)
    valid_redo = weights(host)
    command(host, "undo")
    command(host, "rig_select_bone", {"bone_index": 3})
    before, before_history = weights(host), history(host)
    assert before_history[1] == 1
    with pytest.raises(RustMeshValidationError, match="exact PAC contract"):
        command(host, "rig_adjust_weight", {
            "selection": {"vertices_by_submesh": {"0": [vertex]}, "source_indices": []},
            "delta": -1,
        })
    assert weights(host) == before
    assert history(host) == before_history
    command(host, "redo")
    assert weights(host) == valid_redo


@pytest.mark.parametrize("fault", ["offset", "map"])
def test_legacy_draft_stride_recovery_still_requires_exact_source_records(rig_session, tmp_path, fault):
    _, _, host = rig_session
    adjust(host, [1], 0, .1)
    apply_rule(host, tmp_path, PacClothRule(.5))
    expected = shadow_output(host)
    snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
    part = snapshot.mesh.submeshes[0]
    part.source_vertex_stride = 0
    if fault == "offset":
        part.source_vertex_offsets[0] += 40
    else:
        part.source_vertex_map.reverse()
    with pytest.raises(ValueError, match="requires every original|original one-to-one"):
        prepare_replacement_output(snapshot)
    assert shadow_output(host) == expected


@pytest.mark.parametrize("cloth_rule", [False, True])
def test_valid_mixed_skin_edits_finish_without_changing_cloth_bindings(rig_session, tmp_path, cloth_rule):
    source, service, host = rig_session
    for bone in (0, 1, 2, 4):
        adjust(host, [0], bone, .1)
    assert len(weights(host)[0][0]) == 6
    for bone in (0, 1):
        adjust(host, [1], bone, .1)
    adjust(host, [1], 0, .1)  # Increasing an existing bone at capacity is valid.
    assert len(weights(host)[0][1]) == 4
    adjust(host, [1], 2, 1)  # Full weight replaces the four prior influences.
    assert weights(host)[0][1] == (2,)
    adjust(host, [1], 0, .1)
    adjust(host, [1], 0, -1)  # Removing one of two bones is also valid.
    assert weights(host)[0][1] == (2,)
    selection = {"vertices_by_submesh": {"0": [1]}, "source_indices": []}
    command(host, "rig_transfer_weights", {"selection": selection})
    assert weights(host)[0][1] == (3, 7)
    for bone in (0, 1):
        adjust(host, [1], bone, .1)
    command(host, "rig_normalize_weights", {"selection": selection})
    expected = weights(host)
    if cloth_rule:
        apply_rule(host, tmp_path, PacClothRule(.5))
    host.finish(_request(host, "finish_request", 30))
    snapshot = service.capture_export_snapshot(host.authoritative_session_id)
    output, report = service.rebuild_result_from_snapshot(snapshot)
    assert report.validation_status == "passed"
    parsed = parse_pac(output.data, "owned-rust-exact.pac")
    for indices, want in zip(parsed.submeshes[0].bone_indices, expected[0]):
        assert set(indices) == set(want)
    for level in pac_cloth_lods(source):
        for offset in level.submeshes[0].source_vertex_offsets:
            binding = pac_cloth_binding(source, offset)
            if cloth_rule and binding is not None:
                binding = (32, binding[1], binding[2])
            assert pac_cloth_binding(output.data, offset) == binding
    # Parsed lower-level geometry and skeletal weights do not include cloth lanes.
    assert parsed.lod_levels[1:] == parse_pac(source, "owned-rust-exact.pac").lod_levels[1:]
    assert snapshot.original_data == source
