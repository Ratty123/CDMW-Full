from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.core import archive_modding
from cdmw.core.mesh_baseline import MeshBaselineData
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ImportAutoFixResult,
    ModelPreviewData,
    ModelPreviewMesh,
    ModPackageInfo,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.modding.static_mesh_replacer import (
    StaticMeshReplacementOptions,
    StaticMeshReplacementReport,
    StaticReplacementTransform,
)


def _mesh(path: str, vertices: list[tuple[float, float, float]]) -> ParsedMesh:
    submesh = SubMesh(
        name="part",
        material="part",
        vertices=vertices,
        faces=[(0, 1, 2)],
    )
    return ParsedMesh(
        path=path,
        format=Path(path).suffix.lstrip(".").lower(),
        submeshes=[submesh],
        total_vertices=len(vertices),
        total_faces=1,
    )


def _entry(path: str, root: Path) -> ArchiveEntry:
    package_root = root / "0009"
    package_root.mkdir(parents=True, exist_ok=True)
    return ArchiveEntry(
        path=path,
        pamt_path=package_root / "package.pamt",
        paz_file=package_root / "package.paz",
        offset=0,
        comp_size=0,
        orig_size=0,
        flags=0,
        paz_index=0,
    )


class MeshImportPreviewStaticEditTests(unittest.TestCase):
    def test_edited_source_mesh_override_flows_through_static_import_preview(self) -> None:
        entry = ArchiveEntry(
            path="character/model/test.pac",
            pamt_path=Path("test.pamt"),
            paz_file=Path("test.paz"),
            offset=0,
            comp_size=0,
            orig_size=0,
            flags=0,
            paz_index=0,
        )
        original_mesh = _mesh(
            entry.path,
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        )
        imported_mesh = _mesh(
            "replacement.obj",
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        )
        edited_mesh = _mesh(
            "replacement.obj",
            [(0.5, 0.0, 0.0), (1.5, 0.0, 0.0), (0.5, 1.0, 0.0)],
        )
        rebuilt_mesh = _mesh(
            entry.path,
            [(0.5, 0.0, 0.0), (1.5, 0.0, 0.0), (0.5, 1.0, 0.0)],
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            edited_source_mesh=edited_mesh,
        )
        captured: dict[str, object] = {}

        def fake_parse_mesh(data: bytes, virtual_path: str) -> ParsedMesh:
            if data == b"original":
                return original_mesh
            if data == b"rebuilt":
                return rebuilt_mesh
            raise AssertionError(f"Unexpected parse payload for {virtual_path}: {data!r}")

        def fake_build_static_mesh_replacement(
            original_data: bytes,
            original: ParsedMesh,
            replacement: ParsedMesh,
            static_options: StaticMeshReplacementOptions,
        ) -> tuple[bytes, StaticMeshReplacementReport]:
            captured["replacement_vertices"] = tuple(replacement.submeshes[0].vertices)
            captured["edited_vertices"] = tuple(static_options.edited_source_mesh.submeshes[0].vertices)  # type: ignore[union-attr]
            captured["mapping_vertices"] = tuple(
                archive_modding.effective_static_replacement_source_mesh(
                    original,
                    replacement,
                    static_options,
                ).submeshes[0].vertices
            )
            return b"rebuilt", StaticMeshReplacementReport(
                original_submesh_count=1,
                replacement_submesh_count=1,
                original_vertex_count=3,
                replacement_vertex_count=3,
                original_face_count=1,
                replacement_face_count=1,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            obj_path = Path(temp_dir) / "replacement.obj"
            obj_path.write_text("# untouched source OBJ\n", encoding="utf-8")

            with (
                patch.object(
                    archive_modding,
                    "read_archive_entry_baseline_data",
                    return_value=MeshBaselineData(data=b"original", from_cache=False),
                ),
                patch.object(archive_modding, "parse_mesh", side_effect=fake_parse_mesh),
                patch.object(
                    archive_modding,
                    "build_static_mesh_replacement",
                    side_effect=fake_build_static_mesh_replacement,
                ),
                patch.object(
                    archive_modding,
                    "_build_mesh_import_validation",
                    return_value=((), (), ImportAutoFixResult(), []),
                ),
                patch.object(archive_modding, "_load_obj_roundtrip_sidecar", return_value=None),
                patch("cdmw.core.archive.build_archive_model_texture_references", return_value=()),
            ):
                result = archive_modding.build_mesh_import_preview(
                    entry,
                    obj_path,
                    import_mode="static_replacement",
                    static_replacement_options=options,
                    scene_import_result=SceneImportResult(mesh=imported_mesh),
                )

            self.assertEqual("# untouched source OBJ\n", obj_path.read_text(encoding="utf-8"))

        self.assertEqual("static_replacement", result.import_mode)
        self.assertEqual(tuple(imported_mesh.submeshes[0].vertices), captured["replacement_vertices"])
        self.assertEqual(tuple(edited_mesh.submeshes[0].vertices), captured["edited_vertices"])
        self.assertEqual(tuple(edited_mesh.submeshes[0].vertices), captured["mapping_vertices"])
        self.assertEqual((0.5, 0.0, 0.0), result.parsed_mesh.submeshes[0].vertices[0])

    def test_local_sidecar_preview_does_not_promote_unrelated_named_base(self) -> None:
        preview_model = ModelPreviewData(
            path="character/model/test.pac",
            meshes=[
                ModelPreviewMesh(material_name="CD_Test_Part_A", texture_name="CD_Test_Part_A"),
                ModelPreviewMesh(material_name="CD_Test_Part_B", texture_name="CD_Test_Part_B"),
            ],
        )
        bindings = (
            SimpleNamespace(
                texture_path="character/texture/part_a.dds",
                parameter_name="_diffuseTextureR",
                submesh_name="CD_Test_Part_A",
            ),
        )

        with patch(
            "cdmw.core.pipeline.ensure_dds_display_preview_png",
            side_effect=lambda _texconv, dds_path, **_kwargs: f"preview://{Path(dds_path).name}",
        ):
            lines = archive_modding._apply_mesh_import_local_sidecar_texture_overrides(
                preview_model,
                parsed_mesh=None,
                sidecar_texture_bindings=bindings,
                supplemental_dds_by_normalized_path={"character/texture/part_a.dds": Path("part_a.dds")},
                supplemental_dds_by_basename={"part_a.dds": Path("part_a.dds")},
                texconv_path=Path("texconv.exe"),
            )

        self.assertEqual("character/texture/part_a.dds", preview_model.meshes[0].texture_name)
        self.assertEqual("preview://part_a.dds", preview_model.meshes[0].preview_texture_path)
        self.assertEqual("CD_Test_Part_B", preview_model.meshes[1].texture_name)
        self.assertEqual("", preview_model.meshes[1].preview_texture_path)
        self.assertNotIn("local sidecar texture fallback", "\n".join(lines))

    def test_runtime_sibling_warning_flags_display_clone_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            display_entry = _entry(
                "character/model/2_mon/cd_m0001/armor/19_cloak/cd_m0001_00_de_pdm_cloak_21009.pac",
                root,
            )
            player_entry = _entry(
                "character/model/1_pc/1_phm/armor/19_cloak/cd_phm_00_cloak_0009.pac",
                root,
            )
            mesh = ParsedMesh(
                path=display_entry.path,
                format="pac",
                submeshes=[
                    SubMesh(
                        name="CD_PHM_00_Cloak_0009",
                        material="CD_PHM_00_Cloak_0009",
                        vertices=[(0.0, 0.0, 0.0)],
                        faces=[],
                    )
                ],
            )

            lines = archive_modding._mesh_import_runtime_sibling_warning_lines(
                display_entry,
                mesh,
                {"cd_phm_00_cloak_0009.pac": (player_entry,)},
            )

        self.assertIn("Runtime target warning", "\n".join(lines))
        self.assertIn(player_entry.path, "\n".join(lines))

    def test_loose_export_auto_copies_exact_mesh_companions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = _entry("character/model/armor/test_cloak.pac", root)
            sidecar = _entry("character/modelproperty/armor/test_cloak.pac_xml", root)
            physics = _entry("character/bin__/meshphysics/armor/test_cloak.hkx", root)
            unrelated = _entry("character/modelproperty/armor/other_cloak.pac_xml", root)
            preview = archive_modding.MeshImportPreviewResult(
                rebuilt_data=b"rebuilt",
                parsed_mesh=ParsedMesh(path=primary.path, format="pac"),
                preview_model=ModelPreviewData(),
                summary_lines=[],
                texture_references=(
                    ArchiveModelTextureReference(
                        reference_name=sidecar.basename,
                        resolved_archive_path=sidecar.path,
                        resolved_entry=sidecar,
                        resolution_status="resolved",
                        relation_group="Material Sidecars",
                        reference_kind="material_sidecar",
                    ),
                    ArchiveModelTextureReference(
                        reference_name=physics.basename,
                        resolved_archive_path=physics.path,
                        resolved_entry=physics,
                        resolution_status="resolved",
                        relation_group="Physics / Collision",
                        reference_kind="physics",
                    ),
                    ArchiveModelTextureReference(
                        reference_name=unrelated.basename,
                        resolved_archive_path=unrelated.path,
                        resolved_entry=unrelated,
                        resolution_status="resolved",
                        relation_group="Material Sidecars",
                        reference_kind="material_sidecar",
                    ),
                ),
            )

            def fake_extract(entry: ArchiveEntry, target_path: Path, **_kwargs: object) -> Path:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(f"related:{entry.path}".encode("utf-8"))
                return target_path

            with patch("cdmw.core.archive.extract_archive_entry", side_effect=fake_extract):
                result = archive_modding.export_archive_mesh_payloads_to_mod_ready_loose(
                    (archive_modding.ArchivePatchRequest(primary, b"rebuilt"),),
                    primary_entry=primary,
                    preview_result=preview,
                    source_obj_path=root / "source.obj",
                    parent_root=root,
                    package_info=ModPackageInfo(title="Mesh Mod"),
                    related_entries_to_include=(),
                )

            self.assertTrue((result.package_root / "character" / "modelproperty" / "armor" / "test_cloak.pac_xml").exists())
            self.assertTrue((result.package_root / "character" / "bin__" / "meshphysics" / "armor" / "test_cloak.hkx").exists())
            self.assertFalse((result.package_root / "character" / "modelproperty" / "armor" / "other_cloak.pac_xml").exists())


if __name__ == "__main__":
    unittest.main()
