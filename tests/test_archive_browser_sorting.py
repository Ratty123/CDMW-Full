import unittest
from pathlib import Path

from cdmw.core.archive import (
    archive_browser_entry_sort_key,
    build_archive_entry_path_index,
    build_archive_tree_index,
    sort_archive_entries_for_browser,
)
from cdmw.models import ArchiveEntry


def _entry(
    path: str,
    *,
    size: int = 1,
    comp_size: int | None = None,
    package: str = "0000",
    offset: int = 0,
    flags: int = 0,
) -> ArchiveEntry:
    pamt = Path("C:/archives") / package / "0.pamt"
    return ArchiveEntry(
        path=path,
        pamt_path=pamt,
        paz_file=pamt.with_name("0.paz"),
        offset=offset,
        comp_size=size if comp_size is None else comp_size,
        orig_size=size,
        flags=flags,
        paz_index=0,
    )


class ArchiveBrowserSortingTests(unittest.TestCase):
    def test_name_sort_uses_case_insensitive_natural_order(self) -> None:
        entries = [
            _entry("folder/Z10.dds"),
            _entry("folder/a10.dds"),
            _entry("folder/A2.dds"),
        ]

        ascending = sort_archive_entries_for_browser(entries, 0, "asc")
        descending = sort_archive_entries_for_browser(entries, 0, "desc")

        self.assertEqual([entry.basename for entry in ascending], ["A2.dds", "a10.dds", "Z10.dds"])
        self.assertEqual([entry.basename for entry in descending], ["Z10.dds", "a10.dds", "A2.dds"])

    def test_size_sort_uses_original_byte_size(self) -> None:
        entries = [
            _entry("folder/medium.pac", size=512),
            _entry("folder/small.pac", size=12),
            _entry("folder/large.pac", size=4096, comp_size=900),
        ]

        ascending = sort_archive_entries_for_browser(entries, 4, "asc")
        descending = sort_archive_entries_for_browser(entries, 4, "desc")

        self.assertEqual([entry.basename for entry in ascending], ["small.pac", "medium.pac", "large.pac"])
        self.assertEqual([entry.basename for entry in descending], ["large.pac", "medium.pac", "small.pac"])

    def test_all_archive_columns_have_deterministic_sort_keys(self) -> None:
        original = _entry("character/model/cd_weapon_king_halberd.pac", size=500, package="0009", offset=10)
        modded = _entry("character/model/cd_weapon_king_halberd.pac", size=700, package="dmmsa", offset=20)
        unrelated = _entry("ui/texture/icon_002.dds", size=300, package="0001", offset=30, flags=2)
        entries = [original, modded, unrelated]
        path_index = build_archive_entry_path_index(entries)
        exact_names = {"cd_weapon_king_halberd": "Vow of the Dead King"}
        display_names = {"icon_002": "Inventory Icon 2"}

        for column in range(9):
            sorted_once = sort_archive_entries_for_browser(
                entries,
                column,
                "asc",
                item_display_names=display_names,
                item_exact_display_names=exact_names,
                archive_entries_by_normalized_path=path_index,
            )
            sorted_twice = sort_archive_entries_for_browser(
                entries,
                column,
                "asc",
                item_display_names=display_names,
                item_exact_display_names=exact_names,
                archive_entries_by_normalized_path=path_index,
            )

            self.assertCountEqual([id(entry) for entry in sorted_once], [id(entry) for entry in entries])
            self.assertEqual(
                [(entry.path, entry.package_label, entry.offset) for entry in sorted_once],
                [(entry.path, entry.package_label, entry.offset) for entry in sorted_twice],
            )
            self.assertTrue(
                all(
                    archive_browser_entry_sort_key(
                        entry,
                        column,
                        item_display_names=display_names,
                        item_exact_display_names=exact_names,
                        archive_entries_by_normalized_path=path_index,
                    )
                    for entry in entries
                )
            )

    def test_tree_index_can_preserve_sorted_file_order_inside_folders(self) -> None:
        entries = [
            _entry("folder/b.pac"),
            _entry("folder/a.pac"),
            _entry("folder/c.pac"),
        ]

        _folders, default_direct_files, _folder_indexes, _stats = build_archive_tree_index(entries)
        _folders, preserved_direct_files, _folder_indexes, _stats = build_archive_tree_index(
            entries,
            preserve_direct_file_order=True,
        )

        self.assertEqual(default_direct_files[("folder",)], [1, 0, 2])
        self.assertEqual(preserved_direct_files[("folder",)], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
