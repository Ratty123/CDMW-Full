from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from cdmw.modding.mesh_exporter import export_obj
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_service_editing import _quad_mesh


def test_load_mesh_bytes_attaches_exact_source_identity() -> None:
    parsed = _quad_mesh()
    parsed.path = ""
    service = MeshService()

    with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed) as parser:
        mesh = service.load_mesh_bytes(b"archive mesh bytes", "character/model/body.pac")

    parser.assert_called_once_with(b"archive mesh bytes", "character/model/body.pac")
    assert getattr(mesh, "_cdmw_original_data") == b"archive mesh bytes"
    assert getattr(mesh, "_cdmw_mesh_asset_source_hash") == hashlib.sha256(b"archive mesh bytes").hexdigest()


def test_edit_session_and_export_preserve_import_sidecar_source_identity(tmp_path: Path) -> None:
    mesh = _quad_mesh()
    source_data = b"source archive bytes"
    source_hash = hashlib.sha256(source_data).hexdigest()
    setattr(mesh, "_cdmw_sidecar_source_asset_hash", source_hash)
    setattr(mesh, "_cdmw_sidecar_source_asset_size", len(source_data))
    service = MeshService()
    view = service.open_edit_session(mesh, session_id="sidecar-source-identity", mode="edit")

    report = service.validate_export(view.session_id, available_textures=("a.dds",))
    snapshot = service.capture_export_snapshot(view.session_id)
    snapshot_report = service.export_snapshot_report(snapshot)
    export_obj(snapshot.mesh, str(tmp_path), "mesh")
    sidecar = json.loads((tmp_path / "mesh.obj.meta.json").read_text(encoding="utf-8"))

    assert report.source_asset_hash == source_hash
    assert snapshot_report["source_asset_hash"] == source_hash
    assert snapshot_report["source_asset_size"] == len(source_data)
    assert sidecar["source_asset_hash"] == source_hash
    assert sidecar["source_asset_size"] == len(source_data)
