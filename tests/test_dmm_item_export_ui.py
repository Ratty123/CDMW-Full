"""The real queued callers capture the opt-in; defaults stay unchanged."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.services.independent_item_compatibility import scan_independent_conflicts, prepare_independent_mod_merge
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.independent_items_page import IndependentItemsPage
from cdmw.ui.new_item.mod_merge_dialog import ModMergeDialog
from tests.test_dmm_item_export import installed
from tests.test_independent_item_settings import extended_game
from tests.test_mod_management import pump


@pytest.mark.parametrize('route', ['installed', 'merge'])
def test_opt_in_reaches_real_export_worker_and_is_captured_before_start(tmp_path, installed, route):
    app = QApplication.instance() or QApplication([])
    root, _ = installed
    controller = NewItemStudioController()
    widget = IndependentItemsPage(controller, root, None) if route == 'installed' else ModMergeDialog(controller, root)
    try:
        assert not widget.dmm_v3.isChecked()
        widget.dmm_v3.setChecked(True)
        if route == 'installed':
            widget._comparison = scan_independent_conflicts(root)
            with patch('cdmw.ui.new_item.independent_items_page.QFileDialog.getExistingDirectory', return_value=str(tmp_path)), \
                 patch('cdmw.ui.new_item.independent_items_page.QInputDialog.getText', return_value=('queued-v3', True)):
                widget._export_merge()
        else:
            widget._scanned(prepare_independent_mod_merge(root, dmm_v3=True))
            widget.destination.setText(str(tmp_path / 'queued-v3'))
            widget._export()
        assert controller.busy and not widget.dmm_v3.isEnabled()
        # Even a programmatic change cannot modify the in-flight request.
        widget.dmm_v3.setChecked(False)
        pump(app, lambda: not controller.busy)
        assert (tmp_path / 'queued-v3/mod.field.json').is_file(), widget.status.text()
        assert (tmp_path / 'queued-v3/cdmw-source/cdmw-semantic.cditem').is_file()
    finally:
        if route == 'installed':
            widget.request_shutdown()
        else:
            widget.reject()
        controller.shutdown()
        widget.close()
