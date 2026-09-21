import hashlib
import json
import threading

import pytest
from PySide6.QtGui import QColor, QImage

from cdmw.services.mesh_dotnet_reference_composite import decode_dotnet_native_preview_package
from cdmw.services.mesh_rust_preview_package import build_rust_preview_package_from_preview_core
from cdmw.ui.new_item.item_preview import PlacementScene, build_item_preview_package
from tests.test_rust_preview_material_oracle_parity import _layer, _write_dds, _write_preview_core_package


@pytest.mark.parametrize("surface", ["appearance", "appearance_edits", "placement", "effects", "effects_edits"])
def test_combined_template_retains_browse_archives_material_graph(tmp_path, monkeypatch, surface):
    native = tmp_path / "native"
    native.mkdir()
    for name, color in (("base", "gray"), ("detail", "blue"), ("mask", "red")):
        image = QImage(8, 8, QImage.Format.Format_RGBA8888)
        image.fill(QColor(color))
        _write_dds(native / f"{name}.dds", image, srgb=name != "mask")
    layers = [
        _layer(role="base", source_parameter="_diffuseTexture", diffuse_source="base.dds"),
        _layer(role="detail", channel="r", source_parameter="_detailDiffuseMaskR",
               diffuse_source="detail.dds", mask_source="mask.dds", tint=(0.2, 0.3, 0.4, 1.0)),
    ]
    _write_preview_core_package(native, layers=layers)
    archive = build_rust_preview_package_from_preview_core(native, output_root=tmp_path / "archive")
    template = decode_dotnet_native_preview_package(native)
    from cdmw.services.effect_placement_preview import mesh_names_textures
    from cdmw.services import mesh_rust_authoring

    assert mesh_names_textures(template)
    monkeypatch.setattr(mesh_rust_authoring, "compile_mesh_dotnet_material_manifest",
                        lambda *_args, **_kwargs: pytest.fail("canonical template textures must not be synthesized again"))
    if surface.endswith("_edits"):
        from cdmw.domain.new_item.spec import GlowChoice
        from cdmw.domain.new_item.translucency import TranslucencyChoice
        from cdmw.services.new_item_materials import glow_preview_mesh
        from cdmw.services.new_item_translucency import translucency_preview_mesh

        parts = (template.submeshes[0].material,)
        template = glow_preview_mesh(template, GlowChoice(parts, (0.0, 0.0, 1.0), 6.0))
        template = translucency_preview_mesh(template, TranslucencyChoice(parts, 0.1, 0.3,
            surface_settings=((parts[0], 0.9, 0.0),)))
    if surface.startswith("effects"):
        from cdmw.services.effect_placement_preview import build_effect_placement_package
        combined = build_effect_placement_package(template, (-1, -1, -1), (1, 1, 1),
            output_root=tmp_path / "effects", include_body=False, include_item_textures=True).package_dir
    else:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        imported = ParsedMesh(path="import.obj", format="obj", submeshes=[SubMesh(
            name="import", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], faces=[(0, 1, 2)],
        )])
        scene = PlacementScene(template=template if surface == "placement" else None,
                               model=imported if surface == "placement" else template)
        combined = build_item_preview_package(scene, token=surface, output_root=tmp_path / surface,
                                             stop_event=threading.Event(), include_material_resources=True)

    def graph_materials(package):
        manifest = json.loads((package / "manifest.json").read_text())
        graph = manifest["preview_core_material_graph"]
        assert graph["resources_included"] and graph["quality"] == "full"
        materials = graph["materials"]
        for material in materials:
            for layer in material["layers"]:
                for role in ("diffuse", "normal", "material", "height", "mask"):
                    resource = layer.get(role)
                    if resource:
                        data = (package / resource["path"]).read_bytes()
                        assert hashlib.sha256(data).hexdigest().upper() == resource["sha256"]
                        resource.pop("path")
            # Synthetic placement parts change draw indices, never source ownership.
            material.pop("material_index")
            material.pop("material_slot_index")
        return materials

    assert graph_materials(combined) == graph_materials(archive.package_dir)
    archive_manifest = json.loads(archive.manifest_path.read_text())
    combined_manifest = json.loads((combined / "manifest.json").read_text())
    index = combined_manifest["preview_core_material_graph"]["materials"][0]["material_index"]
    presentation = next(row for row in combined_manifest["material_presentations"] if row["material_index"] == index)
    expected = archive_manifest["material_presentations"][0]
    if surface.endswith("_edits"):
        assert presentation["emissive_intensity"] == 6.0
        assert presentation["emissive_color"] == [0.0, 0.0, 1.0]
        assert presentation["translucency"] == [0.1, 0.3]
        assert presentation["translucency_surface"] == [0.9, 0.0]
        for field in ("emissive_intensity", "emissive_color", "translucency", "translucency_surface"):
            expected[field] = presentation[field]
    for row in (presentation, expected):
        row.pop("material_index")
        row.pop("material_slot_index")
    assert presentation == expected
