"""Styled Qt geometry for the effect tools, without a renderer or game assets."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout

from cdmw.domain.new_item.effect_authoring import EffectLayer
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from cdmw.ui.new_item.effect_recipe_panel import EffectRecipePanel, EffectUserLibrary
from cdmw.ui.new_item.state import EffectWorkspaceState
from cdmw.ui.new_item.ui_kit import step_style
from cdmw.ui.themes import build_app_palette, build_app_stylesheet
from tests.test_effect_placement_dialog import _Host, _blade

_APP = QApplication.instance() or QApplication([])
_FONT = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
if _FONT.is_file():
    QFontDatabase.addApplicationFont(str(_FONT))


@pytest.mark.parametrize("width,height,font_size", [(1000, 700, 9), (1600, 900, 9), (1100, 720, 11)])
def test_styled_effect_tools_are_compact_and_do_not_overlap(monkeypatch, width, height, font_size):
    monkeypatch.setattr(EffectPlacementWorkspace, "_start_package", lambda self: None)
    previous_font = _APP.font()
    _APP.setFont(QFont("Segoe UI", font_size))
    root = QGroupBox()
    root.setObjectName("new_item_step")
    root.setFont(QFont("Segoe UI", font_size))
    root.setPalette(build_app_palette("graphite"))
    root.setStyleSheet(build_app_stylesheet("graphite") + step_style(root.palette()))
    outer = QTabWidget()
    outer.setObjectName("new_item_perks_effects_tabs")
    QVBoxLayout(root).addWidget(outer)
    workspace = EffectPlacementWorkspace(
        item_mesh=_blade(), box_min=(-1, -1, -1), box_max=(1, 1, 1),
        host_factory=_Host, compatibility_ui=False,
    )
    outer.addTab(workspace, "Effects")
    recipe = EffectRecipePanel(EffectUserLibrary(), workspace.inspector_widget)
    workspace.inspector_widget.layout().insertWidget(0, recipe)
    recipe.set_state(EffectWorkspaceState.from_layers((EffectLayer("fx_fire"), EffectLayer("fx_sparks"))))
    workspace.setFont(root.font())
    root.resize(width, height)
    root.show()
    try:
        for _ in range(3):
            _APP.processEvents()
        assert root.width() == width
        assert recipe.emitter.font().pointSize() == font_size
        scroll = workspace.findChild(QScrollArea, "effect_inspector_scroll")
        assert scroll.horizontalScrollBar().maximum() == 0
        tabs = recipe.findChild(QTabWidget)
        layers_height = recipe.height()
        assert layers_height < 240
        add = next(button for button in tabs.currentWidget().findChildren(QPushButton) if button.text() == "Add")
        assert 0 <= add.y() - recipe.layers.geometry().bottom() <= 10
        assert add.width() <= add.sizeHint().width() + 4
        heading = workspace.findChild(QLabel, "effect_inspector_heading")
        assert 0 <= heading.y() - recipe.geometry().bottom() <= 12
        for button in workspace._guided_toolbar_buttons:
            assert button.width() <= button.sizeHint().width() + 4
            assert button.height() < 38
            assert workspace.guided_toolbar_panel.rect().contains(button.geometry())
            for other in workspace._guided_toolbar_buttons:
                if other is not button:
                    assert not button.geometry().intersects(other.geometry())
        for control in workspace.playback_controls._controls:
            assert control.width() <= control.sizeHint().width() + 4
            assert workspace.playback_controls.rect().contains(control.geometry())
        if width == 1600:
            assert workspace.playback_controls._columns == 5
            assert workspace.playback_controls.height() < 40

        tabs.setCurrentIndex(1)
        recipe.set_preview(SimpleNamespace(editor_emitters=({
            "name": "Sparks", "enabled": True, "resolved": True,
            "fields": ("_spawnCountMin",), "values": {"_spawnCountMin": (3,)},
        },)))
        for _ in range(3):
            _APP.processEvents()
        assert recipe.height() > layers_height
        assert scroll.horizontalScrollBar().maximum() == 0
        for row in range(recipe.parameters.rowCount()):
            holder = recipe.parameters.cellWidget(row, 2)
            for spin in holder.findChildren(type(workspace.scale_spin)):
                assert holder.rect().contains(spin.geometry()), (row, spin.geometry(), holder.rect())

        for index in (2, 0):
            tabs.setCurrentIndex(index)
            for _ in range(3):
                _APP.processEvents()
            assert recipe.height() < 240
            assert 0 <= heading.y() - recipe.geometry().bottom() <= 12
            buttons = tabs.currentWidget().findChildren(QPushButton)
            for button in buttons:
                assert tabs.currentWidget().rect().contains(button.geometry())

        assert not scroll.isAncestorOf(workspace.apply_button)
        before = workspace.apply_button.mapTo(workspace, QPoint())
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        _APP.processEvents()
        assert workspace.apply_button.mapTo(workspace, QPoint()) == before
        capture = os.environ.get("CDMW_EFFECT_LAYOUT_CAPTURE")
        if capture and width == 1600:
            scroll.verticalScrollBar().setValue(0)
            _APP.processEvents()
            root.grab().save(capture)
            tabs.setCurrentIndex(1)
            for _ in range(3):
                _APP.processEvents()
            scroll.verticalScrollBar().setValue(0)
            root.grab().save(str(Path(capture).with_stem("cdmw-effects-emitters")))
    finally:
        workspace.request_shutdown()
        root.close()
        shiboken6.delete(root)
        _APP.setFont(previous_font)
