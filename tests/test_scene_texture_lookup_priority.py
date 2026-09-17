from pathlib import Path

import pytest

from cdmw.modding import scene_texture_discovery as textures


@pytest.mark.parametrize("package_match", [True, False])
def test_relocated_texture_keeps_first_nearby_match(tmp_path: Path, monkeypatch, package_match: bool):
    root = tmp_path / "files"
    nearby = root / "model" / "nested" / "albedo.png"
    nearby.parent.mkdir(parents=True)
    nearby.write_bytes(b"this model")
    other = root / "albedo.png"
    if package_match:
        other.write_bytes(b"other model")
    source = nearby.parent.parent / "model.obj"
    source.write_text("mtllib model.mtl\n", encoding="utf-8")
    source.with_suffix(".mtl").write_text("newmtl A\nmap_Kd relocated/albedo.png\n", encoding="utf-8")
    if not package_match:
        # A broader directory may hit its scan limit despite a local match.
        original = textures._find_first_local_file_by_basename
        monkeypatch.setattr(textures, "_find_first_local_file_by_basename",
                            lambda path, name: None if path == root else original(path, name))
    assert textures._resolve_local_texture_reference(source, "relocated/albedo.png") == nearby.resolve()
    assert textures._obj_material_texture_references(source) == (nearby.resolve().as_posix(),)
