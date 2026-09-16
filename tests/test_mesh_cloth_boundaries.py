"""Height boundaries follow displayed geometry through editing and recovery."""

from contextlib import ExitStack
import hashlib
import json
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from tests.test_mesh_cloth_influence import apply_rule, shadow_output
from tests.test_mesh_cloth_sequences import all_cloth_fixture
from tests.test_mesh_editor_replacement_sequences import open_editor, source_variants
from tests.test_mesh_rust_authoring_exact_output import (
    _candidate_reference, _open_exact_session, _request,
)
from tests.test_mesh_rust_replacement import command


def _assert_lod_heights_and_gates(data, appearance, heights, gates):
    for level in pac_cloth_lods(data):
        displayed = appearance.to_neutral(level) if appearance else level
        assert [point[1] for point in displayed.submeshes[0].vertices] == pytest.approx(heights, abs=.001)
        actual = [data[offset + 39] & 63 for offset in level.submeshes[0].source_vertex_offsets]
        assert actual == gates


@pytest.mark.parametrize("neutral", [False, True])
@pytest.mark.parametrize("source_index,height,heights,gates,moved_gates", [
    # Stay clear of a half-integer blend: PAC position quantization can move
    # that legitimate rounding result by one of the 64 stored values.
    (0, 4.1, [3, 3, 5], [28, 28, 63], [63, 63, 63]),
    (3, 3.1, [0, 0, 2, 4, 2], [0, 0, 28, 63, 28], [28, 28, 63, 63, 63]),
])
def test_height_boundary_after_move_draft_reset_and_finish(
    tmp_path, monkeypatch, neutral, source_index, height, heights, gates, moved_gates,
):
    source = all_cloth_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **kw: source)
    matrix = (1., 0., 0., 0., 0., 2., 0., 0., 0., 0., 1., 0., 0., 10., 0., 1.)
    appearance = NeutralMeshAppearance("owned", tuple(range(8)), (matrix,) * 8) if neutral else None
    paths = source_variants(tmp_path / "sources")
    _, service, host = _open_exact_session(tmp_path / "host", neutral_appearance=appearance)
    with ExitStack() as stack:
        stack.callback(service.close_edit_session, host.authoritative_session_id, force_without_saving=True)
        stack.callback(lambda: host.cancel() if not host.closed else None)
        apply_rule(host, tmp_path, PacClothRule())
        key = host.state_payload()["cloth"]["parts"][0]["id"]
        command(host, "replacement_choose", {"scope": "entire", "source_path": str(paths[source_index])})
        command(host, "replacement_apply", {"targets": [key], "materials": "original"})
        unmodified = shadow_output(host)
        apply_rule(host, tmp_path, PacClothRule(1, height, 2))
        original_placement = shadow_output(host)
        _assert_lod_heights_and_gates(original_placement, appearance, heights, gates)

        mesh = host.shadow_service.working_mesh(host.shadow_session_id)
        ref = _candidate_reference(host, request_id=41, first_x=mesh.submeshes[0].vertices[0][0])
        path = host.root / ref["path"]
        candidate = json.loads(path.read_bytes())
        for point in candidate["submeshes"][0]["positions"]:
            point[1] += 2
        encoded = json.dumps(candidate, separators=(",", ":")).encode()
        path.write_bytes(encoded)
        ref.update(byte_length=len(encoded), sha256=hashlib.sha256(encoded).hexdigest().upper())
        host.apply_candidate({**_request(host, "transaction_request", 41), "candidate": ref})
        moved = shadow_output(host)
        _assert_lod_heights_and_gates(moved, appearance, [y + 2 for y in heights], moved_gates)
        command(host, "undo")
        assert shadow_output(host) == original_placement
        command(host, "redo")
        assert shadow_output(host) == moved

        draft = tmp_path / "draft" / "mesh_layers.json"
        host.shadow_service._session(host.shadow_session_id).mesh_layer_project_path = draft
        host.shadow_service.retry_mesh_layer_autosave(host.shadow_session_id)
        loaded, sid = open_editor(stack, source, "owned-rust-exact.pac", draft)
        recovered = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=loaded, active_session_id=sid),
            tmp_path / "recovered", process_generation=19)
        stack.callback(lambda: recovered.cancel() if not recovered.closed else None)
        assert shadow_output(recovered) == moved
        command(recovered, "replacement_reset")
        assert shadow_output(recovered) == original_placement
        apply_rule(recovered, tmp_path, PacClothRule(), reset=True)
        assert shadow_output(recovered) == unmodified
        command(recovered, "undo")
        assert shadow_output(recovered) == original_placement
        recovered.finish(_request(recovered, "finish_request", 45))
        snapshot = loaded.capture_export_snapshot(sid)
        assert loaded.rebuild_result_from_snapshot(snapshot)[0].data == original_placement
        assert snapshot.original_data == source
