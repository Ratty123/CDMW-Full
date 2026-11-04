"""Regression checks for the current editor's external mesh export."""
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.models import RunCancelled
from cdmw.services.mesh_interchange_export import export_editable_mesh
from cdmw.services.mesh_export_readback import readback_editable_package_metadata
from cdmw.services.mesh_service import MeshService
from cdmw.workers.mesh_editor_workers import MeshEditablePackageExportWorker
from tests.test_mesh_interchange_authoring import authored_mesh, glb_document


@pytest.fixture
def source(tmp_path):
    service = MeshService()
    view = service.open_edit_session(authored_mesh(tmp_path / "source"), session_id="export-regression", mode="edit")
    try:
        yield service, view.session_id
    finally:
        service.close_edit_session(view.session_id)


def test_skinned_legacy_package_exports_all_formats_and_verified_weights(source, tmp_path):
    service, session_id = source
    errors, completed = [], []
    worker = MeshEditablePackageExportWorker(1, service, session_id, tmp_path / "package")
    worker.error.connect(lambda _request, message: errors.append(message))
    worker.completed.connect(lambda _request, result, _elapsed: completed.append(result))
    worker.run()
    assert errors == []
    assert len(completed) == 1
    package = tmp_path / "package"
    assert all((package / f"mesh.{suffix}").is_file() for suffix in ("glb", "fbx", "obj"))
    assert glb_document(package / "mesh.glb")["skins"]
    assert b"Cluster" in (package / "mesh.fbx").read_bytes()
    assert completed[0]["export_snapshot"]["output_reparse"]["status"] == "passed"


@pytest.mark.parametrize("format_name", ["glb", "fbx", "obj"])
def test_one_format_export_does_not_invoke_other_writers(source, tmp_path, format_name):
    service, session_id = source
    from contextlib import ExitStack
    with ExitStack() as stack:
        for other in {"glb", "fbx", "obj"} - {format_name}:
            stack.enter_context(patch(f"cdmw.services.mesh_interchange_export.export_{other}", side_effect=AssertionError("wrong writer")))
        result = export_editable_mesh(service, session_id, tmp_path / "out", name="outfit", formats=(format_name,))
    assert result["mesh_path"].name == f"outfit.{format_name}"
    assert result["metadata_path"].is_file()
    assert not any((tmp_path / "out" / f"outfit.{other}").exists() for other in {"glb", "fbx", "obj"} - {format_name})


@pytest.mark.parametrize("format_name", ["glb", "fbx", "obj"])
def test_metadata_checker_still_rejects_unproven_edit_permissions(source, tmp_path, format_name):
    service, session_id = source
    result = export_editable_mesh(service, session_id, tmp_path / "out", formats=(format_name,))
    path = result["metadata_path"]
    data = json.loads(path.read_text(encoding="utf-8"))
    data["allowed_edit_operations"].append("arbitrary_topology_changes")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="allowed_edit_operations"):
        readback_editable_package_metadata(path.parent, "mesh", service.capture_export_snapshot(session_id).mesh, formats=(format_name,))


def test_failed_or_cancelled_export_preserves_existing_files(source, tmp_path):
    service, session_id = source
    output = tmp_path / "out"
    output.mkdir()
    existing = output / "mesh.glb"
    existing.write_bytes(b"previous export")
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        export_editable_mesh(service, session_id, output, formats=("glb",), stop_event=stop)
    with patch("cdmw.services.mesh_interchange_export._package_reparse_report", side_effect=RuntimeError("readback failed")):
        with pytest.raises(RuntimeError, match="readback failed"):
            export_editable_mesh(service, session_id, output, formats=("glb",))
    assert list(output.iterdir()) == [existing]
    assert existing.read_bytes() == b"previous export"
    assert not list(tmp_path.glob(".out.export-*"))


@pytest.mark.parametrize("format_name", ["glb", "fbx", "obj"])
def test_rust_export_worker_uses_edited_shadow_without_committing(source, tmp_path, format_name):
    from types import SimpleNamespace
    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker
    from tests.test_mesh_rust_authoring import _request
    service, session_id = source
    session = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=session_id),
        tmp_path / "rust-session", process_generation=1,
    )
    try:
        shadow = session.shadow_service
        shadow.configure_output_policy(session.shadow_session_id, "free_edit_rebuild", output_destination=str(tmp_path / "free-edit"))
        shadow.apply_command(session.shadow_session_id, MeshEditCommand(
            action="transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), params={"translate": (0.25, 0.0, 0.0)},
        ))
        before = shadow.session_view(session.shadow_session_id)
        request = _request(session, "command_request", 1)
        request.update(command="export_mesh", arguments={"format": format_name, "path": str(tmp_path / "out" / f"edited.{format_name}")})
        worker = MeshRustProtocolWorker(1, session, request)
        completed, errors = [], []
        worker.completed.connect(lambda *args: completed.append(args))
        worker.error.connect(lambda *args: errors.append(args))
        worker.run()
        assert errors == []
        assert len(completed) == 1
        assert shadow.session_view(session.shadow_session_id).revision == before.revision
        assert service.session_view(session_id).revision == 0
        assert service.working_mesh(session_id).submeshes[0].vertices[0][0] == 0
        path = tmp_path / "out" / f"edited.{format_name}"
        from cdmw.modding.mesh_glb_interchange import import_glb_with_sidecar
        if format_name == "glb":
            assert import_glb_with_sidecar(path).submeshes[0].vertices[0][0] == pytest.approx(0.25)
        from cdmw.services.mesh_rust_authoring import _editable_package_mesh_path
        assert _editable_package_mesh_path(path.parent) == path
    finally:
        session.cancel()


def test_export_rejects_unsupported_format_before_writing(source, tmp_path):
    service, session_id = source
    with pytest.raises(ValueError, match="GLB, FBX and OBJ"):
        export_editable_mesh(service, session_id, tmp_path / "out", formats=("gltf",))
    assert not (tmp_path / "out").exists()
