from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from cdmw.models import ArchiveEntry
from tools.extract_crimson_shader_corpus import (
    collect_dds_references,
    resolve_dds_entries,
    select_shader_text_entries,
)


def _entry(path: str, *, package: str = "0009", offset: int = 0) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("C:/game") / package / "0.pamt",
        paz_file=Path("C:/game") / package / "0.paz",
        offset=offset,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class ShaderCorpusExtractorTests(unittest.TestCase):
    def test_selects_shader_sidecars_without_dds_bulk(self) -> None:
        entries = [
            _entry("character/modelproperty/body.pac_xml"),
            _entry("character/texture/body.dds"),
            _entry("misc/config.xml"),
        ]

        selected = select_shader_text_entries(entries)

        self.assertEqual(["character/modelproperty/body.pac_xml", "misc/config.xml"], [entry.path for entry in selected])

    def test_collects_dds_refs_from_package_prefixed_extract_path(self) -> None:
        sidecar = _entry("character/modelproperty/body.pac_xml", package="0009")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_path = root / "0009" / "character" / "modelproperty" / "body.pac_xml"
            out_path.parent.mkdir(parents=True)
            out_path.write_text(
                '<MaterialParameterTexture _name="_baseColorTexture">'
                '<ResourceReferencePath_ITexture _path="character/texture/body.dds"/>'
                "</MaterialParameterTexture>",
                encoding="utf-8",
            )

            refs = collect_dds_references(root, [sidecar])

        self.assertEqual(1, len(refs))
        self.assertEqual("character/texture/body.dds", refs[0]["dds_reference"])

    def test_resolves_exact_dds_paths_before_basename_fallback(self) -> None:
        refs = [{"sidecar_path": "a.pac_xml", "dds_reference": "character/texture/body.dds", "dds_basename": "body.dds"}]
        exact = _entry("character/texture/body.dds", offset=10)
        other = _entry("object/texture/body.dds", offset=20)

        resolved, rows, stats = resolve_dds_entries([exact, other], refs, limit=4)

        self.assertEqual([exact], resolved)
        self.assertEqual("exact", rows[0]["resolution"])
        self.assertEqual(1, stats["exact"])


if __name__ == "__main__":
    unittest.main()
