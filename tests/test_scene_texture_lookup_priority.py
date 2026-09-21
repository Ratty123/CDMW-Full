from pathlib import Path

import pytest

from cdmw.modding import scene_texture_discovery as textures
from cdmw.modding.scene_importer import import_scene_mesh_with_report
from tests.scene_gltf_test_support import write_valid_image


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


@pytest.mark.parametrize("normal_suffix", ["Normal_DirectX", "NormalMap_DirectX"])
def test_obj_sibling_directx_normal_keeps_its_material_group(tmp_path, normal_suffix):
    source = tmp_path / "blade.obj"
    source.write_text(
        "mtllib blade.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 0 1\nusemtl Blade\nf 1/1 2/2 3/3\n",
        encoding="utf-8",
    )
    source.with_suffix(".mtl").write_text(
        "newmtl Blade\nmap_Kd Blade_Base_Color.png\n", encoding="utf-8",
    )
    write_valid_image(tmp_path / "Blade_Base_Color.png")
    normal = tmp_path / f"Blade_{normal_suffix}.png"
    write_valid_image(normal)
    result = import_scene_mesh_with_report(source, include_external_audit=False)
    assert Path(result.mesh.submeshes[0].preview_normal_texture_path) == normal
