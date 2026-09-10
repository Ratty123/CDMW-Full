"""Morph controls must fit the native editor's bounded JSONL channel."""

import json
from unittest.mock import patch

from cdmw.domain.mesh import MeshEditResult
from cdmw.domain.mesh.morph import MeshMorphDefinition, MeshMorphRule, MeshMorphState, MeshMorphVertexWeight
from cdmw.services.mesh_rust_authoring import _json_safe
from cdmw.ui.mesh_editor.process_io import DOTNET_PROTOCOL_LINE_LIMIT
from tests.test_mesh_rust_morph_safety import _open_exact_rust_session


def test_large_morph_definition_keeps_weights_in_host_and_compact_controls_on_wire(tmp_path):
    definition = MeshMorphDefinition(
        definition_id="body", label="Body", category="Body",
        vertices=tuple(MeshMorphVertexWeight(0, index, 1.0) for index in range(20_000)),
        pivot=(0.0, 0.0, 0.0),
        local_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        rule=MeshMorphRule(kind="move", axis="x", amount=0.02),
    )
    morph = MeshMorphState(profile_id="body", definitions=(definition,), driver_submesh_indices=(0,))
    authority, session = _open_exact_rust_session(tmp_path / "session")
    try:
        with patch.object(session.shadow_service, "cached_morph_state_from_runtime", return_value=morph):
            state = session.state_payload(include_document=True)
        message = {"event": "command_result", "ok": True, "payload": {
            "state": state, "result": _json_safe({"profile": {"definitions": [definition]}}),
        }}
        wire = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        assert len(wire) <= DOTNET_PROTOCOL_LINE_LIMIT
        controls = state["morph_refit"]["definitions"][0]
        assert controls["definition_id"] == "body"
        assert controls["rule"]["amount"] == 0.02
        assert "vertices" not in controls
        assert len(definition.vertices) == 20_000
        assert definition.vertices[-1].vertex_index == 19_999
    finally:
        session.cancel()
        authority.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_morph_vertex_updates_use_the_mesh_document_instead_of_duplicate_inline_arrays():
    updates = ({"submesh_index": 0, "vertices": [[index, 0.0, 0.1] for index in range(20_000)]},)
    result = MeshEditResult(
        action="morph_change", status="ok", revision=4,
        changed_vertices_by_submesh=((0, tuple(range(20_000))),),
        native_preview_vertex_update_groups=updates,
        diagnostics=("Owned morph update",),
    )
    payload = _json_safe(result)
    assert len(json.dumps(payload).encode()) < DOTNET_PROTOCOL_LINE_LIMIT
    assert payload["status"] == "ok"
    assert payload["diagnostics"] == ["Owned morph update"]
    assert "native_preview_vertex_update_groups" not in payload
    assert len(result.native_preview_vertex_update_groups[0]["vertices"]) == 20_000
