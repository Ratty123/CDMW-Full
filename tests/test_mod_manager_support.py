"""Supported exports and reconciliation of removed saved manager choices."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.core.recolor_variants import default_recolor_output_profiles

from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_EXPORT_PROFILES, MOD_PACKAGE_MANAGER_PROFILES, mod_package_export_options_for_manager,
    normalize_mod_package_manager_profile,
)
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog
from cdmw.services.new_item_service import LOOSE_EXPORT_PROFILES
from cdmw.ui.new_item.state import MANAGERS
from cdmw.ui.shell.problem_report_catalog import MOD_MANAGERS
from tools.placement_studio.packaging import MANAGER_PROFILES


def test_supported_profiles():
    # Existing CDUMM and Field-JSON packages stay readable; export UIs offer DMM only.
    assert MOD_PACKAGE_MANAGER_PROFILES == ("dmm", "cdumm", "field_json")
    assert MOD_PACKAGE_EXPORT_PROFILES == ("dmm",)
    for manager in MOD_PACKAGE_MANAGER_PROFILES:
        assert mod_package_export_options_for_manager(manager).manager_targets == (manager,)
    # Package writers keep both layouts; Create New Item and Placement offer DMM only.
    assert set(LOOSE_EXPORT_PROFILES) == set(MANAGER_PROFILES) == {"CDUMM", "DMM"}
    assert MANAGERS == ("DMM",)
    from tools.placement_studio.window_editing import PACKAGE_MANAGERS
    assert PACKAGE_MANAGERS == ("DMM",)
    assert {profile.profile_id for profile in default_recolor_output_profiles()} == {"dmm"}
    assert "JMM" not in MOD_MANAGERS


@pytest.mark.parametrize("saved", ["jmm", "JMM", "jmm_json", "json", "retired_manager"])
def test_removed_saved_profiles_use_the_existing_default(saved):
    assert normalize_mod_package_manager_profile(saved) == "dmm"
    assert mod_package_export_options_for_manager(saved) == mod_package_export_options_for_manager("dmm")


@pytest.mark.parametrize("choice,profile", [("jmm_loose", "jmm"), ("cdumm_loose", "cdumm")])
def test_build_mod_reconciles_removed_saved_choice(tmp_path, choice, profile):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = MeshModExportDialog(
        parent, title="Test", description="", output_parent=str(tmp_path),
        output_choice=choice, manager_profile=profile,
    )
    try:
        assert [dialog.manager.itemData(i)[0] for i in range(dialog.manager.count())] == ["dmm_loose"]
        assert dialog.manager.currentData()[2] == "dmm"
        assert dialog.build_button.isEnabled()
        assert dialog.output_path() == tmp_path / "Test-dmm"
    finally:
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()
