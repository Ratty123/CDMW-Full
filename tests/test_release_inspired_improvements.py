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


def _rgba_dds_payload() -> bytes:
    header = bytearray(124)
    struct.pack_into("<I", header, 0, 124)
    struct.pack_into("<I", header, 4, 0x100F)
    struct.pack_into("<I", header, 8, 1)
    struct.pack_into("<I", header, 12, 1)
    struct.pack_into("<I", header, 16, 4)
    struct.pack_into("<I", header, 72, 32)
    struct.pack_into("<I", header, 76, 0x41)
    struct.pack_into("<I", header, 84, 32)
    struct.pack_into("<I", header, 88, 0x00FF0000)
    struct.pack_into("<I", header, 92, 0x0000FF00)
    struct.pack_into("<I", header, 96, 0x000000FF)
    struct.pack_into("<I", header, 100, 0xFF000000)
    struct.pack_into("<I", header, 104, 0x1000)
    return b"DDS " + bytes(header) + b"\x00\x00\xff\xff"


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

    def test_skeleton_resolver_prefers_prefabdata_skeleton_and_reports_pabc_context(self) -> None:
        model = _entry("character/model/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.pac")
        identity = _entry("character/identityskeleton.pab")
        descriptor = _entry("character/prefab/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.prefabdata_xml")
        skeleton = _entry("character/model/1_pc/2_phw/phw_01.pab")
        pabc = _entry("character/binary/skeletonvariation/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.pabc")
        pamt = _entry("character/model/1_pc/2_phw/phw_01.pamt")
        papr = _entry("character/model/1_pc/2_phw/phw_01.papr")
        socket = _entry("character/descriptors/socketbonedata/phw_01.pab.sockets.xml")
        entries = (model, identity, descriptor, skeleton, pabc, pamt, papr, socket)
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index: dict[str, tuple[ArchiveEntry, ...]] = {}
        for entry in entries:
            basename_index[entry.basename.lower()] = (entry,)

        def read_payload(entry: ArchiveEntry) -> bytes:
            if entry is descriptor:
                return (
                    '<PrefabData>'
                    '<SkeletonName FileName="1_pc/2_phw/phw_01.pab" />'
                    '<SkeletonVariationName FileName="1_PC/10_PGW/Nude/CD_PGW_00_Nude_00_0001.pabc" />'
                    '<MorphTargetSet FileName="1_pc/2_phw/phw_01.pamt" />'
                    '<AnimationConstraintName FileName="1_pc/2_phw/phw_01.papr" />'
                    '<SocketFileName FileName="phw_01.pab.sockets.xml" />'
                    '</PrefabData>'
                ).encode("utf-8")
            return _pab_payload(name_hash=0x00ABCDEF)

        selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            pac_data=b"no palette",
            read_entry_data=read_payload,
        )

        self.assertIs(selected, skeleton)
        self.assertEqual("descriptor", report.confidence)
        self.assertEqual(descriptor.path, report.descriptor_path)
        self.assertEqual(pabc.path, report.skeleton_variation_path)
        self.assertEqual(descriptor.path, report.morph_descriptor_path)
        self.assertEqual(pamt.path, report.morph_target_path)
        self.assertEqual(papr.path, report.animation_constraint_path)
        self.assertEqual(socket.path, report.socket_path)
        self.assertNotEqual(identity.path, report.selected_path)

    def test_skeleton_resolver_combines_body_skeleton_with_sibling_head_morph_descriptor(self) -> None:
        family = "2_mon/cd_m0002_00_fourfeet/cd_m0002_00_buffalo/cd_m0002_00_buffalo"
        model = _entry(f"character/model/{family}/cd_m0002_00_buffalo_00_0001.pac")
        body_descriptor = _entry(
            f"character/prefab/{family}/cd_m0002_00_buffalo_00_0001.prefabdata_xml"
        )
        head_descriptor = _entry(
            f"character/prefab/{family}/cd_m0002_00_buffalo_head_0001.prefabdata_xml"
        )
        skeleton = _entry(f"character/model/{family}/cd_m0002_00_buffalo.pab")
        morphs = _entry(f"character/model/{family}/cd_m0002_00_buffalo.pamt")
        entries = (model, body_descriptor, head_descriptor, skeleton, morphs)
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}

        def read_payload(entry: ArchiveEntry) -> bytes:
            if entry is body_descriptor:
                return (
                    '<NudePrefabData><SkeletonName FileName="'
                    f'{family}/cd_m0002_00_buffalo.pab"/></NudePrefabData>'
                ).encode("utf-8")
            if entry is head_descriptor:
                return (
                    '<HeadPrefabData><MorphTargetSet FileName="'
                    f'{family}/cd_m0002_00_buffalo.pamt"/></HeadPrefabData>'
                ).encode("utf-8")
            return _pab_payload()

        selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=read_payload,
        )

        self.assertIs(skeleton, selected)
        self.assertEqual(body_descriptor.path, report.descriptor_path)
        self.assertEqual(head_descriptor.path, report.morph_descriptor_path)
        self.assertEqual(morphs.path, report.morph_target_path)
        self.assertIn("sibling prefabdata descriptor", report.reason)

    def test_skeleton_resolver_uses_cross_folder_morphs_from_the_same_named_family(self) -> None:
        body_family = "2_mon/cd_m0002_00_fourfeet/cd_m0002_00_dog/cd_m0002_00_cat"
        model = _entry(f"character/model/{body_family}/cd_m0002_00_hatch_00_0001.pac")
        body_descriptor = _entry(
            f"character/prefab/{body_family}/cd_m0002_00_hatch_00_0001.prefabdata_xml"
        )
        wrong_head_descriptor = _entry(
            f"character/prefab/{body_family}/cd_m0002_00_catbaby_head_0001.prefabdata_xml"
        )
        hatch_head_descriptor = _entry(
            "character/prefab/2_mon/cd_m0002_00_fourfeet/cd_m0002_00_hatch/"
            "cd_m0002_00_hatch_head_00_0001.prefabdata_xml"
        )
        skeleton = _entry("character/model/2_mon/cd_m0002_00_fourfeet/cd_m0011_00_dog.pab")
        wrong_morphs = _entry(f"character/model/{body_family}/cd_m0002_00_cat.pamt")
        hatch_morphs = _entry(
            "character/model/2_mon/cd_m0002_00_fourfeet/cd_m0002_00_hatch/cd_m0002_00_hatch.pamt"
        )
        entries = (
            model,
            body_descriptor,
            wrong_head_descriptor,
            hatch_head_descriptor,
            skeleton,
            wrong_morphs,
            hatch_morphs,
        )
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}
        payloads = {
            body_descriptor.path: (
                '<NudePrefabData><SkeletonName FileName="2_mon/cd_m0002_00_fourfeet/'
                'cd_m0011_00_dog.pab"/></NudePrefabData>'
            ),
            wrong_head_descriptor.path: (
                f'<HeadPrefabData><MorphTargetSet FileName="{body_family}/cd_m0002_00_cat.pamt"/>'
                '</HeadPrefabData>'
            ),
            hatch_head_descriptor.path: (
                '<HeadPrefabData><MorphTargetSet FileName="2_mon/cd_m0002_00_fourfeet/'
                'cd_m0002_00_hatch/cd_m0002_00_hatch.pamt"/></HeadPrefabData>'
            ),
        }

        _selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )

        self.assertEqual(body_descriptor.path, report.descriptor_path)
        self.assertEqual(hatch_head_descriptor.path, report.morph_descriptor_path)
        self.assertEqual(hatch_morphs.path, report.morph_target_path)

    def test_skeleton_resolver_does_not_apply_family_head_morphs_to_a_tail_part(self) -> None:
        family = "2_mon/cd_m0002_00_fourfeet/cd_m0002_00_hatch"
        model = _entry(f"character/model/{family}/cd_m0002_00_hatch_tail_00_0001.pac")
        tail_descriptor = _entry(
            f"character/prefab/{family}/cd_m0002_00_hatch_tail_00_0001.prefabdata_xml"
        )
        head_descriptor = _entry(
            f"character/prefab/{family}/cd_m0002_00_hatch_head_00_0001.prefabdata_xml"
        )
        skeleton = _entry(f"character/model/{family}/cd_m0002_00_hatch.pab")
        morphs = _entry(f"character/model/{family}/cd_m0002_00_hatch.pamt")
        entries = (model, tail_descriptor, head_descriptor, skeleton, morphs)
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}
        payloads = {
            tail_descriptor.path: (
                f'<TailPrefabData><SkeletonName FileName="{family}/cd_m0002_00_hatch.pab"/>'
                '</TailPrefabData>'
            ),
            head_descriptor.path: (
                f'<HeadPrefabData><MorphTargetSet FileName="{family}/cd_m0002_00_hatch.pamt"/>'
                '</HeadPrefabData>'
            ),
        }

        _selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )

        self.assertEqual(tail_descriptor.path, report.descriptor_path)
        self.assertEqual("", report.morph_descriptor_path)
        self.assertEqual("", report.morph_target_path)

    def test_skeleton_resolver_does_not_treat_a_head_descriptor_as_a_tail_owner(self) -> None:
        family = "2_mon/cd_m0002_00_fourfeet/cd_m0002_00_hatch"
        model = _entry(f"character/model/{family}/cd_m0002_00_hatch_tail_00_0001.pac")
        tail_descriptor = _entry(
            f"character/prefab/{family}/cd_m0002_00_hatch_tail_00_0001.prefabdata_xml"
        )
        head_descriptor = _entry(
            f"character/prefab/{family}/cd_m0002_00_hatch_head_00_0001.prefabdata_xml"
        )
        wrong_family_descriptor = _entry(
            f"character/prefab/{family}/cd_m0002_00_cat_00_0001.prefabdata_xml"
        )
        wrong_family_skeleton = _entry(f"character/model/{family}/cd_m0011_00_dog.pab")
        wrong_family_morphs = _entry(f"character/model/{family}/cd_m0002_00_cat.pamt")
        morphs = _entry(f"character/model/{family}/cd_m0002_00_hatch.pamt")
        entries = (
            model,
            tail_descriptor,
            head_descriptor,
            wrong_family_descriptor,
            wrong_family_skeleton,
            wrong_family_morphs,
            morphs,
        )
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}
        payloads = {
            tail_descriptor.path: "<TailPrefabData />",
            head_descriptor.path: (
                f'<HeadPrefabData><MorphTargetSet FileName="{family}/cd_m0002_00_hatch.pamt"/>'
                '</HeadPrefabData>'
            ),
            wrong_family_descriptor.path: (
                f'<NudePrefabData><SkeletonName FileName="{family}/cd_m0011_00_dog.pab"/>'
                f'<MorphTargetSet FileName="{family}/cd_m0002_00_cat.pamt"/></NudePrefabData>'
            ),
        }

        _selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )

        self.assertEqual("", report.descriptor_path)
        self.assertEqual("", report.morph_target_path)

    def test_skeleton_resolver_combines_named_head_with_sibling_nude_skeleton(self) -> None:
        model = _entry("character/model/1_pc/5_pom/head/head/cd_pom_00_head_0001_oongka.pac")
        head_descriptor = _entry(
            "character/prefab/1_pc/05_pom/head/head/"
            "cd_pom_00_head_00_0001_oongka.prefabdata_xml"
        )
        nude_descriptor = _entry(
            "character/prefab/1_pc/05_pom/nude/"
            "cd_pom_00_nude_00_0001_oongka.prefabdata_xml"
        )
        oldarm_descriptor = _entry(
            "character/prefab/1_pc/05_pom/nude/"
            "cd_pom_00_nude_00_0004_oldarm_oongka.prefabdata_xml"
        )
        aging_descriptor = _entry(
            "character/prefab/1_pc/05_pom/nude/"
            "cd_pom_00_nude_00_0001_oongka_aging.prefabdata_xml"
        )
        skeleton = _entry("character/model/1_pc/1_phm/phm_01.pab")
        variation = _entry(
            "character/binary/skeletonvariation/1_pc/5_pom/head/head/"
            "cd_pom_oongka_head_0001.pabc"
        )
        morphs = _entry("character/model/1_pc/5_pom/pom_oongka.pamt")
        entries = (
            model,
            head_descriptor,
            nude_descriptor,
            oldarm_descriptor,
            aging_descriptor,
            skeleton,
            variation,
            morphs,
        )
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}
        payloads = {
            head_descriptor.path: (
                '<HeadPrefabData><SkeletonVariationName FileName="1_pc/5_pom/head/head/'
                'cd_pom_oongka_head_0001.pabc"/><MorphTargetSet FileName="1_pc/5_pom/'
                'pom_oongka.pamt"/></HeadPrefabData>'
            ),
            nude_descriptor.path: (
                '<NudePrefabData><SkeletonName FileName="1_pc/1_phm/phm_01.pab"/>'
                '</NudePrefabData>'
            ),
            oldarm_descriptor.path: (
                '<NudePrefabData><SkeletonName FileName="1_pc/1_phm/phm_01.pab"/>'
                '</NudePrefabData>'
            ),
            aging_descriptor.path: (
                '<NudePrefabData><SkeletonName FileName="1_pc/1_phm/phm_01.pab"/>'
                '</NudePrefabData>'
            ),
        }

        selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )

        self.assertIs(skeleton, selected)
        self.assertEqual(head_descriptor.path, report.descriptor_path)
        self.assertEqual(nude_descriptor.path, report.skeleton_descriptor_path)
        self.assertEqual(variation.path, report.skeleton_variation_path)
        self.assertEqual(head_descriptor.path, report.morph_descriptor_path)
        self.assertEqual(morphs.path, report.morph_target_path)

    def test_skeleton_resolver_does_not_borrow_named_morphs_for_a_generic_head(self) -> None:
        model = _entry("character/model/1_pc/5_pom/head/head/cd_pom_00_head_0001.pac")
        generic_descriptor = _entry(
            "character/prefab/1_pc/05_pom/head/head/cd_pom_00_head_00_0001.prefabdata_xml"
        )
        named_descriptor = _entry(
            "character/prefab/1_pc/05_pom/head/head/"
            "cd_pom_00_head_00_0001_oongka.prefabdata_xml"
        )
        generic_variation = _entry(
            "character/binary/skeletonvariation/1_pc/5_pom/head/head/cd_pom_00_head_0001.pabc"
        )
        named_morphs = _entry("character/model/1_pc/5_pom/pom_oongka.pamt")
        entries = (model, generic_descriptor, named_descriptor, generic_variation, named_morphs)
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}
        payloads = {
            generic_descriptor.path: (
                '<HeadPrefabData><SkeletonVariationName FileName="1_pc/5_pom/head/head/'
                'cd_pom_00_head_0001.pabc"/></HeadPrefabData>'
            ),
            named_descriptor.path: (
                '<HeadPrefabData><SkeletonVariationName FileName="1_pc/5_pom/head/head/'
                'cd_pom_00_head_0001.pabc"/><MorphTargetSet FileName="1_pc/5_pom/'
                'pom_oongka.pamt"/>'
                '</HeadPrefabData>'
            ),
        }

        _selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )

        self.assertEqual(generic_descriptor.path, report.descriptor_path)
        self.assertEqual("", report.morph_descriptor_path)
        self.assertEqual("", report.morph_target_path)

    def test_skeleton_resolver_prefers_same_virtual_family_folder_over_duplicate_current_stem(self) -> None:
        legacy_family = "2_mon/m0002_00_fourfeet/m0002_00_dog/m0002_00_cat"
        current_family = "2_mon/cd_m0002_00_fourfeet/cd_m0002_00_dog/cd_m0002_00_cat"
        model = _entry(f"character/model/{legacy_family}/cd_m0002_00_cat_00_0001.pac")
        current_model = _entry(f"character/model/{current_family}/cd_m0002_00_cat_00_0001.pac")
        legacy_body = _entry(
            f"character/prefab/{legacy_family}/cd_m0002_00_cat_00_0001_test.prefabdata_xml"
        )
        legacy_head = _entry(
            f"character/prefab/{legacy_family}/cd_m0002_00_cat_head_00_0001_test.prefabdata_xml"
        )
        current_body = _entry(
            f"character/prefab/{current_family}/cd_m0002_00_cat_00_0001.prefabdata_xml"
        )
        legacy_skeleton = _entry(f"character/model/{legacy_family}/m0011_00_dog.pab")
        current_skeleton = _entry(f"character/model/{current_family}/cd_m0011_00_dog.pab")
        legacy_morphs = _entry(f"character/model/{legacy_family}/cd_m0002_00_cat.pamt")
        entries = (
            model,
            current_model,
            legacy_body,
            legacy_head,
            current_body,
            legacy_skeleton,
            current_skeleton,
            legacy_morphs,
        )
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}
        payloads = {
            legacy_body.path: (
                f'<NudePrefabData><SkeletonName FileName="{legacy_family}/m0011_00_dog.pab"/>'
                '</NudePrefabData>'
            ),
            legacy_head.path: (
                f'<HeadPrefabData><MorphTargetSet FileName="{legacy_family}/cd_m0002_00_cat.pamt"/>'
                '</HeadPrefabData>'
            ),
            current_body.path: (
                f'<NudePrefabData><SkeletonName FileName="{current_family}/cd_m0011_00_dog.pab"/>'
                '</NudePrefabData>'
            ),
        }

        _selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )

        self.assertEqual(legacy_body.path, report.descriptor_path)
        self.assertEqual(legacy_head.path, report.morph_descriptor_path)
        self.assertEqual(legacy_morphs.path, report.morph_target_path)

        _current_selected, current_report = resolve_skeleton_for_model(
            current_model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )
        self.assertEqual(current_body.path, current_report.descriptor_path)
        self.assertEqual("", current_report.morph_target_path)

    def test_skeleton_resolver_keeps_prefixless_legacy_family_components_together(self) -> None:
        family = "2_mon/m0001_00_twofeet/m0001_00_bear"
        model = _entry(f"character/model/{family}/m0001_00_bear_0001.pac")
        nude_descriptor = _entry(
            f"character/prefab/{family}/m0001_00_bear_nude_0001.prefabdata_xml"
        )
        head_descriptor = _entry(
            f"character/prefab/{family}/m0001_00_bear_head_0001.prefabdata_xml"
        )
        decoy_descriptor = _entry(
            f"character/prefab/{family}/m0001_00_baby_bear_nude_0001.prefabdata_xml"
        )
        skeleton = _entry(f"character/model/{family}/m0001_00_bear.pab")
        decoy_skeleton = _entry(f"character/model/{family}/m0001_00_baby_bear.pab")
        morphs = _entry(f"character/model/{family}/cd_m0001_00_bear_0001.pamt")
        entries = (
            model,
            nude_descriptor,
            head_descriptor,
            decoy_descriptor,
            skeleton,
            decoy_skeleton,
            morphs,
        )
        path_index = {entry.path.lower(): (entry,) for entry in entries}
        basename_index = {entry.basename.lower(): (entry,) for entry in entries}
        payloads = {
            nude_descriptor.path: (
                f'<NudePrefabData><SkeletonName FileName="{family}/m0001_00_bear.pab"/>'
                '</NudePrefabData>'
            ),
            head_descriptor.path: (
                f'<HeadPrefabData><MorphTargetSet FileName="{family}/cd_m0001_00_bear_0001.pamt"/>'
                '</HeadPrefabData>'
            ),
            decoy_descriptor.path: (
                f'<NudePrefabData><SkeletonName FileName="{family}/m0001_00_baby_bear.pab"/>'
                '</NudePrefabData>'
            ),
        }

        selected, report = resolve_skeleton_for_model(
            model,
            entries,
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            read_entry_data=lambda entry: payloads.get(entry.path, "").encode("utf-8"),
        )

        self.assertIs(skeleton, selected)
        self.assertEqual(nude_descriptor.path, report.descriptor_path)
        self.assertEqual(head_descriptor.path, report.morph_descriptor_path)
        self.assertEqual(morphs.path, report.morph_target_path)

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

    def test_character_dependency_plan_bundles_character_specific_pabc_and_pamt(self) -> None:
        stem = "cd_phw_00_head_00_0111"
        tempdir, entries = _entries_with_payloads(
            [
                ("character/appearance/damian.app_xml", f'<Appearance><Head><Prefab Name="{stem}" /></Head></Appearance>'),
                (
                    f"character/prefab/1_pc/2_phw/head/head/{stem}.prefabdata_xml",
                    "<HeadPrefabData>"
                    '<SkeletonName FileName="1_pc/2_phw/phw_01.pab" />'
                    f'<SkeletonVariationName FileName="1_pc/2_phw/head/head/{stem}.pabc" />'
                    '<MorphTargetSet FileName="1_pc/2_phw/phw_damian.pamt" />'
                    "</HeadPrefabData>",
                ),
                (f"character/model/1_pc/2_phw/head/head/{stem}.pac", b"PAC"),
                ("character/model/1_pc/2_phw/phw_01.pab", b"PAB"),
                (f"character/binary/skeletonvariation/1_pc/2_phw/head/head/{stem}.pabc", b"PABC"),
                ("character/model/1_pc/2_phw/phw_damian.pamt", b"PAMT"),
            ]
        )
        self.addCleanup(tempdir.cleanup)
        model = next(entry for entry in entries if entry.extension == ".pac")

        plan = build_character_dependency_plan(model, entries)

        bundled_paths = {entry.path for entry in plan.entries}
        self.assertFalse(plan.blocking_errors)
        self.assertIn("character/model/1_pc/2_phw/phw_01.pab", bundled_paths)
        self.assertIn(f"character/binary/skeletonvariation/1_pc/2_phw/head/head/{stem}.pabc", bundled_paths)
        self.assertIn("character/model/1_pc/2_phw/phw_damian.pamt", bundled_paths)

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
            texture_path.write_bytes(_rgba_dds_payload())
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
