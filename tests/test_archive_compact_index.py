from __future__ import annotations

import unittest
from pathlib import Path

from cdmw.core.archive_compact_index import ArchiveRowIndex, archive_path_key
from cdmw.core.archive_filtering import (
    build_archive_entry_basename_index,
    build_archive_entry_extension_index,
    build_archive_entry_path_index,
    build_archive_entry_role_index,
)
from cdmw.models import ArchiveEntry


def _entry(path: str, *, offset: int = 0) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("0000/0.pamt"),
        paz_file=Path("0000/0.paz"),
        offset=offset,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )


class ArchiveCompactIndexTests(unittest.TestCase):
    def test_exact_path_singleton_is_stored_compactly(self) -> None:
        entries = [_entry("character/model/a.pac")]
        index = build_archive_entry_path_index(entries)

        self.assertIsInstance(index, ArchiveRowIndex)
        self.assertEqual(index.row_ids_for_key("character/model/a.pac"), (0,))
        self.assertEqual(index.raw_rows_by_key["character/model/a.pac"], 0)
        self.assertIs(index.entry_for_singleton_key("character/model/a.pac"), entries[0])
        self.assertEqual(index.singleton_count, 1)
        self.assertEqual(index.multi_count, 0)

    def test_duplicate_path_stores_multiple_row_ids(self) -> None:
        entries = [
            _entry("character/model/a.pac", offset=0),
            _entry("character/model/a.pac", offset=4),
        ]
        index = build_archive_entry_path_index(entries)

        self.assertEqual(index.row_ids_for_key("character/model/a.pac"), (0, 1))
        self.assertEqual(tuple(index.get("character/model/a.pac", ())), tuple(entries))
        self.assertEqual(index.singleton_count, 0)
        self.assertEqual(index.multi_count, 1)

    def test_get_returns_archive_entry_values(self) -> None:
        entries = [_entry("character/model/a.pac")]
        index = build_archive_entry_path_index(entries)

        self.assertEqual(index.get("missing", ()), ())
        self.assertEqual(tuple(index.get("character/model/a.pac", ())), (entries[0],))
        self.assertEqual(index["character/model/a.pac"], (entries[0],))

    def test_items_values_and_materialize_all_remain_compatible(self) -> None:
        entries = [_entry("character/model/a.pac"), _entry("character/texture/a.dds")]
        index = build_archive_entry_extension_index(entries)

        self.assertEqual(len(index), 2)
        self.assertIn(".pac", index)
        self.assertEqual(dict(index.items())[".pac"], (entries[0],))
        self.assertEqual(tuple(index.values())[0], (entries[0],))
        materialized = index.materialize_all()
        self.assertEqual(materialized[".dds"], [entries[1]])

    def test_basename_index_preserves_nested_priority_order(self) -> None:
        entries = [
            _entry("character/cd_phm_00_hel_00_0363.pac"),
            _entry("character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0363.pac"),
            _entry("character/model/cd_phm_00_hel_00_0363.pac"),
        ]
        index = build_archive_entry_basename_index(entries)
        matches = index["cd_phm_00_hel_00_0363.pac"]

        self.assertEqual(
            matches[0].path,
            "character/model/1_pc/1_phm/armor/13_hel/cd_phm_00_hel_00_0363.pac",
        )
        self.assertEqual(matches[-1].path, "character/cd_phm_00_hel_00_0363.pac")

    def test_role_index_keeps_texture_alias(self) -> None:
        entries = [_entry("character/texture/a.dds")]
        index = build_archive_entry_role_index(entries)

        self.assertEqual(index.row_ids_for_key("image"), (0,))
        self.assertEqual(index.row_ids_for_key("texture"), (0,))

    def test_normalized_path_reuses_already_normalized_string(self) -> None:
        path = "character/model/a.pac"

        self.assertIs(archive_path_key(path), path)
        self.assertEqual(archive_path_key("Character\\Model\\A.PAC"), "character/model/a.pac")
        self.assertEqual(archive_path_key(" character/model/a.pac "), "character/model/a.pac")


if __name__ == "__main__":
    unittest.main()
