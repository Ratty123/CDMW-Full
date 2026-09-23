"""New Item's shared preview controls, through Qt and the Rust input bridge."""

from weakref import WeakSet

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.services.effect_placement_preview import EffectPlacementPreview
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.new_item import preview_controls
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from tests.test_effect_placement_dialog import _AckHost, _blade
from tests import test_new_item_item_preview as item_preview_tests
from tests.test_new_item_rust_ui import _send, studio


@pytest.fixture(autouse=True)
def preference(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    path = str(tmp_path / "preview.ini")
    monkeypatch.setattr(preview_controls, "QSettings", lambda *_args: QSettings(path, QSettings.IniFormat))
    monkeypatch.setattr(preview_controls.PreviewGizmoCheckBox, "_instances", WeakSet())
    yield path
    application.processEvents()


def test_gizmo_toggle_follows_every_shared_preview_page_and_survives_recreation(studio, preference):
    _, tab, bridge = studio
    frame = tab.model_panel.preview
    frame._host_factory = item_preview_tests.ItemPreviewFrameTests._fake_host_class()
    assert frame._ensure_host()
    frame.is_ready = True
    frame._placement = ModelPlacement()
    frame._loaded_is_placement = True
    checkbox = frame.gizmo_visible
    for step, visible in ((0, False), (1, True), (2, False), (0, False)):
        tab.show_step(step)
        frame.is_ready = True
        frame._placement = ModelPlacement()
        frame.host.calls.clear()
        bridge.snapshot()
        node = bridge.document.registry.current[bridge.document.registry.identify(checkbox)]
        assert node["kind"] == "check"
        assert checkbox.isVisibleTo(tab)
        _send(bridge, checkbox, "toggle", visible)
        frame.set_gizmo_enabled(True)  # A model change must respect the preference.
        assert frame.host.calls[-1] == ("set_alignment_state", (), {"enabled": visible, "centered": True})
    settings = QSettings(preference, QSettings.IniFormat)
    settings.sync()
    assert settings.value(preview_controls.GIZMO_VISIBLE_SETTING, True, type=bool) is False
    reopened = preview_controls.PreviewGizmoCheckBox()
    try:
        assert not reopened.isChecked()
    finally:
        reopened.deleteLater()


@pytest.mark.parametrize("compatibility_ui", [False, True])
def test_effect_and_dialog_gizmo_toggle_syncs_with_item_preview_and_ready(studio, tmp_path, compatibility_ui):
    _, tab, _bridge = studio
    workspace = EffectPlacementWorkspace(
        item_mesh=_blade(), box_min=(-1, -1, -1), box_max=(1, 1, 1),
        output_root=tmp_path, host_factory=_AckHost, compatibility_ui=compatibility_ui,
    )
    try:
        checkbox = workspace.gizmo_visible
        document = PresentationDocument()
        document.widget(workspace, force=True)
        node = document.registry.current[document.registry.identify(checkbox)]
        assert node["kind"] == "check"
        assert checkbox.isVisibleTo(workspace)
        tab.model_panel.preview.gizmo_visible.setChecked(False)
        assert not checkbox.isChecked()
        assert workspace.host.alignment_states[-1] is False
        workspace._preview = EffectPlacementPreview(tmp_path / "unused", 0, 1, (-1, -1, -1), (1, 1, 1))
        workspace._host_state("ready", "")
        assert workspace.host.alignment_states[-1] is False
        checkbox.click()
        assert tab.model_panel.preview.gizmo_visible.isChecked()
        assert workspace.host.alignment_states[-1] is True
    finally:
        workspace.request_shutdown()
        workspace.deleteLater()
        QApplication.processEvents()


def test_effect_refresh_keeps_pending_camera_reset_until_current_package_ack(tmp_path, monkeypatch):
    workspace = EffectPlacementWorkspace(
        item_mesh=_blade(), box_min=(-1, -1, -1), box_max=(1, 1, 1),
        output_root=tmp_path, host_factory=_AckHost,
    )
    monkeypatch.setattr(workspace, "_launch_package", lambda _request: None)
    try:
        workspace._start_package(reset_view=True)
        workspace._start_package(reset_view=False)
        generation = workspace._package_generation
        preview = EffectPlacementPreview(tmp_path / "new_model", 0, 1, (-1, -1, -1), (1, 1, 1))
        workspace._package_ready((generation, preview, (), False))
        assert workspace.host.loaded_requests[-1] == (preview.package_dir, True)
        assert workspace._loading_view_state is None
        workspace._start_package(reset_view=True)
        workspace.host.controller.package_applied.emit(str(preview.package_dir), generation)
        assert workspace._reset_view_pending, "an older acknowledgement cannot consume a new model's reset"
        preview = EffectPlacementPreview(tmp_path / "latest_model", 0, 1, (-1, -1, -1), (1, 1, 1))
        workspace._package_ready((workspace._package_generation, preview, (), False))
        assert workspace.host.loaded_requests[-1] == (preview.package_dir, True)
        workspace.host.controller.package_applied.emit(str(preview.package_dir), workspace._package_generation)
        assert not workspace._reset_view_pending
        assert not workspace.host.restored_views, "the old item's camera must not overwrite the reset"
        workspace._start_package(reset_view=False)
        upgraded = EffectPlacementPreview(tmp_path / "new_materials", 0, 1, (-1, -1, -1), (1, 1, 1))
        workspace._package_ready((workspace._package_generation, upgraded, (), False))
        assert workspace.host.loaded_requests[-1] == (upgraded.package_dir, False)
        assert workspace._loading_view_state is not None
    finally:
        workspace.request_shutdown()
        workspace.deleteLater()
        QApplication.processEvents()
