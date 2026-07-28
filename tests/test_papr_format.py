"""Gates for the `.papr` constraint-rig reader, writer, and editor."""

from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.papr_format import (  # noqa: E402
    PAPR_VERSION,
    PAR_MAGIC,
    ConstraintEntry,
    PaprDocument,
    PaprFormatError,
    PaprHeader,
    describe,
    encode_papr,
    find_weight_sites,
    parse_header,
    parse_papr,
    rebuild_is_exact,
    rename_bone,
    scale_weights,
    set_transform,
    set_weights,
)

XFORM = (1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.25, 0.5, -0.5)


def _driver_block(*pairs: tuple[str, float]) -> bytes:
    """A block shaped like a real one: an opener, a driver array, a terminator."""

    out = bytearray(b"\x05\x03\x00\x03\x04\x00")
    out.append(len(pairs))
    for name, weight in pairs:
        raw = name.encode("ascii")
        out += struct.pack("<H", len(raw)) + raw + struct.pack("<f", weight)
    out += b"\x07\x05\x00"
    return bytes(out)


def _doc(*entries: ConstraintEntry, record_count: int = 0) -> PaprDocument:
    return PaprDocument(
        header=PaprHeader(
            version=PAPR_VERSION,
            payload_bytes=0,
            entry_count=len(entries),
            record_count=record_count,
        ),
        entries=tuple(entries),
    )


def _entry(name, parent, *, kind=0, block=b"", transform=None, counters=(0, 1)):
    return ConstraintEntry(
        name=name, parent=parent, counters=counters,
        transform=transform, kind=kind, block=block,
    )


class RoundTripTests(unittest.TestCase):
    def test_a_rig_round_trips(self) -> None:
        doc = _doc(
            _entry("Bip01 Spine", "Bip01 Pelvis"),
            _entry("B_Jiggle_M_Root", "Bip01 Spine", kind=3,
                   block=_driver_block(("Bip01 Spine", 30.0), ("Bip01 Pelvis", 50.0))),
            record_count=6,
        )
        data = encode_papr(doc)
        again = parse_papr(data)
        self.assertEqual(again.entries, doc.entries)
        self.assertTrue(rebuild_is_exact(data))

    def test_a_transform_frame_survives(self) -> None:
        doc = _doc(_entry("P_L_Calf", "Bip01 L Calf", transform=XFORM))
        again = parse_papr(encode_papr(doc))
        self.assertEqual(again.entries[0].transform, XFORM)

    def test_the_header_is_recomputed(self) -> None:
        doc = _doc(_entry("A", "B"), _entry("C", "D"))
        header = parse_papr(encode_papr(doc)).header
        self.assertEqual(header.entry_count, 2)
        self.assertEqual(header.payload_bytes, len(encode_papr(doc)) - 0x1C)

    def test_record_count_is_carried_not_invented(self) -> None:
        doc = _doc(_entry("A", "B", kind=3, block=_driver_block(("C", 50.0))), record_count=42)
        self.assertEqual(parse_papr(encode_papr(doc)).header.record_count, 42)


class HeaderTests(unittest.TestCase):
    def test_a_foreign_container_is_refused(self) -> None:
        with self.assertRaises(PaprFormatError):
            parse_header(b"NOPE" + bytes(64))

    def test_a_wrong_payload_length_is_refused(self) -> None:
        data = bytearray(encode_papr(_doc(_entry("A", "B"))))
        struct.pack_into("<I", data, 0x18, 999999)
        with self.assertRaises(PaprFormatError):
            parse_header(bytes(data))

    def test_a_lying_entry_count_is_refused(self) -> None:
        """The chain has to tile the file, or the parse is not trusted."""

        data = bytearray(encode_papr(_doc(_entry("A", "B"))))
        struct.pack_into("<I", data, 0x1C, 9)
        with self.assertRaises(PaprFormatError):
            parse_papr(bytes(data))

    def test_the_container_header_is_written_back(self) -> None:
        data = encode_papr(_doc(_entry("A", "B")))
        self.assertEqual(data[:4], PAR_MAGIC)
        self.assertEqual((data[4], data[5]), PAPR_VERSION)
        self.assertEqual(data[6:16], bytes(range(10)))


class WeightTests(unittest.TestCase):
    def _rig(self):
        return _doc(
            _entry("Root", "Bip01"),
            _entry("Hair", "Root", kind=3,
                   block=_driver_block(("Bip01 Spine", 30.0), ("Bip01 Neck", 50.0))),
            record_count=6,
        )

    def test_weights_are_found_with_their_bone_and_entry(self) -> None:
        sites = find_weight_sites(self._rig())
        self.assertEqual([(s.entry_index, s.bone, s.value) for s in sites],
                         [(1, "Bip01 Spine", 30.0), (1, "Bip01 Neck", 50.0)])

    def test_a_denormal_is_not_mistaken_for_a_weight(self) -> None:
        rig = _doc(_entry("A", "B", kind=3, block=_driver_block(("Bip01", 3.58e-43))))
        self.assertEqual(find_weight_sites(rig), ())

    def test_zero_is_not_treated_as_an_editable_weight(self) -> None:
        rig = _doc(_entry("A", "B", kind=3, block=_driver_block(("Bip01", 0.0))))
        self.assertEqual(find_weight_sites(rig), ())

    def test_an_edit_changes_only_the_named_weight(self) -> None:
        rig = self._rig()
        sites = find_weight_sites(rig)
        key = (sites[0].entry_index, sites[0].block_offset)
        edited = set_weights(rig, {key: 10.0}, expected={key: 30.0})
        self.assertEqual([s.value for s in find_weight_sites(edited)], [10.0, 50.0])
        self.assertEqual(len(encode_papr(edited)), len(encode_papr(rig)))

    def test_scaling_rounds_so_sites_stay_findable(self) -> None:
        """Halving 15 to 7.5 would leave a value the locator no longer offers."""

        rig = _doc(_entry("A", "B", kind=3, block=_driver_block(("Bip01", 15.0))))
        once = scale_weights(rig, find_weight_sites(rig), 0.5)
        self.assertEqual([s.value for s in find_weight_sites(once)], [8.0])
        twice = scale_weights(once, find_weight_sites(once), 0.5)
        self.assertEqual([s.value for s in find_weight_sites(twice)], [4.0])

    def test_scaling_clamps_to_the_percentage_range(self) -> None:
        rig = _doc(_entry("A", "B", kind=3, block=_driver_block(("Bip01", 80.0))))
        out = scale_weights(rig, find_weight_sites(rig), 10.0)
        self.assertEqual(find_weight_sites(out)[0].value, 100.0)

    def test_a_wrong_expected_value_refuses_to_write(self) -> None:
        rig = self._rig()
        site = find_weight_sites(rig)[0]
        key = (site.entry_index, site.block_offset)
        with self.assertRaises(PaprFormatError):
            set_weights(rig, {key: 10.0}, expected={key: 99.0})

    def test_an_out_of_range_weight_is_refused(self) -> None:
        rig = self._rig()
        site = find_weight_sites(rig)[0]
        key = (site.entry_index, site.block_offset)
        with self.assertRaises(PaprFormatError):
            set_weights(rig, {key: 500.0}, expected={key: 30.0})


class StructuralEditTests(unittest.TestCase):
    def test_a_bone_can_be_renamed_to_a_longer_name(self) -> None:
        doc = _doc(_entry("Hair", "Bip01 Neck"), _entry("Tip", "Hair"))
        renamed = rename_bone(doc, "Hair", "Hair_Renamed_Much_Longer")
        data = encode_papr(renamed)
        again = parse_papr(data)
        self.assertEqual(again.entries[0].name, "Hair_Renamed_Much_Longer")
        self.assertEqual(again.entries[1].parent, "Hair_Renamed_Much_Longer")
        self.assertEqual(again.header.payload_bytes, len(data) - 0x1C)

    def test_renaming_an_absent_bone_raises(self) -> None:
        with self.assertRaises(PaprFormatError):
            rename_bone(_doc(_entry("A", "B")), "nope", "x")

    def test_a_transform_can_be_moved(self) -> None:
        doc = _doc(_entry("P", "B", transform=XFORM))
        moved = set_transform(doc, 0, XFORM[:7] + (1.0, 2.0, 3.0))
        self.assertEqual(parse_papr(encode_papr(moved)).entries[0].transform[7:], (1.0, 2.0, 3.0))

    def test_a_transform_cannot_be_added_where_there_is_none(self) -> None:
        with self.assertRaises(PaprFormatError):
            set_transform(_doc(_entry("P", "B")), 0, XFORM)

    def test_a_wrong_length_transform_is_refused(self) -> None:
        with self.assertRaises(PaprFormatError):
            set_transform(_doc(_entry("P", "B", transform=XFORM)), 0, (1.0, 2.0))

    def test_a_name_outside_the_supported_characters_is_refused(self) -> None:
        with self.assertRaises(PaprFormatError):
            encode_papr(_doc(_entry("BadéName", "B")))

    def test_a_block_without_a_kind_is_refused(self) -> None:
        with self.assertRaises(PaprFormatError):
            encode_papr(_doc(_entry("A", "B", kind=0, block=b"\x07\x05\x00")))


@pytest.mark.real_game
class VanillaRigTests(unittest.TestCase):
    """The shipped rigs: parse, rebuild byte for byte, and hold their invariants."""

    def _rigs(self):
        from tools.placement_studio import corpus
        from cdmw.core.archive_extraction import read_archive_entry_data

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            path = corpus.normalize_game_path(entry.path)
            if path.endswith(".papr"):
                data, _decompressed, _note = read_archive_entry_data(entry)
                yield path, data

    def test_every_rig_that_parses_rebuilds_byte_for_byte(self) -> None:
        parsed = rejected = 0
        bones = weights = frames = 0
        for path, data in self._rigs():
            try:
                document = parse_papr(data, name=path)
            except PaprFormatError:
                rejected += 1
                continue
            parsed += 1
            bones += len(document.entries)
            frames += sum(1 for e in document.entries if e.transform is not None)
            weights += len(find_weight_sites(document))
            self.assertEqual(encode_papr(document), data, path)
        if not parsed and not rejected:
            self.skipTest("no .papr entries in the archives")
        self.assertGreaterEqual(parsed, 19, "expected at least 19 rigs to parse")
        self.assertGreater(bones, 2000)
        self.assertGreater(frames, 500)
        self.assertGreater(weights, 1000)

    def test_a_rig_that_does_not_tile_is_rejected_not_guessed(self) -> None:
        """One shipped rig finds 236 entry starts against a declared 237."""

        rejected = [
            path for path, data in self._rigs()
            if not rebuild_is_exact(data, name=path)
        ]
        self.assertLessEqual(len(rejected), 1, f"unexpected rejections: {rejected}")

    def test_located_weights_are_whole_percentages(self) -> None:
        total = 0
        for path, data in self._rigs():
            try:
                document = parse_papr(data, name=path)
            except PaprFormatError:
                continue
            for site in find_weight_sites(document):
                total += 1
                self.assertEqual(site.value, round(site.value), f"{path} {site.bone}")
                self.assertTrue(1 <= site.value <= 100, f"{path} {site.bone} {site.value}")
        if not total:
            self.skipTest("no .papr entries in the archives")

    def test_describe_summarises_a_rig(self) -> None:
        for path, data in self._rigs():
            try:
                document = parse_papr(data, name=path)
            except PaprFormatError:
                continue
            self.assertIn("influence weights", describe(document))
            return
        self.skipTest("no .papr entries in the archives")
