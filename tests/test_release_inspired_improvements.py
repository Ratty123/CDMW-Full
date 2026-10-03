from __future__ import annotations

import struct
import tempfile
import unittest
from unittest.mock import patch
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
from cdmw.core import skeleton_resolver
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


if __name__ == "__main__":
    unittest.main()
