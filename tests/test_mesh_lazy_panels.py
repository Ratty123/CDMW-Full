import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QTreeWidget

from cdmw.domain.mesh import MeshObjectTransformState
from cdmw.ui.mesh_editor.tab import MeshEditorTab


def test_resident_tab_defers_panels_and_replays_latest_state(tmp_path):
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat))
    try:
        workspace = tab.standalone_workspace
        assert workspace._legacy_panels_deferred
        output = workspace.export_mesh_file_button
        workspace.sync_ui_font(QFont('Segoe UI', 11))
        workspace.update_action_state(has_target=True, mode='edit', selection_empty=False)
        workspace.update_object_transform(MeshObjectTransformState(location=(1., 2., 3.)))
        workspace.update_object_transform(MeshObjectTransformState(location=(4., 5., 6.)))
        workspace.set_native_performance_status({'fps': 60.})
        assert workspace._legacy_panels_deferred
        assert 'outliner' not in workspace.__dict__
        tree = workspace.findChild(QTreeWidget, 'MeshEditorOutlinerPanel')
        assert tree is workspace.outliner
        assert not workspace._legacy_panels_deferred
        assert workspace.export_mesh_file_button is output
        assert '60.0' in workspace.native_performance_status_label.text()
        assert [spin.value() for spin in workspace.object_transform_spins['location']] == [4., 5., 6.]
        assert workspace.button_for_key('select_parts').isEnabled()
        assert workspace.left_tool_pages.isHidden() or workspace.left_tool_pages.parentWidget().isHidden()
    finally:
        tab.close()
        tab.deleteLater()
        app.processEvents()
