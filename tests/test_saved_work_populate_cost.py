"""Drafts & Mods fills its table without measuring the date column once per cell.

The "Saved on" column sizes to its contents. While it did so during the fill,
every cell written to a table that already had rows made Qt measure that column
again over every row: 92 to 99 ms for 60 rows offscreen, and a refresh fills the
table up to three times (the list, then the files found, then their checks).
Drafts & Mods held the window thread 298 ms cold and 149 ms warm
(saved_work_page.py _populate) in the 2026-11-17 review.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView, QStyledItemDelegate  # noqa: E402

from cdmw.services.mesh_saved_work_service import SavedWorkRow  # noqa: E402
from cdmw.ui.mesh_editor.saved_work_page import SavedWorkPage  # noqa: E402


class _CountingDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.measured = 0

    def sizeHint(self, option, index):  # noqa: N802 - Qt API
        self.measured += 1
        return super().sizeHint(option, index)


def _rows(root, count: int) -> tuple[SavedWorkRow, ...]:
    return tuple(SavedWorkRow(
        "draft", f"row-{index}", f"cd_phm_00_ub_00_0374 edit {index}", 1794900000.0 + index,
        f"character/model/1_pc/1_phm/armor/9_upperbody/cd_phm_00_ub_00_{index:04d}.pac", "0009", 1,
        root / f"row-{index}", None, "ab" * 32, "cd" * 32, True) for index in range(count))


def test_refilling_the_table_measures_the_date_column_once_not_per_cell(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    page = SavedWorkPage(draft_root=tmp_path / "drafts")
    try:
        page.show()
        deadline = time.monotonic() + 5
        while page._token and time.monotonic() < deadline and page.empty_label.text() == "Reading saved work...":
            app.processEvents()
            time.sleep(0.01)
        counter = _CountingDelegate(page.table)
        page.table.setItemDelegateForColumn(0, counter)
        rows = _rows(tmp_path, 60)
        page._rows = rows
        page._populate()  # a table that is empty fills cheaply
        app.processEvents()
        counter.measured = 0
        page._populate()  # the second and third fills of a refresh replace every cell
        app.processEvents()
        assert counter.measured <= 4 * len(rows), f"the date column was measured {counter.measured} times"
        header = page.table.horizontalHeader()
        assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
        assert page.table.rowCount() == len(rows)
    finally:
        page.close()
        page.deleteLater()
