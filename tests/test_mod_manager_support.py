"""Current manager profiles and the visible compatibility warning."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_MANAGER_PROFILES, mod_package_export_options_for_manager,
    normalize_mod_package_manager_profile,
)
from cdmw.ui.mesh_editor.mod_export_dialog import MeshModExportDialog


def test_supported_profiles_and_unknown_saved_profile():
    assert MOD_PACKAGE_MANAGER_PROFILES == ("dmm", "jmm", "cdumm", "field_json")
    assert normalize_mod_package_manager_profile("retired_manager") == "dmm"
    for manager in ("dmm", "jmm", "cdumm"):
        assert mod_package_export_options_for_manager(manager).manager_targets == (manager,)


def test_build_mod_keeps_jmm_and_explains_compatibility(tmp_path):
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = MeshModExportDialog(
        parent, title="Test", description="", output_parent=str(tmp_path),
        output_choice="jmm_loose", manager_profile="jmm",
    )
    try:
        assert [dialog.manager.itemData(i)[0] for i in range(dialog.manager.count())] == [
            "dmm_loose", "jmm_loose", "cdumm_loose", "dmm_archive",
        ]
        assert dialog.manager.currentData()[2] == "jmm"
        assert dialog.build_button.isEnabled()
        assert dialog.manager_warning.text() == "JMM is outdated; compatibility cannot be ensured."
        assert not dialog.manager_warning.isHidden()
        dialog.manager.setCurrentIndex(0)
        assert dialog.manager.currentData()[2] == "dmm"
        assert dialog.output_path() == tmp_path / "Test-dmm"
    finally:
        dialog.deleteLater()
        parent.deleteLater()
        app.processEvents()
