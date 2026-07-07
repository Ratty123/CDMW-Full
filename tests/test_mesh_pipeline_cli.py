from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from cdmw.domain.mesh.export_validation import validate_mesh_export
from cdmw.modding.mesh_importer import MeshRebuildReport, MeshRebuildResult
from cdmw.modding.mesh_exporter import write_roundtrip_manifest
from cdmw.modding.mesh_glb_interchange import import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj, validate_obj_sidecar_source_identity
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from tools import mesh_pipeline


def _mesh(path: Path) -> ParsedMesh:
    submesh = SubMesh(
        name="Part",
        material="Mat",
        texture="textures/body",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        source_vertex_map=[0, 1, 2],
        source_vertex_offsets=[0, 12, 24],
        source_index_offset=48,
        source_index_count=3,
        source_vertex_stride=12,
        source_descriptor_offset=0,
        vertex_count=3,
        face_count=1,
    )
    setattr(submesh, "unknown_fields", {"descriptor_flags": 7, "bounds": (1.0, 2.0, 3.0)})
    mesh = ParsedMesh(
        path=str(path),
        format="pac",
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )
    setattr(mesh, "_cdmw_original_data", path.read_bytes())
    setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
    setattr(mesh, "_cdmw_mesh_asset_source_hash", hashlib.sha256(path.read_bytes()).hexdigest())
    setattr(
        mesh,
        "_cdmw_mesh_asset_lods",
        (
            SimpleNamespace(
                lod_index=0,
                name="lod0_exact",
                original_section_offset=128,
                original_section_size=256,
                bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
                metadata={"section": "geometry_lod0"},
                submeshes=(
                    SimpleNamespace(
                        submesh_index=0,
                        stable_id="body_lod0_part0",
                        material_slot_index=3,
                        original_descriptor_offset=0,
                        original_vertex_offset=0,
                        original_index_offset=48,
                        original_vertex_stride=12,
                        source_index_map=(0, 1, 2),
                        bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
                    ),
                ),
            ),
        ),
    )
    setattr(mesh, "_cdmw_no_op_roundtrip_report", {"result": "PASS", "byte_identical": True, "unexpected_differences": 0})
    return mesh


class _FakeMeshService:
    def __init__(self) -> None:
        self.base: ParsedMesh | None = None
        self.working: ParsedMesh | None = None

    def load_mesh_file(self, path: Path | str, *, run_roundtrip: bool = False) -> ParsedMesh:
        return copy.deepcopy(_mesh(Path(path)))

    def open_edit_session(self, mesh: ParsedMesh, *, session_id: str | None = None, mode: str = "edit") -> object:
        self.base = copy.deepcopy(mesh)
        self.working = copy.deepcopy(mesh)
        return SimpleNamespace(session_id=session_id or "test-session")

    def replace_working_mesh(self, session_id: str, mesh: ParsedMesh) -> object:
        self.working = copy.deepcopy(mesh)
        return SimpleNamespace(session_id=session_id)

    def validate_export(self, session_id: str):
        assert self.base is not None
        assert self.working is not None
        return validate_mesh_export(
            self.working,
            original_mesh=self.base,
            parse_confidence="exact",
            source_asset_hash=getattr(self.base, "_cdmw_mesh_asset_source_hash"),
            no_op_roundtrip_status="PASS",
            no_op_byte_identical=True,
            no_op_unexpected_differences=0,
            edit_operations=getattr(self.working, "_cdmw_edit_operations", ()),
            requires_edit_operations=bool(getattr(self.working, "_cdmw_imported_from_obj", False)),
        )

    def working_mesh(self, session_id: str) -> ParsedMesh:
        assert self.working is not None
        return self.working


def test_mesh_pipeline_export_validate_and_import_commands(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    package_dir = tmp_path / "package"
    manifest_path = tmp_path / "export_manifest.json"
    validation_path = tmp_path / "validation.json"
    import_dir = tmp_path / "imported"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)

    assert mesh_pipeline.main(["export", str(source), "--out", str(package_dir), "--manifest", str(manifest_path)]) == 0
    assert (package_dir / "mesh.glb").is_file()
    assert (package_dir / "mesh.obj").is_file()
    assert (package_dir / "mesh.cdmeta.json").is_file()
    assert (package_dir / "original_asset_hash.txt").read_text(encoding="utf-8") == hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "cdmw_mesh_pipeline_export_v1"
    assert manifest["mesh"].endswith("mesh.glb")
    imported_glb = import_glb_with_sidecar(package_dir / "mesh.glb")
    assert getattr(imported_glb, "_cdmw_imported_from_obj")
    assert imported_glb.format == "pac"
    assert imported_glb.submeshes[0].source_vertex_stride == 12
    assert imported_glb.submeshes[0].source_vertex_offsets == [0, 12, 24]
    assert imported_glb.submeshes[0].unknown_fields == {"descriptor_flags": 7, "bounds": [1.0, 2.0, 3.0]}
    assert imported_glb._cdmw_edit_operations[0]["source"] == "mesh.glb"
    imported_mesh = import_obj(str(package_dir / "mesh.obj"))
    imported_submesh = imported_mesh.submeshes[0]
    assert imported_submesh.source_vertex_stride == 12
    assert imported_submesh.source_vertex_offsets == [0, 12, 24]
    assert imported_submesh.source_index_offset == 48
    assert imported_submesh.source_index_count == 3
    assert imported_submesh.source_descriptor_offset == 0
    assert getattr(imported_submesh, "unknown_fields") == {"descriptor_flags": 7, "bounds": [1.0, 2.0, 3.0]}
    imported_lods = getattr(imported_mesh, "_cdmw_mesh_asset_lods")
    assert imported_lods[0]["name"] == "lod0_exact"
    assert imported_lods[0]["original_section_offset"] == 128
    assert imported_lods[0]["submeshes"][0]["stable_id"] == "body_lod0_part0"

    assert mesh_pipeline.main(["validate", str(source), str(package_dir), "--report", str(validation_path)]) == 0
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["ok"] is True
    assert validation["no_op_roundtrip_status"] == "PASS"

    assert mesh_pipeline.main(["import", str(source), str(package_dir), "--out", str(import_dir)]) == 0
    assert json.loads((import_dir / "import_report.json").read_text(encoding="utf-8"))["ok"] is True
    assert (import_dir / "edit_operations.json").is_file()


def test_glb_editable_package_import_requires_sidecar(tmp_path: Path, monkeypatch) -> None:
    import pytest

    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    package_dir = tmp_path / "package"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)
    assert mesh_pipeline.main(["export", str(source), "--out", str(package_dir)]) == 0
    (package_dir / "mesh.glb.meta.json").unlink()
    (package_dir / "mesh.cdmeta.json").unlink()

    with pytest.raises(ValueError, match="GLB sidecar is required"):
        import_glb_with_sidecar(package_dir / "mesh.glb")


def test_mesh_pipeline_import_uses_package_cdmeta_for_glb(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    package_dir = tmp_path / "package"
    import_dir = tmp_path / "imported"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)
    assert mesh_pipeline.main(["export", str(source), "--out", str(package_dir)]) == 0
    (package_dir / "mesh.glb.meta.json").unlink()

    assert mesh_pipeline.main(["import", str(source), str(package_dir), "--out", str(import_dir)]) == 0
    assert (package_dir / "mesh.glb.meta.json").is_file()


def test_mesh_pipeline_export_sidecar_records_raw_vertex_record_hash(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pac"
    source_data = bytes(range(64))
    source.write_bytes(source_data)
    package_dir = tmp_path / "package"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)

    assert mesh_pipeline.main(["export", str(source), "--out", str(package_dir)]) == 0

    payload = json.loads((package_dir / "mesh.cdmeta.json").read_text(encoding="utf-8"))
    submesh = payload["lods"][0]["submeshes"][0]
    raw_records = source_data[0:12] + source_data[12:24] + source_data[24:36]
    assert submesh["raw_vertex_record_count"] == 3
    assert submesh["raw_vertex_record_stride"] == 12
    assert submesh["raw_vertex_records_sha256"] == hashlib.sha256(raw_records).hexdigest()


def test_obj_sidecar_prefers_attached_material_slots_and_unknown_sections(tmp_path: Path) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    mesh = _mesh(source)
    setattr(
        mesh,
        "_cdmw_mesh_asset_material_slots",
        (
            SimpleNamespace(index=4, name="Skin", texture="skin.dds"),
            SimpleNamespace(index=8, name="Detail", texture="detail.dds"),
        ),
    )
    setattr(
        mesh,
        "_cdmw_mesh_asset_unknown_sections",
        (SimpleNamespace(name="tail", offset=48, size=16, index=3),),
    )

    sidecar_path = write_roundtrip_manifest(mesh, tmp_path / "mesh.obj")
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))

    assert payload["material_slots"] == [
        {"index": 4, "name": "Skin", "texture": "skin.dds"},
        {"index": 8, "name": "Detail", "texture": "detail.dds"},
    ]
    assert payload["unknown_sections"] == [{"name": "tail", "offset": 48, "size": 16, "index": 3}]
    assert payload["lods"][0]["name"] == "lod0_exact"
    assert payload["lods"][0]["original_section_offset"] == 128
    assert payload["lods"][0]["original_section_size"] == 256
    assert payload["lods"][0]["metadata"] == {"section": "geometry_lod0"}
    assert payload["lods"][0]["submeshes"][0]["stable_id"] == "body_lod0_part0"
    assert payload["lods"][0]["submeshes"][0]["material_slot_index"] == 3
    assert payload["lods"][0]["submeshes"][0]["unknown_fields"] == {
        "descriptor_flags": 7,
        "bounds": [1.0, 2.0, 3.0],
    }


def test_export_validation_blocks_lod_identity_change(tmp_path: Path) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    original = _mesh(source)
    edited = copy.deepcopy(original)
    edited_lods = list(getattr(edited, "_cdmw_mesh_asset_lods"))
    edited_lods[0] = SimpleNamespace(
        **{
            **vars(edited_lods[0]),
            "original_section_size": 512,
        }
    )
    setattr(edited, "_cdmw_mesh_asset_lods", tuple(edited_lods))

    report = validate_mesh_export(
        edited,
        original_mesh=original,
        parse_confidence="exact",
        source_asset_hash=getattr(original, "_cdmw_mesh_asset_source_hash"),
        no_op_roundtrip_status="PASS",
        no_op_byte_identical=True,
        no_op_unexpected_differences=0,
    )

    assert any(issue.code == "lod_identity_changed" for issue in report.blockers)


def test_obj_sidecar_raw_vertex_record_hash_mismatch_blocks_identity_validation(tmp_path: Path, monkeypatch) -> None:
    import pytest

    source = tmp_path / "source.pac"
    source.write_bytes(bytes(range(64)))
    package_dir = tmp_path / "package"
    sidecar_path = package_dir / "mesh.obj.meta.json"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)
    assert mesh_pipeline.main(["export", str(source), "--out", str(package_dir)]) == 0
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    payload["lods"][0]["submeshes"][0]["raw_vertex_records_sha256"] = "0" * 64
    sidecar_path.write_text(json.dumps(payload), encoding="utf-8")

    imported_mesh = import_obj(str(package_dir / "mesh.obj"))
    with pytest.raises(ValueError, match="raw vertex records changed"):
        validate_obj_sidecar_source_identity(imported_mesh, source.read_bytes())


def test_mesh_pipeline_validate_blocks_source_hash_mismatch(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    package_dir = tmp_path / "package"
    report_path = tmp_path / "validation.json"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)
    assert mesh_pipeline.main(["export", str(source), "--out", str(package_dir)]) == 0

    source.write_bytes(b"changed pac byte")

    assert mesh_pipeline.main(["validate", str(source), str(package_dir), "--report", str(report_path)]) == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["issues"][0]["severity"] == "fatal"
    assert "source hash mismatch" in report["issues"][0]["message"]


def test_mesh_pipeline_validation_payload_uses_public_error_severity(tmp_path: Path) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    mesh = _mesh(source)
    mesh.submeshes[0].normals = []
    report = validate_mesh_export(mesh)

    payload = mesh_pipeline._validation_report_payload(report)

    issue = next(issue for issue in payload["issues"] if issue["code"] == "missing_normals")
    assert issue["severity"] == "error"
    assert issue["can_continue"] is False
    assert issue["expected"] == 3
    assert issue["actual"] == 0
    assert issue["lod_index"] == 0
    assert issue["submesh_index"] == 0


def test_mesh_pipeline_import_writes_blocked_report_for_missing_edit_package(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    import_dir = tmp_path / "imported"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)

    assert mesh_pipeline.main(["import", str(source), str(tmp_path / "missing.obj"), "--out", str(import_dir)]) == 1
    report = json.loads((import_dir / "import_report.json").read_text(encoding="utf-8"))
    validation = json.loads((import_dir / "validation_report.json").read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert validation["issues"][0]["severity"] == "fatal"
    assert validation["issues"][0]["code"] == "import_failed"
    assert validation["issues"][0]["expected"] == "valid edited mesh package"
    assert validation["issues"][0]["actual"]
    assert validation["issues"][0]["lod_index"] == -1


def test_mesh_pipeline_rebuild_writes_output_and_report(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.pac"
    source.write_bytes(b"source pac bytes")
    package_dir = tmp_path / "package"
    output_path = tmp_path / "rebuilt.pac"
    report_path = tmp_path / "rebuild_report.json"
    monkeypatch.setattr(mesh_pipeline, "MeshService", _FakeMeshService)
    assert mesh_pipeline.main(["export", str(source), "--out", str(package_dir)]) == 0

    def fake_rebuild_mesh_with_report(mesh: ParsedMesh, original_data: bytes, *, validation_status: str, output_path: str) -> MeshRebuildResult:
        return MeshRebuildResult(
            data=b"rebuilt pac bytes",
            report=MeshRebuildReport(
                mesh_format="pac",
                source_asset_hash=hashlib.sha256(original_data).hexdigest(),
                rebuilt_asset_hash=hashlib.sha256(b"rebuilt pac bytes").hexdigest(),
                source_size=len(original_data),
                rebuilt_size=len(b"rebuilt pac bytes"),
                parse_confidence="exact",
                validation_status=validation_status,
                byte_identical=False,
                changed_byte_ranges=((0, 3),),
                output_path=output_path,
            ),
        )

    monkeypatch.setattr(mesh_pipeline, "rebuild_mesh_with_report", fake_rebuild_mesh_with_report)

    assert mesh_pipeline.main(["rebuild", str(source), str(package_dir), "--out", str(output_path), "--report", str(report_path)]) == 0
    assert output_path.read_bytes() == b"rebuilt pac bytes"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["validation_status"] == "passed"
    assert report["output_path"] == str(output_path)
