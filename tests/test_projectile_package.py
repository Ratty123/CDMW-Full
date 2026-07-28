"""Gates for `.paprojdesc`, the projectile package description.

Behaviour tests over synthesised bytes, plus a corpus gate that checks the one shipped
file against the XML it was compiled from -- which is the only external ground truth this
format has.
"""

from __future__ import annotations

import struct
import unittest

import pytest

from cdmw.core.projectile_package import (
    PACKAGE_DESCRIPTION_PATH,
    ProjectilePackage,
    ProjectilePackageDescription,
    ProjectilePackageError,
    encode_projectile_package,
    parse_projectile_package,
    rebuild_is_exact,
)


def _s(text: str) -> bytes:
    raw = text.encode("ascii")
    return bytes((len(raw) + 1,)) + raw + b"\x00"


def _build(strings, packages, slots) -> bytes:
    out = bytearray(struct.pack("<H", len(strings)))
    for text in strings:
        out += _s(text)
    out += struct.pack("<II", len(packages), len(slots))
    for modules, flag, first, name in packages:
        out += struct.pack("<BBHH", modules, flag, first, name)
    for slot in slots:
        out += struct.pack("<H", slot)
    return bytes(out)


_SAMPLE = _build(
    ["PkgA", "modone", "modtwo", "PkgB"],
    [(2, 1, 0, 0), (1, 1, 2, 3)],
    [1, 2, 1],
)


class ParseTests(unittest.TestCase):
    def test_packages_resolve_their_names_and_modules(self) -> None:
        description = parse_projectile_package(_SAMPLE)

        self.assertEqual([p.name for p in description.packages], ["PkgA", "PkgB"])
        self.assertEqual(description.packages[0].modules, ("modone", "modtwo"))
        self.assertEqual(description.packages[1].modules, ("modone",))

    def test_the_module_list_is_deduplicated_in_first_seen_order(self) -> None:
        description = parse_projectile_package(_SAMPLE)

        self.assertEqual(description.module_names(), ("modone", "modtwo"))

    def test_a_package_reads_its_slice_of_the_shared_module_list(self) -> None:
        """`first_module` is a slot in one flat list, not a per-package list."""

        description = parse_projectile_package(_SAMPLE)

        self.assertEqual(description.packages[1].modules, ("modone",))


class RoundTripTests(unittest.TestCase):
    def test_a_parse_and_a_write_reproduce_the_bytes(self) -> None:
        self.assertTrue(rebuild_is_exact(_SAMPLE))

    def test_the_string_table_order_is_preserved_not_regenerated(self) -> None:
        """The shipped file interleaves package and module names; order is not derivable."""

        description = parse_projectile_package(_SAMPLE)

        self.assertEqual(description.strings, ("PkgA", "modone", "modtwo", "PkgB"))
        self.assertEqual(encode_projectile_package(description), _SAMPLE)

    def test_writing_a_name_outside_the_table_is_refused(self) -> None:
        description = ProjectilePackageDescription(
            strings=("PkgA",), packages=(ProjectilePackage(name="PkgA", modules=("gone",)),)
        )

        with self.assertRaises(ProjectilePackageError):
            encode_projectile_package(description)


class RefusalTests(unittest.TestCase):
    """A malformed file is refused, never half-read."""

    def test_a_string_without_its_terminator_is_refused(self) -> None:
        broken = bytearray(_SAMPLE)
        broken[2 + 1 + 4] = 0x41  # overwrite the NUL after "PkgA"

        with self.assertRaises(ProjectilePackageError):
            parse_projectile_package(bytes(broken))

    def test_trailing_bytes_are_refused(self) -> None:
        with self.assertRaises(ProjectilePackageError):
            parse_projectile_package(_SAMPLE + b"\x00\x00")

    def test_a_module_index_outside_the_table_is_refused(self) -> None:
        broken = _build(["PkgA", "modone"], [(1, 1, 0, 0)], [9])

        with self.assertRaises(ProjectilePackageError):
            parse_projectile_package(bytes(broken))

    def test_a_truncated_file_is_refused(self) -> None:
        with self.assertRaises(ProjectilePackageError):
            parse_projectile_package(_SAMPLE[:10])

    def test_an_empty_buffer_is_refused(self) -> None:
        with self.assertRaises(ProjectilePackageError):
            parse_projectile_package(b"")


@pytest.mark.real_game
class VanillaDescriptionTests(unittest.TestCase):
    """The shipped file, against the XML it was compiled from."""

    def _archive(self, wanted: str) -> bytes:
        from cdmw.core.archive_extraction import read_archive_entry_data
        from tools.placement_studio import corpus

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            if corpus.normalize_game_path(entry.path) == wanted:
                data, _decompressed, _note = read_archive_entry_data(entry)
                return data
        self.skipTest(f"{wanted} is not in the archives")
        raise AssertionError  # unreachable; keeps type checkers quiet

    def test_the_shipped_description_rebuilds_byte_for_byte(self) -> None:
        self.assertTrue(rebuild_is_exact(self._archive(PACKAGE_DESCRIPTION_PATH)))

    def test_it_decodes_to_what_its_xml_says(self) -> None:
        """The XML is the only ground truth this format has, so it is the gate."""

        import re

        binary = parse_projectile_package(self._archive(PACKAGE_DESCRIPTION_PATH))
        xml = self._archive(
            "actionchart/xml/description/projectilepackagedescription.xml"
        ).decode("utf-8-sig", "replace")

        # `<PackageName>` then its `<ModuleInfo FileName="..."/>` children, up to `</>`.
        expected = []
        for block in re.split(r"</>", xml):
            name = re.search(r"<([A-Za-z_]\w*Package)>", block)
            if not name:
                continue
            modules = re.findall(r'<ModuleInfo\s+FileName="([^"]+)"', block)
            expected.append((name.group(1).casefold(), [m.casefold() for m in modules]))

        self.assertTrue(expected, "no packages found in the XML")
        self.assertEqual(
            [(p.name.casefold(), [m.casefold() for m in p.modules]) for p in binary.packages],
            expected,
        )


if __name__ == "__main__":
    unittest.main()
