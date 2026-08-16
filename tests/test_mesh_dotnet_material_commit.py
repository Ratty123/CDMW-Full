"""The resident material snapshot takes both submesh row types it is handed.

The Material Authority resolver hands ``apply_resident_material_resources`` the
Builder's replacement preview model, whose rows are the slotted
``ModelPreviewMesh``. The parser's ``SubMesh`` is a plain dataclass and takes
any attribute; the slotted row has every ``preview_*_texture_path`` field but no
parser-level ``texture``, and assigning one raised straight through the
resolver's completion callback, so Solid (Textured) never got its base binding.
"""

from __future__ import annotations

from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.mesh_editor.tab_dotnet_material_commit import material_resource_snapshot


_BASE_BINDING = {
    "resource_id": "authority/base",
    "channel": "base",
    "source_dds_path": "C:/authority/base.dds",
    "affected_submeshes": [0],
}


def test_base_binding_on_preview_model_rows_lands_in_preview_texture_path() -> None:
    model = ModelPreviewData(
        path="character/model/test.pac",
        meshes=[
            ModelPreviewMesh(material_name="Blade", preview_texture_path="C:/imported/blade.png"),
            ModelPreviewMesh(material_name="Hilt", preview_texture_path="C:/imported/hilt.png"),
        ],
    )

    snapshot = material_resource_snapshot(object(), model, (_BASE_BINDING,), (0,))

    assert snapshot.submeshes[0].preview_texture_path == "C:/authority/base.dds"
    assert not hasattr(snapshot.submeshes[0], "texture")
    assert snapshot.submeshes[1].preview_texture_path == "C:/imported/hilt.png"
    # The snapshot is a copy: the live preview model keeps its own bindings.
    assert model.meshes[0].preview_texture_path == "C:/imported/blade.png"


def test_base_binding_on_parser_rows_still_sets_texture_and_preview_path() -> None:
    mesh = ParsedMesh(
        path="character/model/test.pac",
        format="pac",
        submeshes=[SubMesh(name="Blade", material="Blade", texture="cd_blade")],
    )

    snapshot = material_resource_snapshot(object(), mesh, (_BASE_BINDING,), (0,))

    assert snapshot.submeshes[0].texture == "C:/authority/base.dds"
    assert snapshot.submeshes[0].preview_texture_path == "C:/authority/base.dds"
    assert mesh.submeshes[0].texture == "cd_blade"


def test_removed_binding_clears_only_the_slots_the_row_has() -> None:
    model = ModelPreviewData(
        meshes=[ModelPreviewMesh(material_name="Blade", preview_normal_texture_path="C:/n.png")],
    )

    snapshot = material_resource_snapshot(
        object(),
        model,
        ({"channel": "normal", "remove": True, "affected_submeshes": [0]},),
        (0,),
    )

    assert snapshot.submeshes[0].preview_normal_texture_path == ""
