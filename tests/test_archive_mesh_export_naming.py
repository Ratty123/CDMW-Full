import unittest
import tempfile
from pathlib import Path

from cdmw.core.archive_modding import (
    _build_export_mtl_texture_overrides,
    _mesh_export_basename,
    _rewrite_export_mtl_map_kd,
)
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


class ArchiveMeshExportNamingTests(unittest.TestCase):
    def test_archive_mesh_export_basename_uses_original_filename_stem(self) -> None:
        entry = ArchiveEntry(
            path="character/model/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.pac",
            pamt_path=Path("0009/0.pamt"),
            paz_file=Path("0009/0.paz"),
            offset=0,
            comp_size=1,
            orig_size=1,
            flags=0,
            paz_index=0,
        )

        self.assertEqual("cd_pgw_00_nude_00_0001", _mesh_export_basename(entry))

    def test_archive_mesh_export_basename_sanitizes_filename_only(self) -> None:
        entry = ArchiveEntry(
            path="object/model/folder/weird:name?.pam",
            pamt_path=Path("0001/0.pamt"),
            paz_file=Path("0001/0.paz"),
            offset=0,
            comp_size=1,
            orig_size=1,
            flags=0,
            paz_index=0,
        )

        self.assertEqual("weird_name", _mesh_export_basename(entry))

    def test_obj_mtl_overrides_use_resolved_sidecar_base_texture(self) -> None:
        parsed_mesh = ParsedMesh(
            submeshes=[
                SubMesh(
                    name="CD_PHM_02_Sword_Guard_0015",
                    material="CD_PHM_02_Guard_0013",
                    texture="CD_PHM_02_Guard_0013",
                )
            ]
        )
        references = (
            ArchiveModelTextureReference(
                reference_name="character/texture/cd_phm_02_guard_0013_n.dds",
                material_name="cd_phm_02_sword_guard_0015",
                semantic_label="Normal Texture",
                semantic_hint="_normalTexture",
                sidecar_parameter_name="_normalTexture",
                resolved_archive_path="character/texture/cd_phm_02_guard_0013_n.dds",
                resolution_status="resolved",
                relation_confidence="exact_path",
                relation_group="Textures",
            ),
            ArchiveModelTextureReference(
                reference_name="character/texture/cd_texturelayer_003_0006.dds",
                material_name="cd_phm_02_sword_guard_0015",
                semantic_label="Base / diffuse",
                semantic_hint="_detailDiffuseMaskG",
                sidecar_parameter_name="_detailDiffuseMaskG",
                resolved_archive_path="character/texture/cd_texturelayer_003_0006.dds",
                resolution_status="resolved",
                relation_confidence="exact_path",
                relation_group="Textures",
            ),
        )

        overrides = _build_export_mtl_texture_overrides(parsed_mesh, references)

        self.assertEqual(
            {"CD_PHM_02_Guard_0013": "character/texture/cd_texturelayer_003_0006.dds"},
            overrides,
        )

    def test_obj_mtl_rewrite_points_to_copied_referenced_texture(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            texture_path = root / "referenced_files" / "character" / "texture" / "cd_texturelayer_003_0006.dds"
            texture_path.parent.mkdir(parents=True, exist_ok=True)
            texture_path.write_bytes(b"DDS ")
            mtl_path = root / "sword.mtl"
            mtl_path.write_text(
                "\n".join(
                    [
                        "# Crimson Desert Materials",
                        "",
                        "newmtl CD_PHM_02_Guard_0013",
                        "Ka 1.000 1.000 1.000",
                        "map_Kd CD_PHM_02_Guard_0013.dds",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            changed = _rewrite_export_mtl_map_kd(
                mtl_path,
                {"CD_PHM_02_Guard_0013": "character/texture/cd_texturelayer_003_0006.dds"},
                root,
            )

            self.assertEqual(1, changed)
            self.assertIn(
                "map_Kd referenced_files/character/texture/cd_texturelayer_003_0006.dds",
                mtl_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
