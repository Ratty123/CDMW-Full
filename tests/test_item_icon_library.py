from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from cdmw.core.item_icon import (
    import_edited_item_icon_source,
    load_item_icon_library_index,
    scan_item_icon_library,
    save_item_icon_library_index,
    update_item_icon_library_record_metadata,
)


class ItemIconLibraryTests(unittest.TestCase):
    def test_scan_persists_metadata_and_invalidates_changed_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "icons"
            source_root.mkdir()
            icon = source_root / "itemicon_prefab_cd_test.png"
            Image.new("RGBA", (32, 64), (255, 0, 0, 255)).save(icon)
            index_path = root / "item_icon_library" / "icon_index.json"

            first = scan_item_icon_library([source_root], index_path=index_path)
            save_item_icon_library_index(index_path, roots=[source_root], records=first)
            update_item_icon_library_record_metadata(
                index_path,
                icon,
                tags=("weapon", "draft"),
                notes="kept across rescans",
                favorite=True,
            )

            Image.new("RGBA", (128, 32), (0, 255, 0, 255)).save(icon)
            second = scan_item_icon_library([source_root], index_path=index_path)

            self.assertEqual(1, len(second))
            self.assertEqual((128, 32), (second[0].width, second[0].height))
            self.assertEqual(("weapon", "draft"), second[0].tags)
            self.assertEqual("kept across rescans", second[0].notes)
            self.assertTrue(second[0].favorite)

    def test_scan_filters_unsupported_files_and_indexes_edited_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "icons"
            source_root.mkdir()
            edited_root = root / "item_icon_library" / "edited"
            Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(source_root / "source.png")
            (source_root / "ignore.txt").write_text("not an image", encoding="utf-8")
            exported = root / "export.png"
            Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(exported)

            copied = import_edited_item_icon_source(exported, edited_root)
            records = scan_item_icon_library([source_root], edited_root=edited_root)
            loaded_names = {record.path.name for record in records}
            edited = [record for record in records if record.path == copied]

            self.assertEqual({"source.png", copied.name}, loaded_names)
            self.assertEqual(1, len(edited))
            self.assertEqual("edited", edited[0].source_kind)

    def test_load_corrupt_index_returns_empty_v1_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "icon_index.json"
            index_path.write_text("{broken", encoding="utf-8")

            loaded = load_item_icon_library_index(index_path)

            self.assertEqual(1, loaded["version"])
            self.assertEqual([], loaded["roots"])
            self.assertEqual({}, loaded["records"])


if __name__ == "__main__":
    unittest.main()
