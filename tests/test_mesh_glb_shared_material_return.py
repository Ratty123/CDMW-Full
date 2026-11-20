"""GLB Export then Open Package keeps Parts that share one material name."""

from __future__ import annotations

from cdmw.modding.mesh_glb_interchange import export_glb, import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import _attach_obj_sidecar_warnings
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _part(name: str, material: str, offset: float) -> SubMesh:
    return SubMesh(
        name=name, material=material,
        vertices=[(offset, 0.0, 0.0), (offset + 1.0, 0.0, 0.0), (offset, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3, uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        faces=[(0, 1, 2)], vertex_count=3, face_count=1,
    )


def _shared_material_mesh() -> ParsedMesh:
    parts = [_part("Body", "pot_mat", 0.0), _part("Lid", "pot_mat", 2.0), _part("Handle", "iron_mat", 4.0)]
    return ParsedMesh(path="object/pot.pac", format="pac", submeshes=parts,
                      total_vertices=9, total_faces=3, has_uvs=True)


def _blocking(mesh: ParsedMesh) -> list[dict]:
    warnings = getattr(mesh, "_cdmw_obj_sidecar_warnings", None) or getattr(mesh, "_cdmw_sidecar_warnings", None) or []
    return [warning for warning in warnings if isinstance(warning, dict) and warning.get("blocks_rebuild")]


def test_glb_return_accepts_the_import_alias_for_parts_that_share_a_material(tmp_path):
    files = export_glb(_shared_material_mesh(), tmp_path / "out")
    restored = import_glb_with_sidecar(files[0])
    assert [part.material for part in restored.submeshes] == ["pot_mat", "pot_mat", "iron_mat"]
    assert not _blocking(restored)


def test_the_glb_alias_is_only_accepted_for_a_shared_material():
    entries = [{"material": "pot_mat"}, {"material": "iron_mat"}]
    mesh = ParsedMesh(submeshes=[_part("Body", "pot_mat__material_0", 0.0), _part("Handle", "other__material_1", 2.0)])
    _attach_obj_sidecar_warnings(mesh, entries, {})
    blockers = _blocking(mesh)
    assert {warning["submesh_index"] for warning in blockers} == {0, 1}
    assert all(warning["message"].startswith("Package sidecar material changed") for warning in blockers)
