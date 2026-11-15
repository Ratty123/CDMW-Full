"""B1: the native fault after Build Mod comes from the dialog's Python-made layer items.

MeshModExportDialog builds its "Keep layers underneath" rows with
``QListWidgetItem(name, self.layers)``: 37 items made in Python. Once the dialog
is gone, deleting the Mesh Editor tab (with its native session) faults with an
access violation in about half the runs. Measured with the tab deleted right after
each test (tests/test_mesh_rust_editor_selection.py's ``_dispose`` only posts the
delete, so today every tab is deleted at once in conftest's pytest_unconfigure), at
0359504f6:

- the first Build Mod test: 6 of 8 runs fault; a test with no Build Mod: 0 of 4;
- the dialog built and deleted, no Build Mod: 2 to 3 of 8; with no layer rows: 0 of 4;
  with no parent: still 2 of 4, so the parent is not involved;
- keeping the dialog (never deleteLater) in the real flow: 4 of 4; deleting it at
  once: 3 of 4; clearing the list first, or dropping the check state or the data: 5-6 of 8;
- the rows made by the list (``addItem(name)``, then ``item(row)``): 0 of 8, and the
  whole file 0 of 8 both with that delete and as it runs today (was 3 to 5 of 8).

astra's tip only looked clean: the mods merge removed two buttons from the tab, which
moved the heap; putting them back brings the fault back. A crash cannot be a strict
xfail without flaking, so this test states the change instead. It builds the real
dialog without a tab: with the native session in the same process, the unfixed
dialog is the thing that faults.
"""

from __future__ import annotations

import os

import pytest
import shiboken6

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.services.mesh_layer_visibility import CLOTHING_LAYERS  # noqa: E402
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog  # noqa: E402


def test_build_mod_dialog_layer_rows_are_made_by_the_list() -> None:
    QApplication.instance() or QApplication([])
    dialog = MeshModExportDialog(None, title="t", description="d", output_parent="", output_choice="",
                                 manager_profile="dmm")
    try:
        rows = [dialog.layers.item(row) for row in range(dialog.layers.count())]
        assert len(rows) == len(CLOTHING_LAYERS)
        made_in_python = [item.text() for item in rows if shiboken6.createdByPython(item)]
    finally:
        shiboken6.delete(dialog)
    assert not made_in_python
