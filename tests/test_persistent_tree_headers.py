import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QTreeWidget

from cdmw.ui.widgets import (
    flush_pending_tree_column_saves,
    make_tree_columns_persistent,
    persistent_tree_column_order_key,
    persistent_tree_column_widths_key,
    restore_persistent_tree_column_order,
    restore_persistent_tree_column_widths,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _settings(path: Path) -> QSettings:
    return QSettings(str(path), QSettings.Format.IniFormat)


def _tree(labels: tuple[str, ...] = ("A", "B", "C")) -> QTreeWidget:
    tree = QTreeWidget()
    tree.setHeaderLabels(list(labels))
    return tree


class PersistentTreeHeaderTests(unittest.TestCase):
    def test_width_restore_still_works(self) -> None:
        _app()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings(Path(temp_dir) / "settings.ini")
            settings.setValue(persistent_tree_column_widths_key("tree"), "140,160,180")
            tree = _tree()

            self.assertTrue(restore_persistent_tree_column_widths(tree, settings, "tree"))

            self.assertEqual(140, tree.header().sectionSize(0))
            self.assertEqual(160, tree.header().sectionSize(1))
            self.assertEqual(180, tree.header().sectionSize(2))

    def test_moved_column_order_saves_and_restores(self) -> None:
        _app()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.ini"
            settings = _settings(settings_path)
            tree = _tree()
            make_tree_columns_persistent(tree, settings, "tree", restore_later=False)
            tree.header().moveSection(2, 0)
            flush_pending_tree_column_saves()
            settings.sync()

            restored_settings = _settings(settings_path)
            restored = _tree()
            make_tree_columns_persistent(restored, restored_settings, "tree", restore_later=False)

            self.assertEqual(2, restored.header().logicalIndex(0))
            self.assertEqual(0, restored.header().logicalIndex(1))
            self.assertEqual(1, restored.header().logicalIndex(2))

    def test_can_persist_widths_without_movable_order(self) -> None:
        _app()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.ini"
            settings = _settings(settings_path)
            tree = _tree()
            make_tree_columns_persistent(
                tree,
                settings,
                "tree",
                restore_later=False,
                persist_order=False,
                sections_movable=False,
            )
            tree.header().resizeSection(1, 210)
            flush_pending_tree_column_saves()
            settings.sync()

            self.assertFalse(tree.header().sectionsMovable())
            self.assertEqual("", str(settings.value(persistent_tree_column_order_key("tree"), "")))

            restored_settings = _settings(settings_path)
            restored = _tree()
            make_tree_columns_persistent(
                restored,
                restored_settings,
                "tree",
                restore_later=False,
                persist_order=False,
                sections_movable=False,
            )

            self.assertFalse(restored.header().sectionsMovable())
            self.assertEqual(210, restored.header().sectionSize(1))
            self.assertEqual(0, restored.header().logicalIndex(0))
            self.assertEqual(1, restored.header().logicalIndex(1))
            self.assertEqual(2, restored.header().logicalIndex(2))

    def test_stale_saved_layouts_are_ignored_when_column_count_changes(self) -> None:
        _app()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings(Path(temp_dir) / "settings.ini")
            settings.setValue(persistent_tree_column_widths_key("tree"), "120,130,140")
            settings.setValue(persistent_tree_column_order_key("tree"), "2,0,1")
            tree = _tree(("A", "B"))

            self.assertFalse(restore_persistent_tree_column_widths(tree, settings, "tree"))
            self.assertFalse(restore_persistent_tree_column_order(tree, settings, "tree"))
            self.assertEqual(0, tree.header().logicalIndex(0))
            self.assertEqual(1, tree.header().logicalIndex(1))

    def test_a_burst_of_resizes_costs_one_disk_flush(self) -> None:
        """A drag, or a language change re-laying out headers, must not flush per section.

        `sectionResized` fires once per pointer sample while a divider is
        dragged, and once per header a translated label re-laid out. Saving from
        each one flushed `QSettings` to disk: fifteen synchronous writes during
        one interface-language change, which measured 224-431 ms of its 600 ms.
        """
        _app()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.ini"
            settings = _settings(settings_path)
            syncs = []
            original_sync = settings.sync

            def counting_sync() -> None:
                syncs.append(1)
                original_sync()

            settings.sync = counting_sync
            tree = _tree()
            make_tree_columns_persistent(tree, settings, "tree", restore_later=False)

            for width in range(120, 200, 4):
                tree.header().resizeSection(1, width)

            self.assertEqual(
                [],
                syncs,
                "A burst of section resizes flushed to disk before settling.",
            )

            flush_pending_tree_column_saves()

            self.assertEqual(
                1,
                len(syncs),
                f"Settling a burst cost {len(syncs)} flushes, expected exactly one.",
            )
            self.assertEqual(
                "196",
                str(settings.value(persistent_tree_column_widths_key("tree"), "")).split(",")[1],
                "The settled layout is not the one that was written.",
            )

    def test_flush_is_a_no_op_when_nothing_is_pending(self) -> None:
        _app()
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = _settings(Path(temp_dir) / "settings.ini")
            syncs = []
            original_sync = settings.sync

            def counting_sync() -> None:
                syncs.append(1)
                original_sync()

            settings.sync = counting_sync
            tree = _tree()
            make_tree_columns_persistent(tree, settings, "tree", restore_later=False)

            flush_pending_tree_column_saves()
            flush_pending_tree_column_saves()

            self.assertEqual([], syncs, "Flushing with nothing pending still wrote to disk.")


if __name__ == "__main__":
    unittest.main()
