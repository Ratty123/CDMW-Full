from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
import json

from cdmw.core.archive import ArchiveSearchTerm, filter_archive_entries, parse_archive_search_query
from cdmw.core.archive_relationships import build_character_dependency_plan
from cdmw.core.final_package_preview import (
    build_final_package_preview,
    build_final_package_specs_from_package_root,
    stage_final_package_preview_payloads,
)
from cdmw.core.pipeline import inspect_crimson_dds, validate_dds_payload_size
from cdmw.core.structured_binary_editor import (
    PabghRow,
    parse_length_prefixed_string_fields,
    parse_pabgh_table,
    patch_length_prefixed_string,
    rebuild_pabgh_table,
)
from cdmw.core.skeleton_resolver import build_skin_binding_map, resolve_skeleton_for_model
from cdmw.core.archive_modding import MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewMesh
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.skeleton_parser import Skeleton


def _entry(path: str, *, size: int = 100, package: str = "0009", root: Path | None = None, data: bytes = b"") -> ArchiveEntry:
    pamt_path = (root or Path("C:/game")) / package / "0.pamt"
    paz_path = (root or Path("C:/game")) / package / "0.paz"
    return ArchiveEntry(
        path=path,
        pamt_path=pamt_path,
        paz_file=paz_path,
        offset=0,
        comp_size=len(data) if data else size,
        orig_size=len(data) if data else size,
        flags=0,
        paz_index=0,
    )


def _entries_with_payloads(payloads):
    tempdir = tempfile.TemporaryDirectory()
    root = Path(tempdir.name)
    package = root / "0009"
    package.mkdir(parents=True, exist_ok=True)
    paz_path = package / "0.paz"
    pamt_path = package / "0.pamt"
    entries = []
    offset = 0
    with paz_path.open("wb") as handle:
        for path, payload in payloads:
            data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            handle.write(data)
            entries.append(
                ArchiveEntry(
                    path=path,
                    pamt_path=pamt_path,
                    paz_file=paz_path,
                    offset=offset,
                    comp_size=len(data),
                    orig_size=len(data),
                    flags=0,
                    paz_index=0,
                )
            )
            offset += len(data)
    return tempdir, tuple(entries)


def _pab_payload(name: str = "Root", name_hash: int = 0x00123456) -> bytes:
    data = bytearray(b"PAR " + b"\x00" * (0x16 - 4))
    struct.pack_into("<H", data, 0x14, 1)
    data.extend(struct.pack("<I", name_hash))
    data.append(len(name))
    data.extend(name.encode("ascii"))
    data.extend(struct.pack("<i", -1))
    data.extend(struct.pack("<16f", *([1.0] * 16)))
    data.extend(struct.pack("<16f", *([1.0] * 16)))
    data.extend(b"\x00" * 128)
    data.extend(struct.pack("<fff", 1.0, 1.0, 1.0))
    data.extend(struct.pack("<ffff", 0.0, 0.0, 0.0, 1.0))
    data.extend(struct.pack("<fff", 0.0, 0.0, 0.0))
    return bytes(data)


class ReleaseInspiredImprovementTests(unittest.TestCase):
    def test_archive_query_parser_and_filter_supports_qualifiers_boolean_and_prefix_tokens(self) -> None:
        query = parse_archive_search_query('name:"Canta Plate" ext:pac NOT path:cloak OR size:>1kb')
        self.assertEqual(len(query.groups), 2)
        self.assertTrue(any(isinstance(term, ArchiveSearchTerm) and term.field == "name" for term in query.groups[0]))

        entries = [
            _entry("character/model/cd_phm_00_canta_plate_helm.pac", size=800),
            _entry("character/model/cd_phm_00_eccanta_plate_helm.pac", size=800),
            _entry("character/model/cd_phm_00_canta_plate_cloak.pac", size=800),
            _entry("character/model/large_unrelated.dds", size=4096),
        ]
        filtered = filter_archive_entries(
            entries,
            filter_text='name:"Canta Plate" ext:pac NOT path:cloak OR size:>1kb',
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
        )

        self.assertEqual(
            [entry.path for entry in filtered],
            [
                "character/model/cd_phm_00_canta_plate_helm.pac",
                "character/model/large_unrelated.dds",
            ],
        )

    def test_archive_content_query_is_explicit_and_slow_path(self) -> None:
        tempdir, entries = _entries_with_payloads(
            [
                ("character/appearance/a.app_xml", "<Appearance><Nude Name='body_a' /></Appearance>"),
                ("character/appearance/b.app_xml", "<Appearance><Nude Name='body_b' /></Appearance>"),
            ]
        )
        self.addCleanup(tempdir.cleanup)

        filtered = filter_archive_entries(
            entries,
            filter_text="content:body_b",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
        )

        self.assertEqual([entry.path for entry in filtered], ["character/appearance/b.app_xml"])

    def test_skeleton_resolver_reports_selected_candidate_and_strict_skin_map_blocks_missing_mapping(self) -> None:
        model = _entry("character/model/body_a.pac", data=b"\x56\x34\x12\x00")
        skeleton = _entry("character/model/body_a.pab")
        selected, report = resolve_skeleton_for_model(
            model,
            (),
            archive_entries_by_normalized_path={"character/model/body_a.pab": (skeleton,)},
            archive_entries_by_basename={"body_a.pab": (skeleton,)},
            pac_data=b"\x56\x34\x12\x00",
            read_entry_data=lambda _entry: _pab_payload(name_hash=0x00123456),
        )

        self.assertIs(selected, skeleton)
        self.assertEqual(report.selected_path, "character/model/body_a.pab")
        self.assertIn(report.confidence, {"palette", "exact"})

        parsed = Skeleton(path="character/model/body_a.pab")
        parsed.bones = []
        binding = build_skin_binding_map(parsed, (), strict=True)
        self.assertFalse(binding.is_complete)
        self.assertIn("No PAB-ordered skeleton bones", "\n".join(binding.blocking_errors))

    def test_skeleton_resolver_prefers_palette_evidence_over_exact_path(self) -> None:
        model = _entry("character/model/body_a.pac", data=b"\x56\x34\x12\x00")
        exact = _entry("character/model/body_a.pab")
        palette = _entry("character/skeleton/rig_body.pab")

        def read_payload(entry: ArchiveEntry) -> bytes:
            if entry is palette:
                return _pab_payload(name="PaletteBone", name_hash=0x00123456)
            return _pab_payload(name="OtherBone", name_hash=0x00ABCDEF)

        selected, report = resolve_skeleton_for_model(
            model,
            (exact, palette),
            archive_entries_by_normalized_path={"character/model/body_a.pab": (exact,)},
            archive_entries_by_basename={
                "body_a.pab": (exact,),
                "rig_body.pab": (palette,),
            },
            pac_data=b"\x56\x34\x12\x00",
            read_entry_data=read_payload,
        )

        self.assertIs(selected, palette)
        self.assertEqual("palette", report.confidence)
        self.assertEqual("character/skeleton/rig_body.pab", report.selected_path)

    def test_skeleton_resolver_refuses_ambiguous_heuristic_candidates(self) -> None:
        model = _entry("character/model/body_a.pac", data=b"no palette")
        first = _entry("character/model/rig_a.pab")
        second = _entry("character/model/rig_b.pab")

        selected, report = resolve_skeleton_for_model(
            model,
            (first, second),
            archive_entries_by_basename={
                "rig_a.pab": (first,),
                "rig_b.pab": (second,),
            },
            pac_data=b"no palette",
            read_entry_data=lambda _entry: _pab_payload(name_hash=0x00ABCDEF),
        )

        self.assertIsNone(selected)
        self.assertEqual("ambiguous", report.confidence)
        self.assertIn("Multiple skeleton candidates", "\n".join(report.blocking_errors))

    def test_character_dependency_plan_requires_matching_appearance_graph(self) -> None:
        tempdir, entries = _entries_with_payloads(
            [
                ("character/appearance/hero.app_xml", "<Appearance><Nude Name='body_a' /></Appearance>"),
                ("character/prefab/body_a.prefabdata_xml", '<Prefab FileName="body_a.pac" SkeletonName="body_a.pab" />'),
                ("character/model/body_a.pac", b"PAC"),
                ("character/model/body_a.pab", b"PAB"),
                ("character/texture/body_a.dds", b"DDS "),
            ]
        )
        self.addCleanup(tempdir.cleanup)
        body = next(entry for entry in entries if entry.path.endswith("body_a.pac"))

        plan = build_character_dependency_plan(body, entries)

        self.assertEqual(plan.selected_appearance_path, "character/appearance/hero.app_xml")
        self.assertFalse(plan.blocking_errors)
        self.assertIn("character/model/body_a.pac", [entry.path for entry in plan.entries])
        self.assertIn("character/appearance/hero.app_xml", [entry.path for entry in plan.entries])

    def test_structured_string_and_pabgh_safe_editors_validate_round_trips(self) -> None:
        payload = struct.pack("<I", 12) + b"old_path.paa\x00" + b"tail"
        fields = parse_length_prefixed_string_fields(payload)
        self.assertEqual(fields[0].kind, "animation")

        patched = patch_length_prefixed_string(payload, fields[0], "new_path.paa")
        self.assertEqual(len(patched.data), len(payload))
        with self.assertRaises(ValueError):
            patch_length_prefixed_string(payload, fields[0], "this_replacement_is_too_long.paa")

        table_payload = struct.pack("<HBI", 1, 7, 4) + b"data"
        table = parse_pabgh_table(table_payload)
        self.assertEqual(table.row_size, 5)
        rebuilt = rebuild_pabgh_table(table_payload, [PabghRow(index=0, row_id=7, offset=5)], row_size=5)
        self.assertEqual(parse_pabgh_table(rebuilt).rows[0].offset, 5)

    def test_dds_payload_validation_reports_truncated_payload(self) -> None:
        header = bytearray(124)
        struct.pack_into("<I", header, 0, 124)
        struct.pack_into("<I", header, 4, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000)
        struct.pack_into("<I", header, 8, 4)
        struct.pack_into("<I", header, 12, 4)
        struct.pack_into("<I", header, 24, 1)
        struct.pack_into("<I", header, 72, 32)
        struct.pack_into("<I", header, 76, 0x4)
        header[80:84] = b"DXT1"
        truncated = b"DDS " + bytes(header) + b"\x00\x00"

        ok, message, actual, expected = validate_dds_payload_size(truncated)
        self.assertFalse(ok)
        self.assertLess(actual, expected)
        self.assertIn("truncated", message)
        self.assertTrue(any(finding.code == "payload_truncated" for finding in inspect_crimson_dds(truncated).findings))

    def test_final_package_preview_exposes_texture_resolution_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = root / "model.pac_xml"
            sidecar.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Vector Name="_parameters">'
                '<ResourceReferencePath_ITexture Name="_baseColorTexture" value="character/texture/blade.dds"/>'
                "</Vector></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            dds = root / "blade.dds"
            dds.write_bytes(b"DDS payload")
            preview = MeshImportPreviewResult(
                rebuilt_data=b"PAC",
                parsed_mesh=ParsedMesh(path="weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    meshes=(
                        ModelPreviewMesh(
                            material_name="Blade",
                            texture_name="Blade",
                            positions=[],
                            indices=[],
                        ),
                    )
                ),
                summary_lines=[],
            )
            result = build_final_package_preview(
                preview,
                supplemental_file_specs=(
                    MeshImportSupplementalFileSpec(source_path=sidecar, target_path="character/modelproperty/model.pac_xml"),
                    MeshImportSupplementalFileSpec(source_path=dds, target_path="character/texture/blade.dds"),
                ),
            )

            manifest = result.texture_resolution_manifest
            self.assertEqual(manifest.schema, "cdmw_texture_resolution_manifest_v1")
            self.assertEqual(len(manifest.rows), 1)
            self.assertEqual(manifest.rows[0].material_name, "Blade")
            self.assertEqual(manifest.rows[0].resolved_texture_path, "character/texture/blade.dds")

    def test_final_package_preview_scans_exact_written_loose_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            sidecar_path = package_root / "character" / "modelproperty" / "weapon.pac_xml"
            texture_path = package_root / "character" / "texture" / "blade.dds"
            sidecar_path.parent.mkdir(parents=True)
            texture_path.parent.mkdir(parents=True)
            sidecar_path.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Vector Name="_parameters">'
                '<MaterialParameterTexture Name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade.dds"/>'
                "</MaterialParameterTexture></Vector></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            texture_path.write_bytes(b"DDS final package payload")
            (package_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "files_root": ".",
                        "files": [
                            {"path": "character/modelproperty/weapon.pac_xml"},
                            {"path": "character/texture/blade.dds"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            preview = MeshImportPreviewResult(
                rebuilt_data=b"PAC",
                parsed_mesh=ParsedMesh(path="weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    meshes=(ModelPreviewMesh(material_name="Blade", texture_name="Blade", positions=[], indices=[]),)
                ),
                summary_lines=[],
            )

            specs = build_final_package_specs_from_package_root(package_root)
            result = build_final_package_preview(preview, package_root=package_root, require_source_owned_colors=True)

            self.assertEqual(len(specs), 2)
            self.assertEqual(result.package_root, package_root.as_posix())
            self.assertFalse(result.preflight_errors)
            self.assertEqual(result.binding_rows[0].binding_source, "generated")
            self.assertIn("Color authority: source-owned 1", "\n".join(result.summary_lines))

    def test_test_build_stage_writes_mesh_sidecar_and_dds_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sidecar = root / "weapon.pac_xml"
            dds = root / "blade.dds"
            sidecar.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Vector Name="_parameters">'
                '<MaterialParameterTexture Name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade.dds"/>'
                "</MaterialParameterTexture></Vector></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            dds.write_bytes(b"DDS final package payload")
            preview = MeshImportPreviewResult(
                rebuilt_data=b"PAC final bytes",
                parsed_mesh=ParsedMesh(path="character/model/weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    meshes=(ModelPreviewMesh(material_name="Blade", texture_name="Blade", positions=[], indices=[]),)
                ),
                summary_lines=[],
            )

            package_root = stage_final_package_preview_payloads(
                preview,
                supplemental_file_specs=(
                    MeshImportSupplementalFileSpec(source_path=sidecar, target_path="character/modelproperty/weapon.pac_xml"),
                    MeshImportSupplementalFileSpec(source_path=dds, target_path="character/texture/blade.dds"),
                ),
                label="unit_test",
            )
            specs = build_final_package_specs_from_package_root(package_root)

            self.assertTrue((package_root / "character" / "model" / "weapon.pac").is_file())
            self.assertEqual({spec.kind for spec in specs}, {"mesh", "sidecar_generated", "texture_generated"})

    def test_final_package_preflight_blocks_missing_source_owned_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            sidecar_path = package_root / "character" / "modelproperty" / "weapon.pac_xml"
            sidecar_path.parent.mkdir(parents=True)
            sidecar_path.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Vector Name="_parameters">'
                '<MaterialParameterTexture Name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/missing.dds"/>'
                "</MaterialParameterTexture></Vector></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            preview = MeshImportPreviewResult(
                rebuilt_data=b"PAC",
                parsed_mesh=ParsedMesh(path="weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    meshes=(ModelPreviewMesh(material_name="Blade", texture_name="Blade", positions=[], indices=[]),)
                ),
                summary_lines=[],
            )

            result = build_final_package_preview(preview, package_root=package_root, require_source_owned_colors=True)

            self.assertTrue(result.preflight_errors)
            self.assertTrue(any("Visible color texture is not package-resolved" in line for line in result.preflight_errors))

    def test_final_package_preflight_rejects_support_map_as_base_color(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_root = Path(temp_dir)
            sidecar_path = package_root / "character" / "modelproperty" / "weapon.pac_xml"
            texture_path = package_root / "character" / "texture" / "blade_mg.dds"
            sidecar_path.parent.mkdir(parents=True)
            texture_path.parent.mkdir(parents=True)
            sidecar_path.write_text(
                '<Root><SkinnedMeshMaterialWrapper _subMeshName="Blade"><Vector Name="_parameters">'
                '<MaterialParameterTexture Name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture Name="_value" _path="character/texture/blade_mg.dds"/>'
                "</MaterialParameterTexture></Vector></SkinnedMeshMaterialWrapper></Root>",
                encoding="utf-8",
            )
            texture_path.write_bytes(b"DDS final package payload")
            preview = MeshImportPreviewResult(
                rebuilt_data=b"PAC",
                parsed_mesh=ParsedMesh(path="weapon.pac", format="pac"),
                preview_model=ModelPreviewData(
                    meshes=(ModelPreviewMesh(material_name="Blade", texture_name="Blade", positions=[], indices=[]),)
                ),
                summary_lines=[],
            )

            result = build_final_package_preview(preview, package_root=package_root)

            self.assertTrue(any("Support map" in line and "visible color" in line for line in result.preflight_errors))


if __name__ == "__main__":
    unittest.main()
