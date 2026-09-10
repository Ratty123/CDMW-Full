from pathlib import Path
from types import SimpleNamespace
import threading

from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveMaterialContextResult
from cdmw.workers import mesh_archive_refit_worker as refit_worker
from tests.test_mesh_pac_topology_serializer import _pac_fixture
from tests.test_mesh_rust_authoring import _prepared_dds_entry


def test_refit_preparation_recovers_exact_dds_from_captured_archive_dependencies(tmp_path, monkeypatch):
    payload = b"DDS " + bytes(range(128))
    texture = _prepared_dds_entry(tmp_path, "character/texture/target.dds", payload)
    source = _pac_fixture(skinned=True)
    entry = ArchiveEntry("character/model/body.pac", texture.pamt_path, texture.paz_file,
                         0, len(source), len(source), 0, 0)
    service = MeshService()
    mesh = service.load_mesh_bytes(source, entry.path)
    view = service.open_edit_session(mesh, mode="edit")
    loaded = SimpleNamespace(service=service, view=view)
    model = ModelPreviewData(path=entry.path, meshes=[ModelPreviewMesh(
        source_submesh_index=0, texture_name=texture.path,
        preview_texture_dds_path=str(tmp_path / "missing" / "target.dds"),
    )])
    context = MeshArchiveMaterialContextResult(preview_model=model)
    results = iter((loaded, context))
    monkeypatch.setattr(refit_worker, "_run", lambda *_args: next(results))
    entries = (entry, texture)
    dependencies = ArchiveWorkflowDependencyContext(
        entry, entries, {item.path: (item,) for item in entries},
        {item.basename: (item,) for item in entries}, True,
    )
    result = refit_worker.prepare_archive_refit_source(
        {"_archive_entry": entry, "_archive_dependencies": dependencies}, threading.Event(),
    )
    assert not result["_archive_material_reason"]
    resolved = result["_archive_snapshot"].mesh.submeshes[0].preview_texture_dds_path
    assert Path(resolved).read_bytes() == payload
    assert texture.prepared_path.read_bytes() == payload
    assert not service._sessions
