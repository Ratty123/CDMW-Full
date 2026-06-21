from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidget

from cdmw.ui.research.tree_helpers import (
    auto_fit_persisted_research_tree_columns,
    auto_fit_research_tree_columns,
    research_tree_storage_key,
)


_APP = QApplication.instance() or QApplication([])


def test_research_tree_storage_key_prefixes_research_namespace() -> None:
    assert research_tree_storage_key("archive_picker") == "research/archive_picker"


def test_auto_fit_research_tree_columns_expands_stretch_column() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(3)
    tree.resize(520, 200)
    tree.header().resizeSection(0, 80)
    tree.header().resizeSection(1, 90)
    tree.header().resizeSection(2, 100)

    auto_fit_research_tree_columns(tree, stretch_column=0, min_widths={0: 180, 1: 110, 2: 120})

    assert tree.header().sectionSize(1) >= 110
    assert tree.header().sectionSize(2) >= 120
    assert tree.header().sectionSize(0) >= 180


def test_auto_fit_research_tree_columns_respects_saved_widths() -> None:
    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.resize(220, 160)
    tree.header().resizeSection(0, 1000)
    tree.header().resizeSection(1, 1000)

    auto_fit_research_tree_columns(tree, stretch_column=0, min_widths={0: 300, 1: 300}, has_saved_columns=True)

    assert tree.header().sectionSize(0) == 1000
    assert tree.header().sectionSize(1) == 1000


def test_auto_fit_persisted_research_tree_columns_checks_storage_namespace() -> None:
    class Settings:
        def value(self, key: str, default: object = None) -> object:
            if key == "research/archive_picker/column_widths":
                return [1000, 1000]
            return default

    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.resize(220, 160)
    tree.header().resizeSection(0, 1000)
    tree.header().resizeSection(1, 1000)

    auto_fit_persisted_research_tree_columns(
        tree,
        Settings(),
        "archive_picker",
        stretch_column=0,
        min_widths={0: 300, 1: 300},
    )

    assert tree.header().sectionSize(0) == 1000
    assert tree.header().sectionSize(1) == 1000
