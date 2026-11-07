"""Exercise the real OBJ writer and its companion with multilingual paths."""
import json
from pathlib import Path

import pytest

from cdmw.modding import mesh_exporter
from cdmw.modding.mesh_native_outputs import write_native_obj_roundtrip_manifest
from cdmw.modding.mesh_native_availability import native_mesh_core_available
from tests.test_transactional_mesh_outputs import _mesh


@pytest.mark.parametrize("name", [
    "English", "Deutsch_Größe", "Español", "Français", "Italiano_città",
    "日本語", "한국어", "Polski_łódź", "Português", "Русский",
    "Svenska_båt", "Türkçe_ışık", "简体中文", "繁體中文", "船_🚢",
])
def test_obj_and_roundtrip_manifest_export_to_unicode_paths(tmp_path, monkeypatch, name):
    if not native_mesh_core_available():
        pytest.skip("Native mesh core build is required")
    # A fallback would hide a broken native writer.
    monkeypatch.setattr(mesh_exporter, "_allow_python_export_fallback",
                        lambda *_args: pytest.fail("Native OBJ export failed"))
    mesh = _mesh()
    mesh.path = f"object/{name}.pam"
    mesh.format = "pam"
    folder = tmp_path / name
    outputs = mesh_exporter.export_obj(mesh, str(folder), name)
    obj, mtl = folder / f"{name}.obj", folder / f"{name}.mtl"
    companion = Path(str(obj) + ".meta.json")
    assert {obj, mtl, companion}.issubset({Path(path) for path in outputs})
    text = obj.read_text(encoding="utf-8")
    assert f"mtllib {name}.mtl" in text
    assert len([line for line in text.splitlines() if line.startswith("v ")]) == 3
    assert len([line for line in text.splitlines() if line.startswith("f ")]) == 1
    manifest = json.loads(companion.read_text(encoding="utf-8"))
    assert manifest["source_path"] == mesh.path
    assert manifest["export_path"] == obj.name
    # Archive export writes the enriched companion in a second native call.
    assert write_native_obj_roundtrip_manifest(mesh, obj, companion_path=mtl,
                                              extra_payload={"unicode_marker": name})
    manifest = json.loads(companion.read_text(encoding="utf-8"))
    assert manifest["unicode_marker"] == name
    assert manifest["export_path"] == obj.name
    assert not list(folder.glob(".*.tmp"))


def test_obj_and_mtl_written_as_ansi_import_without_a_decode_error(tmp_path):
    # Older exporters write cp1252 names; the importer must not stop on them.
    from cdmw.modding.mesh_obj_importer import import_obj

    (tmp_path / "diffuse.png").write_bytes(b"")
    (tmp_path / "blade.mtl").write_bytes("newmtl Métal\nmap_Kd diffuse.png\n".encode("cp1252"))
    obj = tmp_path / "blade.obj"
    obj.write_bytes("mtllib blade.mtl\no Länge\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl Métal\nf 1 2 3\n".encode("cp1252"))

    mesh = import_obj(str(obj))

    assert len(mesh.submeshes) == 1 and mesh.submeshes[0].faces == [(0, 1, 2)]
    assert mesh.submeshes[0].texture == "diffuse.png"
