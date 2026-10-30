"""Supported exports and reconciliation of removed saved manager choices."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.core.recolor_variants import default_recolor_output_profiles

from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_MANAGER_PROFILES, mod_package_export_options_for_manager,
    normalize_mod_package_manager_profile,
)
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
from cdmw.services.new_item_service import LOOSE_EXPORT_PROFILES
from cdmw.ui.new_item.state import MANAGERS
from cdmw.ui.shell.problem_report_catalog import MOD_MANAGERS
from tools.placement_studio.packaging import MANAGER_PROFILES


def test_supported_profiles():
    assert MOD_PACKAGE_MANAGER_PROFILES == ("dmm", "cdumm", "field_json")
    for manager in MOD_PACKAGE_MANAGER_PROFILES:
        assert mod_package_export_options_for_manager(manager).manager_targets == (manager,)
    assert set(LOOSE_EXPORT_PROFILES) == set(MANAGER_PROFILES) == set(MANAGERS) == {"CDUMM", "DMM"}
    assert {profile.profile_id for profile in default_recolor_output_profiles()} == {"dmm", "cdumm"}
    assert "JMM" not in MOD_MANAGERS


@pytest.mark.parametrize("saved", ["jmm", "JMM", "jmm_json", "json", "retired_manager"])
def test_removed_saved_profiles_use_the_existing_default(saved):
    assert normalize_mod_package_manager_profile(saved) == "dmm"
    assert mod_package_export_options_for_manager(saved) == mod_package_export_options_for_manager("dmm")


def test_build_mod_reconciles_removed_saved_choice(tmp_path):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = MeshModExportDialog(
        parent, title="Test", description="", output_parent=str(tmp_path),
        output_choice="jmm_loose", manager_profile="jmm",
    )
    try:
        assert [dialog.manager.itemData(i)[0] for i in range(dialog.manager.count())] == [
            "dmm_loose", "cdumm_loose",
        ]
        assert dialog.manager.currentData()[2] == "dmm"
        assert dialog.build_button.isEnabled()
        assert dialog.output_path() == tmp_path / "Test-dmm"
        dialog.manager.setCurrentIndex(1)
        assert dialog.manager.currentData()[2] == "cdumm"
        assert dialog.output_path() == tmp_path / "Test-cdumm"
    finally:
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()
