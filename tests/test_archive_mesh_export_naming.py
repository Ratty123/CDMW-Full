import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

from cdmw.core.archive_modding import (
    _build_export_mtl_texture_overrides,
    export_archive_mesh,
    _mesh_export_basename,
    _rewrite_export_mtl_map_kd,
)
from cdmw.core.archive_mesh_types import MeshExportResult
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


class ArchiveMeshExportNamingTests(unittest.TestCase):
    def test_mesh_export_result_accepts_keyword_fields(self) -> None:
        result = MeshExportResult(output_paths=[Path("mesh.obj")], summary_lines=["ok"])

        self.assertEqual([Path("mesh.obj")], result.output_paths)
        self.assertEqual(["ok"], result.summary_lines)
        self.assertFalse(result.requires_confirmation)

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

    def test_internal_modify_original_export_skips_preview_context_rebuild(self) -> None:
        entry = ArchiveEntry(
            path="character/model/body.pac",
            pamt_path=Path("0009/0.pamt"),
            paz_file=Path("0009/0.paz"),
            offset=0,
            comp_size=1,
            orig_size=1,
            flags=0,
            paz_index=0,
        )
        parsed_mesh = ParsedMesh(
            path=entry.path,
            format="pac",
            submeshes=[
                SubMesh(
                    name="Body",
                    material="BodyMat",
                    texture="BodyTex",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    faces=[(0, 1, 2)],
                )
            ],
            total_vertices=3,
            total_faces=1,
            has_uvs=True,
        )

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            with patch("cdmw.core.archive_mesh_export._parse_archive_mesh", return_value=parsed_mesh), patch(
                "cdmw.core.archive.build_archive_preview_result",
                side_effect=AssertionError("preview context rebuild should be skipped"),
            ):
                result = export_archive_mesh(
                    entry,
                    root,
                    "obj",
                    resolve_skeleton_for_obj=False,
                    build_preview_context=False,
                )

            sidecar_path = next(path for path in result.output_paths if path.name.endswith(".obj.meta.json"))
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))

        self.assertEqual("mesh_roundtrip_manifest_v2", payload["format"])
        self.assertEqual("character/model/body.pac", payload["source_archive_path"])
        self.assertNotIn("family_graph", payload)


if __name__ == "__main__":
    unittest.main()
