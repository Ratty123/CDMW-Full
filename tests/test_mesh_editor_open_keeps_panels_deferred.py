"""Defect 2 (the freeze on opening a set): showing a session synced the compare combo,
and reading it built every hidden legacy panel on the UI thread (2.5 s cold)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import shiboken6
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab_actions import MeshEditorActionsMixin
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace

_APP = QApplication.instance() or QApplication([])


def test_syncing_the_compare_combo_does_not_build_deferred_panels() -> None:
    workspace = MeshEditorWorkspace(defer_legacy_panels=True)
    try:
        assert workspace._legacy_panels_deferred
        tab = SimpleNamespace(standalone_workspace=workspace)
        MeshEditorActionsMixin._sync_standalone_compare_combo(tab)
        assert workspace._legacy_panels_deferred, "the sync built the legacy panels"
        workspace._ensure_legacy_panels()
        workspace.compare_mode_combo.setCurrentText("Source")
        MeshEditorActionsMixin._sync_standalone_compare_combo(tab)
        assert workspace.compare_mode_combo.currentText() == "Edited"
    finally:
        shiboken6.delete(workspace)
        _APP.processEvents()


def test_a_combo_built_later_starts_on_edited() -> None:
    workspace = MeshEditorWorkspace(defer_legacy_panels=True)
    try:
        workspace._ensure_legacy_panels()
        assert workspace.compare_mode_combo.currentText() == "Edited"
    finally:
        shiboken6.delete(workspace)
        _APP.processEvents()
