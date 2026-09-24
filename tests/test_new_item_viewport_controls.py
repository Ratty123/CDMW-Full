"""New Item's shared preview controls, through Qt and the Rust input bridge."""

from weakref import WeakSet
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.services.effect_placement_preview import EffectPlacementPreview
from cdmw.domain.new_item.spec import ModelSource
from cdmw.ui.new_item.effect_placement_dialog import EffectPlacementWorkspace
from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement
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


def test_model_toolbar_projects_and_dispatches_outside_the_inspector(studio):
    _, tab, bridge = studio
    tab.show_step(2)
    panel = tab.model_panel
    frame = panel.preview
    frame._host_factory = item_preview_tests.ItemPreviewFrameTests._fake_host_class()
    assert frame._ensure_host()
    QApplication.processEvents()
    frame.is_ready = True
    frame._loaded_is_placement = True
    frame.set_placement(ModelPlacement())
    panel._refresh_placement_enabled()
    panel.inspector_tabs.setCurrentWidget(panel.appearance_page)
    toolbar = bridge.document.widget(panel.gizmo_toolbar, force=True)["children"][0]
    assert toolbar["kind"] == "row"
    assert [node["label"] for node in toolbar["children"]] == ["Move", "Rotate", "Scale", "Frame", "Show gizmo"]
    assert all(node["props"]["image"] for node in toolbar["children"][:4])
    assert frame.isAncestorOf(panel.gizmo_toolbar)
    assert not panel.model_icon_column.isAncestorOf(panel.gizmo_toolbar)
    for tool in ("rotate", "scale", "move", "rotate"):
        frame.host.calls.clear()
        _send(bridge, panel.gizmo_buttons[tool], "activate")
        assert frame.host.calls == [("set_alignment_gizmo_tool", (tool,), {})]
        assert [name for name, button in panel.gizmo_buttons.items() if button.isChecked()] == [tool]
        assert frame.placement == ModelPlacement()
    _send(bridge, panel.gizmo_buttons["rotate"], "activate")
    assert panel.gizmo_buttons["rotate"].isChecked(), "the active tool cannot be deselected"
    for step in (0, 1, 2):
        tab.show_step(step)
        assert panel.gizmo_toolbar.isVisibleTo(tab)
        assert panel.gizmo_buttons["rotate"].isChecked()
        bridge.snapshot()
        node = bridge.document.registry.current[bridge.document.registry.identify(panel.gizmo_buttons["rotate"])]
        assert node["props"]["checked"]
    QApplication.processEvents()
    frame.is_ready = True
    frame._loaded_is_placement = True
    frame.set_placement(ModelPlacement())
    panel._refresh_placement_enabled()
    frame.host.calls.clear()
    _send(bridge, panel.frame_view_button, "activate")
    assert frame.host.calls == [("reset_view", (), {})]
    with patch.object(type(tab.controller), "busy", new_callable=PropertyMock, return_value=True):
        panel._refresh_placement_enabled()
        assert all(not button.isEnabled() for button in panel.gizmo_buttons.values())
    frame.is_ready = False
    panel._refresh_placement_enabled()
    assert all(not button.isEnabled() for button in panel.gizmo_buttons.values())


@pytest.mark.parametrize("imported", [False, True], ids=["template", "imported"])
@pytest.mark.parametrize("tool, field, delta", [
    ("move", "offset", (0.25, -0.5, 0.75)),
    ("rotate", "rotation", (0.0, 45.0, 90.0)),
    ("scale", "scale", (0.5, 1.0, 0.25)),
])
def test_model_toolbar_gizmo_drags_update_placement_values(studio, tmp_path, imported, tool, field, delta):
    _, tab, bridge = studio
    tab.show_step(2)
    controller = tab.controller
    panel = tab.model_panel
    if imported:
        controller.draft.model_source = ModelSource.IMPORTED
        controller.model_import = ModelImportSource(
            tmp_path / "blade.obj", tmp_path / "blade.obj", SimpleNamespace(mesh=None), None, None,
        )
    frame = panel.preview
    frame._host_factory = item_preview_tests.ItemPreviewFrameTests._fake_host_class()
    assert frame._ensure_host()
    frame.is_ready = True
    frame._loaded_is_placement = True
    initial = ModelPlacement()
    frame.set_placement(initial)
    panel._sync_placement_numbers(initial)
    panel._refresh_placement_enabled()
    _send(bridge, panel.gizmo_buttons[tool], "activate")
    frame.host.calls.clear()
    frame.host.alignment_drag_started.emit()
    changed, finished = {
        "move": (frame.host.alignment_drag_changed, frame.host.alignment_drag_finished),
        "rotate": (frame.host.alignment_rotation_changed, frame.host.alignment_rotation_finished),
        "scale": (frame.host.alignment_scale_changed, frame.host.alignment_scale_finished),
    }[tool]
    changed.emit(*delta)
    expected = initial.with_values(**{field: tuple(a + b for a, b in zip(getattr(initial, field), delta))})
    spins = {"move": panel.offset_spins, "rotate": panel.rotation_spins, "scale": panel.scale_spins}[tool]
    assert tuple(spin.value() for spin in spins) == pytest.approx(getattr(expected, field))
    assert controller.model_placement == initial, "unfinished drags only update the preview and numbers"
    finished.emit(*delta)
    assert controller.model_placement == expected
    assert tuple(spin.value() for spin in spins) == pytest.approx(getattr(expected, field))
    assert not any(call[0] in {"reset_view", "set_view", "request_canonical_view"} for call in frame.host.calls)


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
        workspace.host.set_view(yaw=41, pitch=16, zoom_factor=1.8, fit_to_view=False)
        view_during_load = workspace.host.view_state_snapshot()
        workspace.host.controller.package_applied.emit(str(upgraded.package_dir), workspace._package_generation)
        assert workspace.host.view_state_snapshot() == view_during_load
        assert not workspace.host.restored_views, "refresh must not replay a snapshot taken before the user's latest gesture"
    finally:
        workspace.request_shutdown()
        workspace.deleteLater()
        QApplication.processEvents()


@pytest.mark.parametrize("placement", [False, True])
def test_item_refresh_frames_only_new_templates(tmp_path, monkeypatch, placement):
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame

    class Host(item_preview_tests.ItemPreviewFrameTests._fake_host_class()):
        def request_canonical_view(self):
            self.calls.append(("request_canonical_view", (), {}))
            return True

    frame = ItemPreviewFrame(output_root=tmp_path, host_factory=Host)
    monkeypatch.setattr(frame, "_start_package", lambda _request: None)
    assert frame._ensure_host()
    forgotten = []
    frame.host.controller.forget_state = forgotten.append
    try:
        cases = (
            ("mask", 1, True), ("character", 1, False), ("variant", 1, False),
            ("dye", 1, False), ("import", 1, False), ("gloves", 2, True),
            ("gloves_materials", 2, False), ("mask_again", 1, True),
        )
        for token, template_key, reset in cases:
            kwargs = {"token": token, "framing_key": template_key}
            if placement:
                frame.show_placement(object(), placement=ModelPlacement(), **kwargs)
            else:
                frame.show(object(), **kwargs)
            package = tmp_path / token
            package.mkdir()
            frame.host.calls.clear()
            forgotten.clear()
            frame._package_ready(package, token, placement, "materials")
            frame._host_state("ready", "")
            loads = [call for call in frame.host.calls if call[0] == "load_package"]
            assert loads[-1][2]["reset_view"] is reset
            fits = [call for call in frame.host.calls if call[0] == "request_canonical_view"]
            assert len(fits) == int(reset and placement)
            assert forgotten == ["scene"], "changing geometry must discard the old matrices even without a camera reset"
        frame.host.calls.clear()
        frame.fit_view()
        assert ("request_canonical_view", (), {}) in frame.host.calls
    finally:
        frame.request_shutdown()
        frame.deleteLater()
        QApplication.processEvents()


@pytest.mark.parametrize("offset", [None, (0, 0, 0), (3, 2, 1)])
def test_effect_default_uses_prepared_subject_bounds_without_overwriting_saved_positions(tmp_path, offset):
    workspace = EffectPlacementWorkspace(
        item_mesh=_blade(), box_min=(-1, -1, -1), box_max=(1, 1, 1),
        offset=offset, output_root=tmp_path, host_factory=_AckHost,
    )
    workspace._initial_package_timer.stop()
    try:
        preview = EffectPlacementPreview(
            tmp_path / "effect", 0, 1, (-1, -1, -1), (1, 1, 1), default_offset=(2, 1, 0),
        )
        workspace._package_ready((workspace._package_generation, preview, (), False))
        workspace.host.controller.package_applied.emit(str(preview.package_dir), workspace._package_generation)
        assert workspace.offset == ((2, 1, 0) if offset is None else offset)
        workspace._set_numbers((0, 0, 0), 1)
        preview = EffectPlacementPreview(
            tmp_path / "effect_refresh", 0, 1, (-1, -1, -1), (1, 1, 1), default_offset=(4, 1, 0),
        )
        workspace._package_ready((workspace._package_generation, preview, (), False))
        workspace.host.controller.package_applied.emit(str(preview.package_dir), workspace._package_generation)
        assert workspace.offset == (0, 0, 0)
    finally:
        workspace.request_shutdown()
        workspace.deleteLater()
        QApplication.processEvents()


def test_shared_pages_and_dye_preview_use_the_selected_template_as_framing_key(studio, monkeypatch):
    from cdmw.ui.new_item import dye_preview

    _, tab, _bridge = studio
    panel = tab.model_panel
    frame = panel.preview
    frame._host_factory = item_preview_tests.ItemPreviewFrameTests._fake_host_class()
    assert frame._ensure_host()
    monkeypatch.setattr(tab.controller, "item_preview_source", lambda **kwargs: (str(kwargs), object()))
    for step in (0, 1, 2):
        tab.show_step(step)
        panel.show_character.setChecked(not panel.show_character.isChecked())
        panel.refresh_preview()
        assert frame._pending_framing_key == tab.controller.draft.template_key
    monkeypatch.setattr(dye_preview, "variant_dye_preview_source", lambda _controller: ("dye-refresh", object()))
    for control in (panel.dyes, panel.dyes.preview):
        control.blockSignals(True)
        control.setChecked(True)
        control.blockSignals(False)
    panel.refresh_preview()
    assert frame._pending[0] == "dye-refresh"
    assert frame._pending_framing_key == tab.controller.draft.template_key
