"""The real queued caller captures the opt-in; defaults stay unchanged."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
from tests.test_dmm_item_export import installed
from tests.test_independent_item_settings import extended_game
from tests.test_mod_management import pump


def test_opt_in_reaches_real_export_worker_and_is_captured_before_start(tmp_path, installed):
    app = QApplication.instance() or QApplication([])
    root, _ = installed
    controller = NewItemStudioController()
    widget = ModMergeDialog(controller, root)
    try:
        assert not widget.dmm_v3.isChecked()
        widget.dmm_v3.setChecked(True)
        widget._scanned(prepare_independent_mod_merge(root, dmm_v3=True))
        widget.destination.setText(str(tmp_path / 'queued-v3'))
        widget._export()
        assert controller.busy and not widget.dmm_v3.isEnabled()
        # Even a programmatic change cannot modify the in-flight request.
        widget.dmm_v3.setChecked(False)
        pump(app, lambda: not controller.busy)
        assert (tmp_path / 'queued-v3/mod.field.json').is_file(), widget.status.text()
        assert (tmp_path / 'queued-v3/cdmw-source/cdmw-semantic.cdmw').is_file()
    finally:
        widget.reject()
        controller.shutdown()
        widget.close()
