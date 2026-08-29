from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidgetItem, QWidget

from cdmw.core.recolor_variants import analyze_recolor_variant_package
from cdmw.services.settings_service import create_settings
from cdmw.ui.recolor_variants_tab import RecolorVariantsTab
from cdmw.ui.shell.compact.presentations import apply_compact_presentation
from cdmw.ui.widgets import CollapsibleSection
from tests.test_recolor_variants import _write_mod


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _settle(app: QApplication) -> None:
    for _ in range(4):
        app.processEvents()


def test_compact_recolor_workspace_reclaims_inactive_panes() -> None:
    app = _app()
    with tempfile.TemporaryDirectory(prefix="cdmw-recolor-layout-") as temp_dir:
        root = Path(temp_dir)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = RecolorVariantsTab(settings=settings, base_dir=root)
        window = SimpleNamespace(is_compact_shell=True, settings=settings)
        try:
            assert not tab.preview_section.isHidden()
            assert not tab.results_widget.isHidden()
            assert apply_compact_presentation(window, "recolor_variants", tab)
            tab.resize(1680, 900)
            tab.show()
            _settle(app)

            source_section = tab.findChild(QWidget, "RecolorVariantSourceSection")
            template_section = tab.findChild(QWidget, "RecolorVariantTemplateSection")
            output_section = tab.findChild(QWidget, "RecolorVariantOutputSection")
            assert source_section is not None
            assert template_section is not None
            assert output_section is not None
            for section in (source_section, template_section, output_section):
                assert section.height() <= section.sizeHint().height() + 4
            assert template_section.y() - source_section.geometry().bottom() <= 8
            assert output_section.y() - template_section.geometry().bottom() <= 8

            collapsed_heights = (template_section.height(), output_section.height())
            for collapsible in tab.findChildren(CollapsibleSection):
                collapsible.set_expanded(True)
            _settle(app)
            assert template_section.height() > collapsed_heights[0]
            assert output_section.height() > collapsed_heights[1]
            for section in (template_section, output_section):
                assert section.height() <= section.sizeHint().height() + 4

            assert tab.preview_section.isHidden()
            assert tab.results_widget.isHidden()
            idle_sizes = tab.splitter.sizes()
            assert idle_sizes[2] == 0
            assert idle_sizes[1] > idle_sizes[0] * 2
            assert tab.preview_source_image_label.minimumHeight() <= 220

            source = _write_mod(root)
            tab.analysis = analyze_recolor_variant_package(source)
            tab._populate_targets_tree()
            tab._sync_action_state()
            _settle(app)
            assert tab.preview_section.isVisible()
            assert tab.results_widget.isHidden()

            tab.outputs_tree.addTopLevelItem(
                QTreeWidgetItem(["Temporary output", "Built", "1 texture"])
            )
            tab._sync_workspace_visibility()
            _settle(app)
            result_sizes = tab.splitter.sizes()
            assert tab.results_widget.isVisible()
            assert 0 < result_sizes[2] <= 440
            assert result_sizes[1] > result_sizes[0]
            assert result_sizes[1] > result_sizes[2]
        finally:
            tab.close()
            tab.deleteLater()
            _settle(app)
