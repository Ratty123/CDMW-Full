"""Adding brand-new entries to a package index.

The synthetic package below mirrors the shipped layout the writer relies on: PAZ
records stored as (index, checksum, size), a folder table in file-start order whose
ranges tile the file table, byte-ordered names inside each folder, and a name block
that mixes chained and flat records.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import calculate_pa_checksum, parse_archive_pamt
from cdmw.core.archive_modding import (
    ArchiveAddRequest,
    ArchivePatchRequest,
    _verify_crc_chain,
    add_archive_entries,
    apply_archive_mutations,
    patch_archive_entries,
)
from cdmw.core.archive_entry_addition import parse_pamt_document


def _flat_name(name: str) -> bytes:
    raw = name.encode("utf-8")
    return struct.pack("<IB", 0xFFFFFFFF, len(raw)) + raw


FOLDERS = (
    "character/model",
    "character/model/weapon",
    "ui/icon",
)
# folder -> ordered file names (byte order, like the shipped tables)
FILES = {
    "character/model": ["armor_0001.pac", "armor_0002.pac"],
    "character/model/weapon": ["sword_0001.pac", "sword_0002.pac", "sword_0009.pac"],
    "ui/icon": ["itemicon_a.dds"],
}


def _build_package(root: Path) -> Path:
    """Write meta/0.papgt and 0009/{0.pamt,0.paz,1.paz}; return the pamt path."""
    group = root / "0009"
    meta = root / "meta"
    group.mkdir(parents=True)
    meta.mkdir(parents=True)

    # 0.paz carries every shipped payload; 1.paz is a tiny second archive so the
    # writer has a smallest-PAZ choice to make.
    paz0 = bytearray()
    paz1 = b"\0" * 16
    dir_block = bytearray()
    dir_offsets = {}
    for folder in FOLDERS:
        dir_offsets[folder] = len(dir_block)
        dir_block += _flat_name(folder)

    name_block = bytearray()
    file_records = []
    folder_records = []
    # A shared prefix record proves chained names resolve next to flat ones.
    prefix_offset = len(name_block)
    name_block += _flat_name("sword_")
    for folder in FOLDERS:
        start = len(file_records)
        for name in FILES[folder]:
            payload = f"payload of {folder}/{name}".encode("utf-8")
            offset = len(paz0)
            paz0 += payload
            paz0 += b"\0" * ((-len(paz0)) % 16)
            if name.startswith("sword_"):
                tail = name[len("sword_"):].encode("utf-8")
                name_offset = len(name_block)
                name_block += struct.pack("<IB", prefix_offset, len(tail)) + tail
            else:
                name_offset = len(name_block)
                name_block += _flat_name(name)
            file_records.append(struct.pack("<IIIIHH", name_offset, offset, len(payload), len(payload), 0, 0))
        folder_records.append(
            struct.pack("<IIII", calculate_pa_checksum(folder), dir_offsets[folder], start, len(FILES[folder]))
        )
    (group / "0.paz").write_bytes(bytes(paz0))
    (group / "1.paz").write_bytes(paz1)

    pamt = bytearray()
    pamt += struct.pack("<III", 0, 2, 0x610D3AB2)
    pamt += struct.pack("<III", 0, calculate_pa_checksum(bytes(paz0)), len(paz0))
    pamt += struct.pack("<III", 1, calculate_pa_checksum(paz1), len(paz1))
    pamt += struct.pack("<I", len(dir_block)) + dir_block
    pamt += struct.pack("<I", len(name_block)) + name_block
    pamt += struct.pack("<I", len(folder_records)) + b"".join(folder_records)
    pamt += struct.pack("<I", len(file_records)) + b"".join(file_records)
    pamt_crc = calculate_pa_checksum(bytes(pamt[12:]))
    struct.pack_into("<I", pamt, 0, pamt_crc)
    pamt_path = group / "0.pamt"
    pamt_path.write_bytes(bytes(pamt))

    papgt = bytearray(24)
    struct.pack_into("<I", papgt, 20, pamt_crc)
    struct.pack_into("<I", papgt, 4, calculate_pa_checksum(bytes(papgt[12:])))
    (meta / "0.papgt").write_bytes(bytes(papgt))
    return pamt_path


def _entries_by_path(pamt_path: Path) -> dict:
    return {entry.path.replace("\\", "/").lower(): entry for entry in parse_archive_pamt(pamt_path)}


class AddArchiveEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.pamt_path = _build_package(self.root)
        self.papgt_path = self.root / "meta" / "0.papgt"
        self.before = _entries_by_path(self.pamt_path)
        self.paz0_before = (self.root / "0009" / "0.paz").read_bytes()
        self.paz1_before = (self.root / "0009" / "1.paz").read_bytes()
        self.backup_root = self.root / "backups"
        self._backup_patch = patch("cdmw.core.archive_patching.ARCHIVE_PATCH_BACKUP_ROOT", self.backup_root)
        self._backup_patch.start()

    def tearDown(self) -> None:
        self._backup_patch.stop()
        self._temp.cleanup()

    def test_fixture_matches_the_layout_the_writer_relies_on(self) -> None:
        document = parse_pamt_document(self.pamt_path.read_bytes())
        self.assertEqual([folder.path for folder in document.folders], list(FOLDERS))
        self.assertEqual(len(document.files), 6)
        self.assertEqual(document.files[2].rel_name, "sword_0001.pac")
        self.assertEqual(document.paz_records[0][0], 0)
        self.assertEqual(document.paz_records[1], (1, calculate_pa_checksum(self.paz1_before), 16))
        _verify_crc_chain(self.papgt_path, (self.pamt_path,))

    def test_a_new_entry_lands_in_byte_order_and_reads_back(self) -> None:
        request = ArchiveAddRequest(self.pamt_path, "character/model/weapon/sword_0005.pac", b"new sword payload", 0)
        result = add_archive_entries((request,), on_log=lambda _m: None)

        after = _entries_by_path(self.pamt_path)
        self.assertEqual(set(after), set(self.before) | {"character/model/weapon/sword_0005.pac"})
        self.assertEqual(result.added_paths, ["character/model/weapon/sword_0005.pac"])
        self.assertIn("character/model/weapon/sword_0005.pac", result.changed_entries)
        added = after["character/model/weapon/sword_0005.pac"]
        # the smallest PAZ (1.paz) receives the payload, at a 16-aligned offset past its old end
        self.assertEqual(added.paz_index, 1)
        self.assertEqual(added.offset, 16)
        self.assertEqual(read_archive_entry_data(added)[0], b"new sword payload")
        # untouched entries keep their bytes and locations
        for path, entry in self.before.items():
            self.assertEqual(
                (after[path].paz_index, after[path].offset, after[path].comp_size, after[path].orig_size, after[path].flags),
                (entry.paz_index, entry.offset, entry.comp_size, entry.orig_size, entry.flags),
                path,
            )
            self.assertEqual(read_archive_entry_data(after[path])[0], read_archive_entry_data(entry)[0])
        # placement: after sword_0002, before sword_0009, and ui/icon shifted by one
        document = parse_pamt_document(self.pamt_path.read_bytes())
        names = [record.rel_name for record in document.files]
        self.assertEqual(names[2:6], ["sword_0001.pac", "sword_0002.pac", "sword_0005.pac", "sword_0009.pac"])
        self.assertEqual([(folder.start, folder.count) for folder in document.folders], [(0, 2), (2, 4), (6, 1)])
        # PAZ record for 1.paz updated as (index, checksum, size); 0.paz untouched
        paz1 = (self.root / "0009" / "1.paz").read_bytes()
        self.assertEqual(document.paz_records[1], (1, calculate_pa_checksum(paz1), len(paz1)))
        self.assertEqual(document.paz_records[0], (0, calculate_pa_checksum(self.paz0_before), len(self.paz0_before)))
        self.assertEqual((self.root / "0009" / "0.paz").read_bytes(), self.paz0_before)
        # papgt slot follows the new pamt crc
        _verify_crc_chain(self.papgt_path, (self.pamt_path,))
        # backup holds papgt, pamt and the PAZ that grew
        backed = sorted(p.name for p in result.backup_dir.iterdir())
        self.assertEqual(backed, ["0009_0.pamt", "0009_1.paz", "backup_manifest.json", "meta_0.papgt"])

    def test_first_and_last_slots_of_a_folder_and_the_last_folder(self) -> None:
        requests = (
            ArchiveAddRequest(self.pamt_path, "character/model/weapon/aaa.pac", b"first", 0),
            ArchiveAddRequest(self.pamt_path, "character/model/weapon/zzz.pac", b"last", 0),
            ArchiveAddRequest(self.pamt_path, "ui/icon/itemicon_b.dds", b"icon", 0),
        )
        add_archive_entries(requests)
        document = parse_pamt_document(self.pamt_path.read_bytes())
        names = [record.rel_name for record in document.files]
        self.assertEqual(
            names,
            ["armor_0001.pac", "armor_0002.pac", "aaa.pac", "sword_0001.pac", "sword_0002.pac", "sword_0009.pac", "zzz.pac", "itemicon_a.dds", "itemicon_b.dds"],
        )
        self.assertEqual([(folder.start, folder.count) for folder in document.folders], [(0, 2), (2, 5), (7, 2)])
        after = _entries_by_path(self.pamt_path)
        for path, payload in (("character/model/weapon/aaa.pac", b"first"), ("character/model/weapon/zzz.pac", b"last"), ("ui/icon/itemicon_b.dds", b"icon")):
            self.assertEqual(read_archive_entry_data(after[path])[0], payload)

    def test_compressed_and_encrypted_additions_read_back_through_the_normal_reader(self) -> None:
        xml = b"<?xml version=\"1.0\"?><ModelProperty>" + b"<Material name=\"m\"/>" * 40 + b"</ModelProperty>"
        requests = (
            ArchiveAddRequest(self.pamt_path, "character/model/weapon/sword_0003.pac", b"lz4 " * 200, 0x02),
            ArchiveAddRequest(self.pamt_path, "character/model/weapon/sword_0004.pac_xml", xml, 0x32),
        )
        add_archive_entries(requests)
        after = _entries_by_path(self.pamt_path)
        lz4_entry = after["character/model/weapon/sword_0003.pac"]
        self.assertEqual(lz4_entry.flags, 0x02)
        self.assertLess(lz4_entry.comp_size, lz4_entry.orig_size)
        self.assertEqual(read_archive_entry_data(lz4_entry)[0], b"lz4 " * 200)
        enc_entry = after["character/model/weapon/sword_0004.pac_xml"]
        self.assertEqual(enc_entry.flags, 0x32)
        data, _decompressed, note = read_archive_entry_data(enc_entry)
        self.assertEqual(data, xml)
        self.assertIn("ChaCha20", str(note))

    def test_a_patch_and_an_addition_share_one_rebuild_and_one_backup(self) -> None:
        existing = self.before["character/model/armor_0001.pac"]
        result = apply_archive_mutations(
            (ArchivePatchRequest(existing, b"armor v2"),),
            (ArchiveAddRequest(self.pamt_path, "character/model/armor_0003.pac", b"armor three", 0),),
        )
        after = _entries_by_path(self.pamt_path)
        self.assertEqual(read_archive_entry_data(after["character/model/armor_0001.pac"])[0], b"armor v2")
        self.assertEqual(read_archive_entry_data(after["character/model/armor_0003.pac"])[0], b"armor three")
        # the replacement stayed in its own PAZ (0), the addition went to the smallest (1)
        self.assertEqual(after["character/model/armor_0001.pac"].paz_index, 0)
        self.assertEqual(after["character/model/armor_0003.pac"].paz_index, 1)
        self.assertEqual(sorted(result.changed_paths), ["character/model/armor_0001.pac", "character/model/armor_0003.pac"])
        self.assertEqual(result.added_paths, ["character/model/armor_0003.pac"])
        backed = sorted(p.name for p in result.backup_dir.iterdir())
        self.assertEqual(backed, ["0009_0.pamt", "0009_0.paz", "0009_1.paz", "backup_manifest.json", "meta_0.papgt"])
        document = parse_pamt_document(self.pamt_path.read_bytes())
        for index in (0, 1):
            paz = (self.root / "0009" / f"{index}.paz").read_bytes()
            self.assertEqual(document.paz_records[index], (index, calculate_pa_checksum(paz), len(paz)))
        _verify_crc_chain(self.papgt_path, (self.pamt_path,))

    def test_a_plain_patch_keeps_paz_records_as_index_checksum_size(self) -> None:
        existing = self.before["character/model/armor_0001.pac"]
        patch_archive_entries((ArchivePatchRequest(existing, b"armor v2"),))
        document = parse_pamt_document(self.pamt_path.read_bytes())
        paz0 = (self.root / "0009" / "0.paz").read_bytes()
        self.assertEqual(document.paz_records[0], (0, calculate_pa_checksum(paz0), len(paz0)))
        self.assertEqual(document.paz_records[1], (1, calculate_pa_checksum(self.paz1_before), 16))

    def _assert_refused(self, request: ArchiveAddRequest, pattern: str) -> None:
        with patch("cdmw.core.archive_patching._create_backup") as create_backup:
            with self.assertRaisesRegex((ValueError, FileNotFoundError), pattern):
                add_archive_entries((request,))
        create_backup.assert_not_called()
        self.assertEqual((self.root / "0009" / "0.paz").read_bytes(), self.paz0_before)
        self.assertEqual((self.root / "0009" / "1.paz").read_bytes(), self.paz1_before)
        self.assertEqual(_entries_by_path(self.pamt_path).keys(), self.before.keys())

    def test_refusals_happen_before_backup_or_write(self) -> None:
        self._assert_refused(ArchiveAddRequest(self.pamt_path, "character/model/armor_0001.pac", b"x", 0), "already exists")
        self._assert_refused(ArchiveAddRequest(self.pamt_path, "character/model/helmet/h.pac", b"x", 0), "not in 0009/0.pamt")
        self._assert_refused(ArchiveAddRequest(self.pamt_path, "loose.pac", b"x", 0), "folder-qualified")
        self._assert_refused(ArchiveAddRequest(self.pamt_path, "character/model/../x.pac", b"x", 0), "folder-qualified")
        self._assert_refused(ArchiveAddRequest(self.pamt_path, "character/model/ice.pac", b"x", 0x10), "encryption type 1")
        self._assert_refused(ArchiveAddRequest(self.pamt_path, "character/model/zlib.pac", b"x", 0x03), "compression type 3")
        self._assert_refused(ArchiveAddRequest(self.pamt_path, "character/model/" + "n" * 260 + ".pac", b"x", 0), "255 bytes")
        self._assert_refused(ArchiveAddRequest(self.root / "0010" / "0.pamt", "character/model/x.pac", b"x", 0), "Could not find archive metadata")

    def test_the_same_path_twice_in_one_request_is_refused(self) -> None:
        requests = (
            ArchiveAddRequest(self.pamt_path, "character/model/dup.pac", b"1", 0),
            ArchiveAddRequest(self.pamt_path, "Character/Model/DUP.pac", b"2", 0),
        )
        with patch("cdmw.core.archive_patching._create_backup") as create_backup:
            with self.assertRaisesRegex(ValueError, "requested twice"):
                add_archive_entries(requests)
        create_backup.assert_not_called()

    def test_empty_and_wrongly_typed_requests_are_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "No archive additions"):
            add_archive_entries(())
        with self.assertRaisesRegex(ValueError, "No archive modifications"):
            apply_archive_mutations((), ())
        with self.assertRaises(TypeError):
            apply_archive_mutations((), ("character/model/x.pac",))  # type: ignore[arg-type]

    def test_a_write_failure_restores_the_backup_including_the_grown_paz(self) -> None:
        request = ArchiveAddRequest(self.pamt_path, "character/model/weapon/sword_0005.pac", b"new sword payload", 0)
        pamt_before = self.pamt_path.read_bytes()
        papgt_before = self.papgt_path.read_bytes()
        with patch("cdmw.core.archive_patching._write_bytes_preserve_timestamps", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                add_archive_entries((request,))
        self.assertEqual(self.pamt_path.read_bytes(), pamt_before)
        self.assertEqual(self.papgt_path.read_bytes(), papgt_before)
        self.assertEqual((self.root / "0009" / "1.paz").read_bytes(), self.paz1_before)
        _verify_crc_chain(self.papgt_path, (self.pamt_path,))

    def test_from_template_copies_group_and_flags(self) -> None:
        template = self.before["character/model/weapon/sword_0001.pac"]
        request = ArchiveAddRequest.from_template(template, "character\\model\\weapon\\sword_0007.pac", b"seven")
        self.assertEqual(request.pamt_path, Path(template.pamt_path))
        self.assertEqual(request.path, "character/model/weapon/sword_0007.pac")
        self.assertEqual(request.flags, template.flags)
        self.assertEqual(request.basename, "sword_0007.pac")
        add_archive_entries((request,))
        self.assertEqual(read_archive_entry_data(_entries_by_path(self.pamt_path)["character/model/weapon/sword_0007.pac"])[0], b"seven")


class PamtDocumentTests(unittest.TestCase):
    def test_serialize_reproduces_the_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            pamt_path = _build_package(Path(temp))
            data = pamt_path.read_bytes()
            self.assertEqual(parse_pamt_document(data).serialize(), data)

    def test_off_layout_tables_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            pamt_path = _build_package(Path(temp))
            data = bytearray(pamt_path.read_bytes())
            document = parse_pamt_document(bytes(data))
            # a gap between folder ranges is refused
            broken = parse_pamt_document(bytes(data))
            broken.folders[1].start += 1
            with self.assertRaisesRegex(ValueError, "leaves a gap"):
                parse_pamt_document(broken.serialize())
            # trailing bytes are refused
            with self.assertRaisesRegex(ValueError, "trailing"):
                parse_pamt_document(bytes(data) + b"\0")
            # a file record pointing at a PAZ that does not exist is refused
            document.files[0].paz_index = 7
            with self.assertRaisesRegex(ValueError, "PAZ index 7"):
                parse_pamt_document(document.serialize())


if __name__ == "__main__":
    unittest.main()
