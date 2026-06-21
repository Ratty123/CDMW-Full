from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.item_icons.state import (
    is_probable_item_icon_entry,
    path_list_to_settings,
    safe_icon_library_component,
    safe_relative_target_path,
    settings_path_list,
)


class ItemIconStateTests(unittest.TestCase):
    def test_settings_path_list_round_trips_json_paths(self) -> None:
        paths = [Path("icons"), Path("more/icons")]

        encoded = path_list_to_settings(paths)

        self.assertEqual(paths, settings_path_list(encoded))
        self.assertEqual([], settings_path_list("{bad json"))

    def test_safe_icon_library_component_and_relative_target_path(self) -> None:
        self.assertEqual("Warrior-Icon", safe_icon_library_component("ui/item/Warrior Icon.dds"))
        self.assertEqual(Path("ui") / "item" / "icon.dds", safe_relative_target_path("ui/item/icon.dds"))
        with self.assertRaises(ValueError):
            safe_relative_target_path("../escape.dds")

    def test_probable_item_icon_entry_uses_path_and_extension(self) -> None:
        self.assertTrue(is_probable_item_icon_entry(SimpleNamespace(path="ui/item/itemicon_001.dds", extension=".dds")))
        self.assertTrue(is_probable_item_icon_entry(SimpleNamespace(path="assets/ui/custom/icon_001.dds", extension=".dds")))
        self.assertFalse(is_probable_item_icon_entry(SimpleNamespace(path="texture/itemicon_001.png", extension=".png")))


if __name__ == "__main__":
    unittest.main()
