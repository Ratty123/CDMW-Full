"""Styled Qt geometry for the effect tools, without a renderer or game assets."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from cdmw.domain.new_item.effect_authoring import EffectLayer
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from cdmw.ui.new_item.effect_recipe_panel import EffectRecipePanel, EffectUserLibrary
from cdmw.ui.new_item.effect_workspace import GuidedEffectsWorkspace
from cdmw.ui.new_item.state import EffectWorkspaceState
from cdmw.ui.new_item.ui_kit import step_style
from cdmw.ui.themes import build_app_palette, build_app_stylesheet
from tests.test_effect_placement_dialog import _Host, _blade
from tests.test_new_item_effect_workspace import _Controller

_APP = QApplication.instance() or QApplication([])
_FONT = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
if _FONT.is_file():
    QFontDatabase.addApplicationFont(str(_FONT))


@pytest.mark.parametrize("width,height,font_size", [(1280, 720, 9), (1600, 900, 9), (1280, 720, 11)])
def test_effect_library_controls_leave_the_viewport_full_height(monkeypatch, width, height, font_size):
    """Headless styled geometry; the placeholder owns no renderer or game assets."""
    monkeypatch.setattr(GuidedEffectsWorkspace, "_rebuild_preview", lambda self: None)
    previous_font = _APP.font()
    _APP.setFont(QFont("Segoe UI", font_size))
    root = QGroupBox()
    root.setObjectName("new_item_step")
    root.setProperty("guidedPage", True)
    root.setFont(QFont("Segoe UI", font_size))
    root.setPalette(build_app_palette("graphite"))
    root.setStyleSheet(build_app_stylesheet("graphite") + step_style(root.palette()))
    tabs = QTabWidget()
    tabs.setObjectName("new_item_perks_effects_tabs")
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(tabs)
    controller = _Controller()
    workspace = GuidedEffectsWorkspace(controller)
    tabs.addTab(workspace, "Effects")
    tabs.addTab(QWidget(), "Experimental Features (Perks, Sockets, Bonuses)")
    tabs.setCurrentWidget(workspace)
    tabs.setCornerWidget(workspace.library_controls, Qt.Corner.TopLeftCorner)
    root.resize(width, height)
    root.show()

    def settle():
        for _ in range(4):
            _APP.processEvents()

    def library_rect(widget):
        return QRect(widget.mapTo(workspace.library_panel, QPoint()), widget.size())

    try:
        settle()
        assert root.size().width() == width
        assert root.size().height() == height
        assert workspace.placement is None
        assert workspace.library_toggle.isVisibleTo(root)
        assert workspace.library_panel.isVisibleTo(workspace)
        assert workspace.splitter.y() <= 1
        assert workspace.placement_holder.y() == 0
        assert workspace.height() - workspace.splitter.geometry().bottom() - 1 <= workspace.caution.fontMetrics().height() + 16
        assert workspace.caution.height() <= workspace.caution.fontMetrics().height() + 8
        controls = workspace.library_controls
        assert tabs.cornerWidget(Qt.Corner.TopLeftCorner) is controls
        for control in (workspace.library_toggle, workspace.selected_effect_label):
            assert controls.rect().contains(control.geometry())
        assert not workspace.library_toggle.geometry().intersects(workspace.selected_effect_label.geometry())
        assert controls.mapTo(tabs, controls.rect().topRight()).x() < tabs.tabBar().geometry().left()
        assert workspace.selected_effect_label.width() <= 240

        original_placeholder = workspace.placeholder
        workspace.library_toggle.setChecked(False)
        settle()
        workspace.library_toggle.setChecked(True)
        settle()
        assert workspace.library_panel.isVisibleTo(workspace)
        toggle_center = workspace.library_toggle.mapTo(workspace.library_panel, workspace.library_toggle.rect().center())
        assert 0 <= toggle_center.x() < workspace.library_panel.width()
        assert workspace.library_panel.isAncestorOf(workspace.search)
        assert workspace.library_panel.isAncestorOf(workspace.category_choice)
        assert 120 <= workspace.search.width() <= 280
        assert workspace.library_panel.rect().contains(library_rect(workspace.search))
        filters = (workspace.behavior_all, workspace.loop_only, workspace.one_shot_only, workspace.category_choice)
        for index, control in enumerate(filters):
            rect = library_rect(control)
            assert workspace.library_panel.rect().contains(rect)
            assert abs(rect.center().y() - library_rect(workspace.category_choice).center().y()) <= 2
            for other in filters[index + 1:]:
                assert not rect.intersects(library_rect(other))
        assert library_rect(workspace.search).bottom() < library_rect(workspace.category_choice).top()
        assert workspace.splitter.y() <= 1
        assert workspace.placeholder is original_placeholder
        expanded_height = workspace.splitter.height()
        workspace.library_toggle.click()
        settle()
        assert not workspace.library_panel.isVisibleTo(workspace)
        assert workspace.splitter.height() == expanded_height
        assert workspace.placeholder is original_placeholder
    finally:
        workspace.request_shutdown()
        root.close()
        shiboken6.delete(root)
        _APP.setFont(previous_font)


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
    recipe.hide()
    while recipe.tabs.count():
        page, title = recipe.tabs.widget(0), recipe.tabs.tabText(0)
        recipe.tabs.removeTab(0)
        page.layout().setContentsMargins(10, 8, 10, 8)
        workspace._add_inspector_tab(page, title)
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
        tabs = workspace.inspector_tabs
        tabs.setCurrentIndex(2)
        _APP.processEvents()
        layers_page = tabs.currentWidget().widget()
        add = next(button for button in layers_page.findChildren(QPushButton) if button.text() == "Add")
        assert 0 <= add.y() - recipe.layers.geometry().bottom() <= 10
        assert add.width() <= add.sizeHint().width() + 4
        assert not recipe.isVisibleTo(workspace)
        assert recipe.layers.isVisibleTo(workspace)
        for button in workspace._guided_toolbar_buttons:
            assert button.width() <= button.sizeHint().width() + 4
            assert button.height() < 38
            assert workspace.guided_toolbar_panel.rect().contains(button.geometry())
            for other in workspace._guided_toolbar_buttons:
                if other is not button:
                    assert not button.geometry().intersects(other.geometry())
        for control in workspace.playback_controls._controls:
            assert control.width() <= control.sizeHint().width() + 4
            assert workspace.guided_toolbar_panel.rect().contains(control.geometry())
        assert workspace.guided_toolbar_panel.rect().contains(workspace.gizmo_visible.geometry())
        assert workspace.preview_options_toggle.isChecked()
        assert workspace.placement_toggle.isChecked()
        workspace.placement_toggle.click()
        assert workspace.placement_controls.isHidden()
        assert not workspace.preview_options.isHidden()
        workspace.placement_toggle.click()
        assert not workspace.placement_controls.isHidden()

        tabs.setCurrentIndex(3)
        recipe.set_preview(SimpleNamespace(editor_emitters=({
            "name": "Sparks", "enabled": True, "resolved": True,
            "fields": ("_spawnCountMin",), "values": {"_spawnCountMin": (3,)},
        },)))
        for _ in range(3):
            _APP.processEvents()
        assert tabs.currentWidget().horizontalScrollBar().maximum() == 0
        for row in range(recipe.parameters.rowCount()):
            holder = recipe.parameters.cellWidget(row, 2)
            for spin in holder.findChildren(type(workspace.scale_spin)):
                assert holder.rect().contains(spin.geometry()), (row, spin.geometry(), holder.rect())

        for index in (4, 2):
            tabs.setCurrentIndex(index)
            for _ in range(3):
                _APP.processEvents()
            page = tabs.currentWidget().widget()
            buttons = page.findChildren(QPushButton)
            for button in buttons:
                assert page.rect().contains(button.geometry())

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
            tabs.setCurrentIndex(3)
            for _ in range(3):
                _APP.processEvents()
            scroll.verticalScrollBar().setValue(0)
            root.grab().save(str(Path(capture).with_stem("cdmw-effects-emitters")))
    finally:
        workspace.request_shutdown()
        root.close()
        shiboken6.delete(root)
        _APP.setFont(previous_font)
