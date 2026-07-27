"""Gates for the `.papr` constraint-rig reader and in-place weight editor."""

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
    PaprFormatError,
    WeightSite,
    describe,
    find_weight_sites,
    parse_header,
    scale_weights,
    set_weights,
)


def _rig(*pairs: tuple[str, float], entry_count: int = 1) -> bytes:
    """A buffer shaped like a rig: real header, then name/weight pairs."""

    body = bytearray()
    for name, weight in pairs:
        raw = name.encode("ascii")
        body += struct.pack("<H", len(raw)) + raw + struct.pack("<f", weight)
    head = bytearray(PAR_MAGIC + bytes(PAPR_VERSION) + bytes(range(10)))
    head += struct.pack("<I", 0)
    head += struct.pack("<I", 14)
    head += struct.pack("<I", len(body) + 8)  # payload counted from 0x1C
    head += struct.pack("<I", entry_count)
    head += struct.pack("<I", 0)
    return bytes(head + body)


class HeaderTests(unittest.TestCase):
    def test_a_valid_header_parses(self) -> None:
        header = parse_header(_rig(("Bip01 Spine", 50.0), entry_count=3))
        self.assertEqual(header.version, PAPR_VERSION)
        self.assertEqual(header.entry_count, 3)

    def test_a_foreign_container_is_refused(self) -> None:
        with self.assertRaises(PaprFormatError):
            parse_header(b"NOPE" + bytes(64))

    def test_a_wrong_payload_length_is_refused(self) -> None:
        data = bytearray(_rig(("Bip01", 50.0)))
        struct.pack_into("<I", data, 0x18, 999999)
        with self.assertRaises(PaprFormatError):
            parse_header(bytes(data))


class LocateTests(unittest.TestCase):
    def test_weights_are_found_with_their_bone(self) -> None:
        sites = find_weight_sites(_rig(("Bip01 Spine", 30.0), ("Bip01 Pelvis", 50.0)))
        self.assertEqual([(s.bone, s.value) for s in sites],
                         [("Bip01 Spine", 30.0), ("Bip01 Pelvis", 50.0)])

    def test_a_denormal_is_not_mistaken_for_a_weight(self) -> None:
        """Four bytes of a neighbouring integer read as a float round to zero."""

        site = WeightSite(offset=0, bone="Bip01", value=3.587324068671532e-43)
        self.assertFalse(site.confident)
        self.assertEqual(find_weight_sites(_rig(("Bip01", 3.587324068671532e-43))), ())

    def test_zero_is_not_treated_as_an_editable_weight(self) -> None:
        self.assertEqual(find_weight_sites(_rig(("Bip01", 0.0))), ())

    def test_every_candidate_is_available_when_asked_for(self) -> None:
        sites = find_weight_sites(_rig(("Bip01", 0.0)), confident_only=False)
        self.assertEqual(len(sites), 1)
        self.assertFalse(sites[0].confident)


class EditTests(unittest.TestCase):
    def test_an_edit_keeps_the_length_and_changes_only_the_weight(self) -> None:
        data = _rig(("Bip01 Spine", 50.0), ("Bip01 Pelvis", 50.0))
        sites = find_weight_sites(data)
        out = set_weights(data, {sites[0].offset: 25.0}, expected={sites[0].offset: 50.0})
        self.assertEqual(len(out), len(data))
        self.assertEqual([s.value for s in find_weight_sites(out)], [25.0, 50.0])

    def test_a_no_op_edit_returns_the_source_bytes(self) -> None:
        data = _rig(("Bip01", 50.0))
        self.assertEqual(scale_weights(data, find_weight_sites(data), 1.0), data)

    def test_scaling_clamps_to_the_percentage_range(self) -> None:
        data = _rig(("Bip01", 80.0))
        out = scale_weights(data, find_weight_sites(data), 10.0)
        self.assertEqual(find_weight_sites(out)[0].value, 100.0)

    def test_a_wrong_expected_value_refuses_to_write(self) -> None:
        data = _rig(("Bip01", 50.0))
        offset = find_weight_sites(data)[0].offset
        with self.assertRaises(PaprFormatError):
            set_weights(data, {offset: 10.0}, expected={offset: 99.0})

    def test_a_missing_expected_value_refuses_to_write(self) -> None:
        data = _rig(("Bip01", 50.0))
        offset = find_weight_sites(data)[0].offset
        with self.assertRaises(PaprFormatError):
            set_weights(data, {offset: 10.0}, expected={})

    def test_an_out_of_range_weight_is_refused(self) -> None:
        data = _rig(("Bip01", 50.0))
        offset = find_weight_sites(data)[0].offset
        with self.assertRaises(PaprFormatError):
            set_weights(data, {offset: 500.0}, expected={offset: 50.0})

    def test_an_offset_outside_the_file_is_refused(self) -> None:
        data = _rig(("Bip01", 50.0))
        with self.assertRaises(PaprFormatError):
            set_weights(data, {len(data): 10.0})


@pytest.mark.real_game
class VanillaRigTests(unittest.TestCase):
    """Read the shipped rigs and prove a no-op edit is byte-identical on all of them."""

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

    def test_every_shipped_rig_parses_and_survives_a_no_op_edit(self) -> None:
        seen = 0
        weights = 0
        for path, data in self._rigs():
            seen += 1
            parse_header(data, name=path)
            sites = find_weight_sites(data)
            weights += len(sites)
            self.assertEqual(scale_weights(data, sites, 1.0), data, path)
        if not seen:
            self.skipTest("no .papr entries in the archives")
        self.assertGreater(weights, 1000, "expected the rigs to carry many influence weights")

    def test_located_weights_are_whole_percentages(self) -> None:
        """What separates a real weight from four bytes that happen to parse."""

        total = 0
        for path, data in self._rigs():
            for site in find_weight_sites(data):
                total += 1
                self.assertEqual(site.value, round(site.value), f"{path} {site.bone}")
                self.assertTrue(1 <= site.value <= 100, f"{path} {site.bone} {site.value}")
        if not total:
            self.skipTest("no .papr entries in the archives")

    def test_describe_summarises_a_rig(self) -> None:
        for path, data in self._rigs():
            self.assertIn("influence weights", describe(data, name=path))
            return
        self.skipTest("no .papr entries in the archives")
