"""Two items in one mod folder: the second planned on the tables the first wrote.

A loose mod carries whole tables, so two of them cannot both be enabled: whichever the
manager mounts last owns the table and the other item's row is not there. Planning the
second item against the folder rather than against the archives puts both rows in one
table, which is the only arrangement every manager can load.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.iteminfo_row import parse_iteminfo_row  # noqa: E402
from cdmw.core.structured_binary_editor import parse_pabgh_table  # noqa: E402
from cdmw.domain.new_item.spec import NewItemSpec  # noqa: E402
from cdmw.services.new_item_mod_base import (  # noqa: E402
    describe_mod_folder,
    mod_folder_payloads,
    read_entry_over_mod_folder,
)
from cdmw.services.new_item_service import NewItemService  # noqa: E402
from test_new_item_service import TEMPLATE, _read, build_package, synthetic_files  # noqa: E402

BIN = "gamedata/binary__/client/bin"


class ModBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.pamt = build_package(self.root / "game", synthetic_files())
        from cdmw.core.archive_format import parse_archive_pamt

        self.entries = tuple(parse_archive_pamt(self.pamt))
        self.service = NewItemService()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _rows(self, folder: Path) -> dict:
        payloads = mod_folder_payloads(folder)
        body = payloads[f"{BIN}/iteminfo.pabgb"].read_bytes()
        head = payloads[f"{BIN}/iteminfo.pabgh"].read_bytes()
        table = parse_pabgh_table(head, payload=body)
        rows = {}
        for span in table.row_spans(len(body)):
            if span[0].row_id >= 1990000:
                rows[span[0].row_id] = parse_iteminfo_row(body[span[1]:span[2]]).string_key
        return rows

    def test_the_second_item_is_planned_on_the_first_one_s_tables(self) -> None:
        folder = self.root / "mod"

        first = self.service.plan(
            self.service.allocate(
                NewItemSpec(template_key=TEMPLATE, internal_name="Item_One", display_names={"eng": "One"}),
                self.service.build_snapshot(self.entries, read_entry=_read),
            ),
            self.service.build_snapshot(self.entries, read_entry=_read),
        )
        self.service.export_loose(first, folder, manager="JMM")
        self.assertEqual(self._rows(folder), {first.spec.item_key: "Item_One"})

        # what the studio does when the folder already holds a mod: read the tables from
        # there, so the next row is appended to those
        payloads = mod_folder_payloads(folder)
        self.assertIn(f"{BIN}/iteminfo.pabgb", payloads)
        self.assertIn("already holds a mod", describe_mod_folder(folder))
        over_mod = self.service.build_snapshot(
            self.entries, read_entry=read_entry_over_mod_folder(_read, payloads)
        )
        self.assertIn(first.spec.item_key, over_mod.rows, "the first item is in the tables the second sees")

        second = self.service.plan(
            self.service.allocate(
                NewItemSpec(template_key=TEMPLATE, internal_name="Item_Two", display_names={"eng": "Two"}),
                over_mod,
            ),
            over_mod,
        )
        self.assertNotEqual(second.spec.item_key, first.spec.item_key, "and it takes the next key")
        self.service.export_loose(second, folder, manager="JMM")

        self.assertEqual(
            self._rows(folder),
            {first.spec.item_key: "Item_One", second.spec.item_key: "Item_Two"},
            "one folder, one table, both items",
        )

    def test_without_the_folder_the_second_item_overwrites_the_first(self) -> None:
        """The failure this exists to prevent: planned against the archives, the second
        item's table is the shipped one with only its own row, so exporting it into the
        same folder drops the first item."""

        folder = self.root / "plain"
        snapshot = self.service.build_snapshot(self.entries, read_entry=_read)
        first = self.service.plan(
            self.service.allocate(NewItemSpec(template_key=TEMPLATE, internal_name="Item_One", display_names={"eng": "One"}), snapshot),
            snapshot,
        )
        self.service.export_loose(first, folder, manager="JMM")
        second = self.service.plan(
            self.service.allocate(NewItemSpec(template_key=TEMPLATE, internal_name="Item_Two", display_names={"eng": "Two"}), snapshot),
            snapshot,
        )
        self.service.export_loose(second, folder, manager="JMM")
        self.assertEqual(list(self._rows(folder).values()), ["Item_Two"], "the first item is gone")

    def test_the_studio_plans_on_the_folder_when_it_is_pointed_at_one(self) -> None:
        """What the Output step does: pointed at a folder that already holds a mod, the
        controller plans the next item on its tables, and pointed away it goes back to the
        archives."""

        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.new_item.controller import NewItemStudioController

        QApplication.instance() or QApplication([])
        folder = self.root / "studio_mod"
        snapshot = self.service.build_snapshot(self.entries, read_entry=_read)
        first = self.service.plan(
            self.service.allocate(NewItemSpec(template_key=TEMPLATE, internal_name="Item_One", display_names={"eng": "One"}), snapshot),
            snapshot,
        )
        self.service.export_loose(first, folder, manager="JMM")

        controller = NewItemStudioController(read_entry=_read, synchronous=True)
        controller.snapshot = snapshot
        self.assertEqual(controller.planning_snapshot(), snapshot, "no folder, no change")

        found = controller.set_mod_base(folder)
        self.assertIn("already holds a mod", found)
        over = controller.planning_snapshot()
        self.assertIsNotNone(over)
        self.assertIn(first.spec.item_key, over.rows, "the item in the folder is in the tables the next plan sees")
        self.assertIs(controller.planning_snapshot(), over, "and the reading is kept while the folder is unchanged")

        self.assertEqual(controller.set_mod_base(None), "")
        self.assertEqual(controller.planning_snapshot(), snapshot, "pointed away, the archives again")
        self.assertEqual(controller.set_mod_base(self.root / "nothing_here"), "", "a folder with no mod is not a base")

    def test_the_dmm_layout_is_an_archive_group(self) -> None:
        """DMM routes loose files but not whole tables: its own mount summary counts mods
        as JSON, browser/file, standalone-overlay or group-replace, and a six-megabyte
        item table belongs to the last two. So the DMM export writes the group it mounts,
        the same shape the workbench installs into the game."""

        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.archive_format import parse_archive_pamt
        from cdmw.core.papgt_format import parse_papgt

        folder = self.root / "dmm"
        snapshot = self.service.build_snapshot(self.entries, read_entry=_read)
        plan = self.service.plan(
            self.service.allocate(NewItemSpec(template_key=TEMPLATE, internal_name="Item_One", display_names={"eng": "One"}), snapshot),
            snapshot,
        )
        result = self.service.export_loose(plan, folder, manager="DMM")
        self.assertEqual(result.manager, "DMM")
        written = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
        self.assertIn("manifest.json", written)
        self.assertIn("modinfo.json", written)
        group = next(name.split("/")[0] for name in written if name.endswith("/0.pamt"))
        self.assertIn(f"{group}/0.paz", written)
        self.assertIn("meta/0.papgt", written)

        # the group is a real archive: every patched path reads back out of it
        listed = {str(entry.path): entry for entry in parse_archive_pamt(folder / group / "0.pamt")}
        self.assertEqual(sorted(listed), sorted(result.payload_paths))
        for request in plan.patches:
            self.assertEqual(read_archive_entry_data(listed[str(request.entry.path)])[0], request.payload_data)

        # and the mount list it ships names the group, counting itself
        mounted = (folder / "meta" / "0.papgt").read_bytes()
        names = [item.name for item in parse_papgt(mounted)]
        self.assertEqual(names[0], group)
        self.assertEqual(mounted[8], len(names), "the header counts the directories it lists")

    def test_a_folder_with_nothing_in_it_says_nothing(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(mod_folder_payloads(empty), {})
        self.assertEqual(describe_mod_folder(empty), "")
        self.assertEqual(describe_mod_folder(self.root / "missing"), "")


if __name__ == "__main__":
    unittest.main()
