"""Game-target replacement stays distinct from an OBJ rebuild session."""

from types import SimpleNamespace

import pytest

from cdmw.services.mesh_rust_replacement import replacement_ui_state
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_mesh_rust_replacement import command


FREE_EDIT_REASON = (
    "Free Edit exports OBJ geometry without rig weights. "
    "Import Replacement requires an original game mesh with Exact output."
)


def test_free_edit_game_mesh_explains_replacement_and_can_return_to_exact(tmp_path):
    _, service, host = _open_exact_session(tmp_path / "session")
    try:
        host.shadow_service.configure_output_policy(
            host.shadow_session_id,
            "free_edit_rebuild",
            output_destination=tmp_path / "free-edit-output",
        )
        before = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        state = replacement_ui_state(host)
        assert not state["available"]
        assert state["reason"] == FREE_EDIT_REASON
        with pytest.raises(ValueError, match="Free Edit exports OBJ geometry without rig weights"):
            command(host, "replacement_choose", {"scope": "entire"})
        after = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        assert after.mesh_revision == before.mesh_revision
        assert after.original_data == before.original_data
        assert after.mesh.submeshes[0].vertices == before.mesh.submeshes[0].vertices
        assert host.shadow_service.session_view(host.shadow_session_id).output_policy == "free_edit_rebuild"
        assert host.pending_replacement is None

        host.shadow_service.configure_output_policy(host.shadow_session_id, "exact_game_asset")
        assert replacement_ui_state(host)["available"]
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id)


def test_imported_obj_reports_free_edit_workflow_without_suggesting_exact_support(tmp_path):
    from cdmw.modding.scene_importer import import_scene_mesh

    source = tmp_path / "imported.obj"
    source.write_text("o imported\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    service = MeshService()
    view = service.open_edit_session(import_scene_mesh(source))
    service.configure_output_policy(
        view.session_id,
        "free_edit_rebuild",
        output_destination=tmp_path / "free-edit-output",
    )
    host = SimpleNamespace(
        shadow_service=service,
        shadow_session_id=view.session_id,
        neutral_appearance=None,
        pending_replacement=None,
        replacement_comparison="edit",
    )
    try:
        state = replacement_ui_state(host)
        assert not state["available"]
        assert state["reason"] == FREE_EDIT_REASON
        assert host.shadow_service.session_view(host.shadow_session_id).output_policy == "free_edit_rebuild"
        with pytest.raises(ValueError):
            host.shadow_service.configure_output_policy(host.shadow_session_id, "exact_game_asset")
        assert not replacement_ui_state(host)["available"]
    finally:
        service.close_edit_session(view.session_id)
