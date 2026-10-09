"""Gates for the UI icon registry (`ui/xml/texture/cd_item_icon.xml`) writer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.item_icon_registry import IconRegistryError, add_icon_texture, icon_filename_for, parse_icon_registry, registered_icon_names  # noqa: E402

LINE = b'<Texture Name="%s"\tFilename="UI/texture/icon/%s.dds" Type="Image" GetRect="0,0,256,256"/>'


def registry(*names: str, crlf: bool = True, bom: bool = True) -> bytes:
    nl = b"\r\n" if crlf else b"\n"
    body = nl.join(LINE % (n.encode(), n.encode()) for n in names) + nl + nl
    return (b"\xef\xbb\xbf" if bom else b"") + b"<!-- icons -->" + nl + body


class IconRegistryTests(unittest.TestCase):
    def test_names_and_append_shaped_like_the_template(self) -> None:
        data = registry("itemicon_empty", "ItemIcon_Prefab_cd_phm_01_sword_0109")
        self.assertEqual(registered_icon_names(data), ("itemicon_empty", "ItemIcon_Prefab_cd_phm_01_sword_0109"))
        grown = add_icon_texture(data, "ItemIcon_Prefab_cd_phm_01_sword_9109", like="ItemIcon_Prefab_CD_PHM_01_Sword_0109")
        self.assertEqual(registered_icon_names(grown)[-1], "ItemIcon_Prefab_cd_phm_01_sword_9109")
        self.assertTrue(grown.startswith(b"\xef\xbb\xbf<!-- icons -->\r\n"), "BOM and head kept")
        self.assertTrue(grown.endswith(b'<Texture Name="ItemIcon_Prefab_cd_phm_01_sword_9109"\tFilename="UI/texture/icon/ItemIcon_Prefab_cd_phm_01_sword_9109.dds" Type="Image" GetRect="0,0,256,256"/>\r\n\r\n'), grown[-200:])
        self.assertEqual(len(grown), len(data) + len(LINE % (b"ItemIcon_Prefab_cd_phm_01_sword_9109", b"ItemIcon_Prefab_cd_phm_01_sword_9109")) + 2)
        self.assertEqual(icon_filename_for("X"), "UI/texture/icon/X.dds")
        # LF files keep LF
        lf = add_icon_texture(registry("a", "b", crlf=False, bom=False), "c", like="b")
        self.assertNotIn(b"\r", lf)
        self.assertEqual(registered_icon_names(lf), ("a", "b", "c"))

    def test_refusals(self) -> None:
        data = registry("itemicon_empty", "ItemIcon_Prefab_cd_phm_01_sword_0109")
        with self.assertRaisesRegex(IconRegistryError, "already registered"):
            add_icon_texture(data, "itemicon_prefab_CD_PHM_01_SWORD_0109", like="itemicon_empty")
        with self.assertRaisesRegex(IconRegistryError, "no entry named"):
            add_icon_texture(data, "New", like="nope")
        with self.assertRaisesRegex(IconRegistryError, "plain identifier"):
            add_icon_texture(data, 'bad"name', like="itemicon_empty")
        with self.assertRaisesRegex(IconRegistryError, "no <Texture>"):
            add_icon_texture(b"not xml", "New", like="x")


def test_parser_preserves_opaque_content_and_ignores_commented_out_textures():
    comment = b'<!-- <Texture Name="Fake" Filename="fake.dds"/> -->'
    unknown = b'<FutureSetting Keep="yes"/>'
    actual = b"<Texture Filename='UI/a.dds' Name='Real' Type='Image' Extra='keep > value'/>"
    data = b'\xef\xbb\xbf' + comment + b'\r\n' + actual + b'\r\n' + unknown
    parsed = parse_icon_registry(data)
    assert [(row.name, row.filename, row.raw) for row in parsed.textures] == [('Real', 'UI/a.dds', actual)]
    assert parsed.remainder == b'\xef\xbb\xbf' + comment + b'\r\n\r\n' + unknown
    grown = add_icon_texture(data, 'New', like='REAL')
    assert grown.startswith(data)
    assert registered_icon_names(grown) == ('Real', 'New')
    assert b"Extra='keep > value'" in parse_icon_registry(grown).textures[-1].raw


@pytest.mark.parametrize('extra', [LINE % (b'A', b'A'), LINE % (b'a', b'other')])
def test_duplicate_names_refuse_even_when_identical(extra):
    with pytest.raises(IconRegistryError, match='duplicate icon name'):
        parse_icon_registry(registry('A') + extra)


@pytest.mark.parametrize('data', [b'<Texture Name="a"/>', b'<Texture Name="" Filename="a.dds"/>',
                                 b'<Texture Name="a" Filename="a.dds">/></Texture>',
                                 b'<Texture Name="a" Filename="a.dds"><Other/></Texture>',
                                 b'<Root><Texture Name="a" Filename="a.dds"/></Root>',
                                 b'<Texture Name="a" Filename="a.dds" broken/>',
                                 b'<Texture Name="\xff" Filename="a.dds"/>',
                                 b'<!DOCTYPE x [<!ENTITY a "x">]><Texture Name="&a;" Filename="a.dds"/>'])
def test_unverified_flat_icon_grammar_refuses(data):
    with pytest.raises(IconRegistryError):
        parse_icon_registry(data)


@pytest.mark.real_game
class VanillaIconRegistryTests(unittest.TestCase):
    def test_the_shipped_registry_names_the_swords_icon(self) -> None:
        from cdmw.core.archive_extraction import read_archive_entry_data
        from tools.placement_studio import corpus

        if not corpus.game_root().is_dir():
            self.skipTest("needs the installed game")
        data = None
        for _package, entry in corpus._iter_archive_entries(corpus.game_root()):
            if corpus.normalize_game_path(entry.path) == "ui/xml/texture/cd_item_icon.xml":
                data = read_archive_entry_data(entry)[0]
                break
        if data is None:
            self.skipTest("registry not found")
        names = registered_icon_names(data)
        self.assertGreater(len(names), 8000)
        lower = {n.lower() for n in names}
        self.assertIn("itemicon_prefab_cd_phm_01_sword_0109", lower)
        probe = "ItemIcon_Prefab_cdmw_gate_probe"
        if probe.lower() not in lower:
            grown = add_icon_texture(data, probe, like="ItemIcon_Prefab_cd_phm_01_sword_0109")
            self.assertEqual(len(registered_icon_names(grown)), len(names) + 1)


if __name__ == "__main__":
    unittest.main()
