"""Imported New Item meshes can reach Free Edit destination selection."""

import json
import threading
from types import SimpleNamespace

import pytest

from cdmw.modding.scene_importer import import_scene_mesh
from cdmw.services.mesh_rust_authoring import (
    RustMeshAuthoringSession,
    RustMeshValidationError,
    read_owned_payload_reference,
)
from cdmw.workers.new_item_mesh_session import prepare_new_item_mesh_session
from tests.test_mesh_rust_authoring import _candidate_reference, _request
from tests.test_scene_importer_gltf import _triangle_payload, _write_glb


@pytest.mark.parametrize("source_format", ("obj", "glb"))
def test_imported_free_edit_can_open_choose_destination_edit_and_finish(tmp_path, source_format):
    source = tmp_path / f"imported.{source_format}"
    if source_format == "glb":
        data, document = _triangle_payload()
        _write_glb(source, document, data)
    else:
        source.write_text(
            "o imported\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            "vt 0 0\nvt 1 0\nvt 0 1\nvn 0 0 1\n"
            "usemtl Imported\nf 1/1/1 2/2/1 3/3/1\n"
        )
    source_bytes = source.read_bytes()
    prepared = prepare_new_item_mesh_session(
        import_scene_mesh(source), "new-item-imported", threading.Event(),
    )
    host = None
    destination = tmp_path / "free-edit-output"
    try:
        assert prepared.view.output_policy == "free_edit_rebuild"
        assert not prepared.view.output_destination_ready
        host = RustMeshAuthoringSession.create(
            SimpleNamespace(mesh_service=prepared.service, active_session_id=prepared.view.session_id),
            tmp_path / "host", process_generation=1,
        )
        initial = host.state_payload()
        assert initial["output_policy"] == "free_edit_rebuild"
        assert initial["output_destination"] == ""
        assert not initial["output_destination_ready"]
        assert not initial["authoring_enabled"]
        assert "output folder" in initial["output_policy_reason"]
        manifest = json.loads(host.manifest_path.read_text(encoding="utf-8"))
        document = read_owned_payload_reference(host.root, manifest["document"])
        assert document["format"] == "preview"
        assert host.shadow_service.working_mesh(host.shadow_session_id).format == source_format

        for request_id, action in enumerate(("topology", "export_free_edit"), start=1):
            request = _request(host, "command_request", request_id)
            request.update(command=action, arguments={"action": "extrude"} if action == "topology" else {})
            with pytest.raises(RustMeshValidationError, match="output folder"):
                host.run_command(request)
        with pytest.raises(RustMeshValidationError, match="output folder"):
            host.finish(_request(host, "finish_request", 3))
        assert not destination.exists()

        configure = _request(host, "command_request", 4)
        configure.update(command="configure_output_policy", arguments={
            "policy": "free_edit_rebuild", "destination": str(destination),
        })
        configured = host.run_command(configure)["state"]
        assert configured["output_destination_ready"]
        assert configured["authoring_enabled"]
        assert not destination.exists()
        exact = _request(host, "command_request", 5)
        exact.update(command="configure_output_policy", arguments={"policy": "exact_game_asset"})
        with pytest.raises(ValueError):
            host.run_command(exact)

        edit = _request(host, "transaction_request", 6)
        edit["candidate"] = _candidate_reference(host, request_id=6, first_x=0.25)
        edit["label"] = "Move imported vertex"
        host.apply_candidate(edit)
        finished = host.finish(_request(host, "finish_request", 7))
        assert finished["status"] == "accepted"
        result = prepared.service.working_mesh(prepared.view.session_id, clone=True)
        assert result.submeshes[0].vertices[0] == (0.25, 0.0, 0.0)
        assert result.format == source_format
        assert not destination.exists()
        assert source.read_bytes() == source_bytes
    finally:
        if host is not None:
            host.cancel()
        prepared.cleanup()
