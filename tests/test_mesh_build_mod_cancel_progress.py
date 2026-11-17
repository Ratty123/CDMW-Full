"""Build Mod's progress dialog after Cancel: it stays closed while the worker winds down."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from cdmw.ui.mesh_editor.tab_direct_output import MeshEditorDirectOutputMixin

_APP = QApplication.instance() or QApplication([])


class _Tab(QWidget, MeshEditorDirectOutputMixin):
    pass


def test_progress_reported_after_cancel_does_not_show_the_dialog_again() -> None:
    tab = _Tab()
    tab.show()
    # As _start_mesh_direct_output_worker makes it.
    progress = QProgressDialog("Preparing mesh-only output...", "Cancel", 0, 100, tab)
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(250)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    tab.standalone_output_progress = progress
    tab.standalone_output_request_id = 3
    try:
        tab._handle_mesh_direct_output_progress(3, 1, "Preparing mesh-only output...")
        time.sleep(0.3)
        tab._handle_mesh_direct_output_progress(3, 10, "Rebuilding parts...")
        _APP.processEvents()
        assert progress.isVisible()
        progress.cancel()  # what the dialog's Cancel button does
        _APP.processEvents()
        assert not progress.isVisible()
        # The worker reports again before it reaches its next cancellation check.
        tab._handle_mesh_direct_output_progress(3, 40, "Writing the mod...")
        _APP.processEvents()
        assert not progress.isVisible()
        assert progress.wasCanceled()
    finally:
        tab.deleteLater()
        _APP.processEvents()
