import pytest
from PIL import Image

from cdmw.models import PreviewMaterialTextureInput
from cdmw.modding.material_replacer import group_replacement_texture_sets
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def test_missing_texture_file_collection_is_treated_as_empty() -> None:
    assert group_replacement_texture_sets(None) == {}


@pytest.mark.parametrize("kind", ["preview-inputs", "texture-slots"])
@pytest.mark.parametrize("reverse_files", [False, True])
def test_explicit_same_named_texture_bindings_ignore_file_order(tmp_path, kind, reverse_files):
    paths, parts = [], []
    for name, color in (("red", (210, 30, 60)), ("blue", (20, 50, 210))):
        folder = tmp_path / name
        folder.mkdir()
        path = folder / "shared.png"
        Image.new("RGB", (4, 4), color).save(path)
        part = SubMesh(name=name, material=name, texture="shared.png")
        if kind == "preview-inputs":
            part.preview_material_texture_inputs = (PreviewMaterialTextureInput(
                slot_kind="base", source_texture_path=str(path), confidence="obj_mtl", semantic_subtype="albedo"),)
        else:
            part.texture_slots = (("base", str(path)),)
        paths.append(path)
        parts.append(part)
    mesh = ParsedMesh(path="model.obj", format="obj", submeshes=parts)
    grouped = group_replacement_texture_sets(list(reversed(paths)) if reverse_files else paths, obj_mesh=mesh)
    for part, path in zip(parts, paths, strict=True):
        slot = grouped[part.material].slots["base"]
        assert slot.source_path.resolve() == path.resolve()
        assert slot.source_authority == "metadata"
