"""Painted masks through the real brush, material writer and owned DDS export."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import numpy as np
from PIL import Image
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget

from cdmw.core.pac_xml_standard_material import find_material_wrappers
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.mesh.shader_controls import EYE_COVER, ShaderControls, preview_factors
from cdmw.domain.new_item.authoring import VariantAppearance
from cdmw.domain.new_item.spec import MaterialRoute, ModelSource
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.domain.textures.transparency_mask import TransparencyMask
from cdmw.services.new_item_materials import route_plain_pbr
from cdmw.services.new_item_shader_controls import apply_shader_controls
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_translucency import apply_prebuilt_translucency
from cdmw.services.new_item_transparency_paint import TransparencyPaintSource, prepare_transparency_paint
from tests.test_translucency_surface import source_files, PAC, XML, SP
from tests.test_new_item_rust_ui import studio, _send


def gradient():
    return TransparencyMask(64, 16, np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (16, 1)).tobytes())


def controls(mask=None):
    return ShaderControls(EYE_COVER.shader, (("_eyeCoverDiffuseParameter", (.5,)), ("material_red", (.1,))), mask)


def rgba(payload):
    with Image.open(BytesIO(payload)) as image:
        return np.asarray(image.convert("RGBA"))


def snapshot_for(files):
    return SimpleNamespace(payload=lambda path: files.pac_data if path == PAC else files.side_files[path],
                           has_entry=files.side_files.__contains__)


def test_mask_roundtrip_and_packed_preview_keeps_spatial_channel():
    mask = gradient()
    value = controls(mask)
    assert ShaderControls.from_dict(value.to_dict()) == value
    assert mask.pixels.hex() not in repr(value)
    assert preview_factors(value)[6] == -1
    assert ShaderControls.from_dict(controls().to_dict()) == controls()
    with pytest.raises(ValueError, match="Transparent surface"):
        ShaderControls("SkinnedMeshWing", transparency_mask=mask).validate()
    with pytest.raises(ValueError):
        TransparencyMask.from_dict({"width": 1, "height": 1, "pixels": mask.to_dict()["pixels"]})


@pytest.mark.parametrize("mode", ["blending", "translucency"])
@pytest.mark.parametrize("route", ["template", "prebuilt", "import"])
def test_mask_export_preserves_other_channels_parts_and_sources(mode, route, tmp_path):
    files, mask = source_files(), gradient()
    original = dict(files.side_files)
    glass = TranslucencyChoice(("Blade",), .5, .7, masks=(("Blade", mask),))
    shaders = (("Blade", controls(mask)),)
    baseline = files
    if route == "template":
        output = prepare_template_model(snapshot_for(files), (PAC,),
            translucency=glass if mode == "translucency" else None,
            shader_controls=shaders if mode == "blending" else ())
    elif route == "prebuilt":
        output = (apply_prebuilt_translucency(files, MaterialRoute.PLAIN_PBR, glass)
                  if mode == "translucency" else apply_shader_controls(files, shaders))
    else:
        from cdmw.services.new_item_materials import SourceMaterialTextures
        source_map = tmp_path / "surface.png"
        Image.open(BytesIO(original[SP])).save(source_map)
        sources = {name.casefold(): SourceMaterialTextures(name, material=source_map) for name in ("Blade", "Gem")}
        baseline = route_plain_pbr(files, sources=sources).files
        output = route_plain_pbr(files, sources=sources, translucency=glass if mode == "translucency" else None).files
        if mode == "blending":
            output = apply_shader_controls(output, shaders)
    blade, gem = find_material_wrappers(output.side_files[XML].decode("utf-8-sig"))
    parameter, channel = ("_baseColorTexture", 3) if mode == "translucency" else ("_materialTexture", 0)
    assert blade.textures[parameter] != gem.textures[parameter]
    data = output.side_files[blade.textures[parameter]]
    pixels = rgba(data)
    expected = np.frombuffer(mask.pixels, dtype=np.uint8).reshape(mask.height, mask.width)
    if mode == "translucency":
        expected = 255 - expected
    assert np.abs(pixels[..., channel].astype(int) - expected).max() <= 3
    assert len(np.unique(pixels[..., channel])) > 32
    old_wrapper = find_material_wrappers(baseline.side_files[XML].decode("utf-8-sig"))[0]
    source = Image.open(BytesIO(baseline.side_files[old_wrapper.textures[parameter]])).convert("RGBA")
    expected_other = np.asarray(source.resize((mask.width, mask.height), Image.Resampling.BILINEAR))
    for other in range(4):
        if other != channel:
            assert np.abs(pixels[..., other].astype(int) - expected_other[..., other].astype(int)).max() <= 6
    from cdmw.core.dds_native import inspect_dds_native
    info = inspect_dds_native(data)
    assert info.format_name == "BC7_UNORM"
    assert len(info.mip_levels) == 7
    assert files.side_files == original and output.pac_data == files.pac_data


@pytest.mark.parametrize("mode", ["blending", "translucency"])
def test_painter_preparation_reuses_saved_pixels_and_real_owned_materials(mode):
    files, mask = source_files(), gradient()
    appearance = VariantAppearance("fixture.prefab", PAC,
        translucency=TranslucencyChoice(("Blade",), masks=(("Blade", mask),)) if mode == "translucency" else None,
        shader_controls=(("Blade", controls(mask)),) if mode == "blending" else ())
    prepared = prepare_transparency_paint(snapshot_for(files), appearance, "Blade", mode)
    assert prepared.mask == mask  # Reopening must not accumulate BC7 loss.
    assert len(prepared.reference_rgba) == mask.width * mask.height * 4
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RunCancelled):
        prepare_transparency_paint(snapshot_for(files), appearance, "Blade", mode, stop_event=cancelled)


@pytest.mark.parametrize("alpha_mode", ["OPAQUE", "BLEND"])
def test_explicit_paint_survives_real_gltf_import_and_opaque_alpha_policy(tmp_path, alpha_mode):
    from tests.test_new_item_texture_fidelity import write_gltf, export_materials, pixels
    image = Image.new("RGBA", (64, 16), (160, 110, 70, 33))
    image.save(tmp_path / "base.png")
    material = {"name": "Glass", "alphaMode": alpha_mode,
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
    path = write_gltf(tmp_path, [material], ["base.png"])
    mask = gradient()
    _, files, wrappers = export_materials(path, tmp_path, socket_attached=True,
        translucency=TranslucencyChoice(("Glass",), masks=(("Glass", mask),)))
    actual = pixels(files, wrappers["Glass"])
    expected = 255 - np.frombuffer(mask.pixels, dtype=np.uint8).reshape(16, 64)
    assert np.abs(actual[..., 3].astype(int) - expected).max() <= 3
    assert np.abs(actual[..., :3].astype(int) - [160, 110, 70]).max() <= 4


def test_canvas_paints_soft_values_undoes_and_only_apply_publishes():
    from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
    app = QApplication.instance() or QApplication([])
    mask = TransparencyMask(64, 64, bytes(4096))
    prepared = TransparencyPaintSource(mask, bytes([90, 120, 160, 255]) * 4096)
    accepted = []
    dialog = TransparencyPaintDialog(prepared, accepted.append, part="Blade")
    try:
        dialog.brush_size.setValue(24)
        dialog.canvas.stroke_committed.emit({"tool": "paint", "points": [(20, 20), (28, 20)]})
        painted = dialog._history[dialog._history_index]
        assert len(set(painted)) > 10
        assert painted[0] == 0 and painted[20 * 64 + 20] > 0
        assert not accepted and prepared.mask.pixels == bytes(4096)
        dialog.undo_button.click()
        assert dialog._history[dialog._history_index] == mask.pixels
        dialog.redo_button.click()
        assert dialog._history[dialog._history_index] == painted
        dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
        assert accepted == [TransparencyMask(64, 64, painted)]
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_mask_editor_controls_retain_pixels_when_uniform_settings_change():
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    from cdmw.ui.new_item.translucency_editor import TranslucencyEditor
    app = QApplication.instance() or QApplication([])
    mask = gradient()
    shader, glass = ShaderControlsEditor(), TranslucencyEditor()
    changed = []
    try:
        shader.refresh((("Blade", "Blade"),), (("Blade", controls(mask)),))
        shader.changed.connect(changed.append)
        field = next(row for row in shader._rows if row[0].name == "material_red")
        assert not field[1].isEnabled() and not field[2][0].isEnabled()
        shader._rows[0][2][0].setValue(.25)
        assert changed[-1][0][1].transparency_mask == mask
        glass.refresh((("Blade", "Blade"),), TranslucencyChoice(("Blade",), masks=(("Blade", mask),)))
        glass.changed.connect(changed.append)
        glass.thickness.setValue(.8)
        assert changed[-1].masks == (("Blade", mask),)
    finally:
        shader.deleteLater()
        glass.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("mode", ["blending", "translucency"])
def test_import_preview_carries_mask_into_real_rust_material_resources(tmp_path, monkeypatch, mode):
    from tests.test_new_item_texture_fidelity import write_gltf
    from cdmw.ui.new_item.model_import import load_model_import_source
    from cdmw.services.new_item_translucency import translucency_preview_mesh
    from cdmw.services.shader_controls_preview import shader_preview_mesh
    from cdmw.services.mesh_rust_authoring import _mesh_texture_payloads, _mesh_material_presentations, _session_root_identity
    Image.new("RGBA", (64, 16), (100, 150, 190, 45)).save(tmp_path / "base.png")
    path = write_gltf(tmp_path, [{"name": name, "alphaMode": "OPAQUE",
        "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}} for name in ("Solid", "Glass")], ["base.png"])
    source = load_model_import_source(path)
    mask = gradient()
    try:
        mesh = source.baked_preview_mesh()
        original_overrides = dict(getattr(mesh.submeshes[1], "preview_native_material_overrides", {}) or {})
        if mode == "blending":
            preview = shader_preview_mesh(mesh, (("Glass", controls(mask)),), plain_pbr=True)
            role, channel = "material", 0
        else:
            preview = translucency_preview_mesh(mesh, TranslucencyChoice(("Glass",), masks=(("Glass", mask),)))
            role, channel = "base_color", 3
            assert _mesh_material_presentations(preview)[1]["alpha_mode"] == "blend"
            assert _mesh_material_presentations(preview)[0]["alpha_mode"] == "opaque"
        output = tmp_path / "preview"
        output.mkdir()
        resources = _mesh_texture_payloads(output, preview, expected_root_identity=_session_root_identity(output))
        resource = next(row for row in resources if row["role"] == role and row["material_indices_by_lod"] == [[1]])
        local = output / resource["file"]["path"]
        actual = rgba(local.read_bytes())[..., channel]
        if mode == "blending":
            assert (rgba(local.read_bytes())[..., 1:3] == 255).all(), "Adding a red mask must retain glTF factor-only surfaces."
        expected = np.frombuffer(mask.pixels, dtype=np.uint8).reshape(16, 64)
        if mode == "translucency":
            expected = 255 - expected
        assert np.array_equal(actual, expected)
        assert getattr(mesh.submeshes[1], "preview_native_material_overrides", {}) == original_overrides
    finally:
        source.cleanup()


def test_native_canvas_remains_visible_to_rust_presentation():
    from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs
    from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
    app = QApplication.instance() or QApplication([])
    workflow, visible = QWidget(), QWidget()
    dialogs = PresentationDialogs(workflow, visible)
    dialogs.active = True
    mask = gradient()
    prepared = TransparencyPaintSource(mask, bytes([90, 120, 160, 255]) * (mask.width * mask.height))
    dialog = TransparencyPaintDialog(prepared, lambda _mask: None, part="Blade", parent=workflow)
    try:
        dialog.open()
        app.processEvents()
        assert dialog.parentWidget() is visible
        assert not dialog.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        assert dialogs.native_modal()
        assert not dialogs.dialogs()  # A pixel canvas must not become an empty projected dialog.
        dialog.reject()
        app.processEvents()
        assert not dialogs.native_modal()
    finally:
        dialogs.close()
        dialog.deleteLater()
        workflow.deleteLater()
        visible.deleteLater()
        app.processEvents()


def _controller():
    from cdmw.ui.new_item.controller import NewItemStudioController
    controller = NewItemStudioController(synchronous=False)
    controller.snapshot = SimpleNamespace(sources=None)
    controller._active_variant = ("fixture.prefab", PAC)
    controller.draft.template_key = 123
    controller.draft.shader_controls = (("Blade", controls()),)
    return controller


def _wait(app, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.005)
    assert predicate(), "worker did not finish"


@pytest.mark.parametrize("cancel", [False, "draft", "shutdown"])
def test_worker_preparation_applies_only_to_current_revision_and_shuts_down(monkeypatch, cancel):
    app = QApplication.instance() or QApplication([])
    controller = _controller()
    entered, release = threading.Event(), threading.Event()
    prepared = TransparencyPaintSource(gradient(), bytes([0, 0, 0, 255]) * 1024)
    worker_threads, callbacks = [], []
    def prepare(*_args, stop_event=None, **_kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        from cdmw.domain.cancellation import raise_if_cancelled
        raise_if_cancelled(stop_event)
        return prepared
    monkeypatch.setattr("cdmw.services.new_item_transparency_paint.prepare_transparency_paint", prepare)
    try:
        assert controller.start_transparency_paint("Blade", "blending", lambda *args: callbacks.append((threading.get_ident(), args)))
        _wait(app, entered.is_set)
        if cancel == "shutdown":
            controller.request_shutdown()
        elif cancel:
            controller.invalidate_plan()
        release.set()
        _wait(app, lambda: not controller.busy)
        assert worker_threads == [worker_threads[0]] and worker_threads[0] != threading.get_ident()
        if cancel:
            assert not callbacks and controller.draft.shader_controls == (("Blade", controls()),)
        else:
            assert callbacks[0][0] == threading.get_ident()
            session, source = callbacks[0][1]
            controller.apply_transparency_paint(session, source.mask)
            assert controller.draft.shader_controls[0][1].transparency_mask == prepared.mask
            assert controller._variant_states[controller._active_variant].appearance.shader_controls == controller.draft.shader_controls
            with pytest.raises(ValueError, match="changed"):
                controller.apply_transparency_paint(session, source.mask)
    finally:
        release.set()
        controller.request_shutdown()
        _wait(app, lambda: not controller.iter_shutdown_workers())
        controller.deleteLater()
        app.processEvents()


def test_rust_paint_action_opens_canvas_and_apply_invalidates_plan(studio, monkeypatch):
    from cdmw.core.material_shader_controls import equipment_shader_options
    from tests.test_shader_controls import material
    _, tab, bridge = studio
    controller, panel = tab.controller, tab.model_panel
    controller._active_variant = ("fixture.prefab", PAC)
    controller.draft.shader_controls = (("Blade", controls()),)
    monkeypatch.setattr(controller, "material_parts", lambda: (("Blade", "Blade"),))
    monkeypatch.setattr(controller, "material_shader_options", lambda: equipment_shader_options(material()))
    mask = gradient()
    prepared = TransparencyPaintSource(mask, bytes([90, 120, 160, 255]) * 1024)
    monkeypatch.setattr("cdmw.services.new_item_transparency_paint.prepare_transparency_paint", lambda *_args, **_kwargs: prepared)
    panel.refresh_glow_parts()
    tab.show_step(2)
    _send(bridge, panel.inspector_tabs, "tab", 1)
    revision = controller._draft_revision
    _send(bridge, panel.shader_controls_editor.paint_mask, "activate")
    dialog = panel._transparency_painter
    try:
        dialog.canvas.stroke_committed.emit({"points": [(10, 5), (20, 5)]})
        dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).click()
        assert controller._draft_revision > revision and not controller.has_current_plan
        assert controller.draft.shader_controls[0][1].transparency_mask is not None
        _send(bridge, panel.shader_controls_editor.restore_mask, "activate")
        assert controller.draft.shader_controls[0][1].transparency_mask is None
    finally:
        from shiboken6 import isValid
        if isValid(dialog):
            dialog.close()


@pytest.mark.parametrize("mode", ["blending", "translucency"])
def test_full_plan_dmm_export_contains_private_spatial_texture(tmp_path, monkeypatch, mode):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.services.new_item_service import NewItemService
    from cdmw.services.new_item_variants import xml_path
    from tests.test_new_item_provenance import current_files, spec
    from tests.test_new_item_service import PAC as TEMPLATE_PAC, PAC_XML, build_package, _read
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    data, owned, mask = current_files(), source_files(), gradient()
    data.update({path: payload for path, payload in owned.side_files.items() if path != XML})
    data[PAC_XML] = owned.side_files[XML]
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / "fixture", data)), read_entry=_read)
    request = replace(spec(), translucency=TranslucencyChoice(("Blade",), masks=(("Blade", mask),)) if mode == "translucency" else None,
                      shader_controls=(("Blade", controls(mask)),) if mode == "blending" else ())
    entry = snapshot.entry(TEMPLATE_PAC)
    archives = {Path(path): Path(path).read_bytes() for path in (entry.pamt_path, entry.paz_file)}
    plan = service.plan(request, snapshot)
    output = next(path for path in plan.loose_files if path.endswith(".pac"))
    blade = find_material_wrappers(plan.loose_files[xml_path(output)].decode("utf-8-sig"))[0]
    parameter, channel = ("_baseColorTexture", 3) if mode == "translucency" else ("_materialTexture", 0)
    texture = blade.textures[parameter]
    service.export_loose(plan, tmp_path / "mod", manager="DMM")
    entries = parse_archive_pamt(tmp_path / "mod/0036/0.pamt")
    payload = read_archive_entry_data(next(entry for entry in entries if entry.path == texture))[0]
    assert payload == plan.loose_files[texture]
    assert len(np.unique(rgba(payload)[..., channel])) > 32
    assert texture not in data
    assert all(path.read_bytes() == content for path, content in archives.items())


def test_template_glass_preview_retains_base_role_and_resolves_owned_direct_texture(tmp_path):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.new_item_translucency import translucency_preview_mesh
    from cdmw.services.mesh_rust_authoring import _mesh_texture_payloads, _session_root_identity
    base = tmp_path / "base.dds"
    base.write_bytes(source_files().side_files["character/texture/base.dds"])
    part = SubMesh(name="Blade", material="Blade", vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                   uvs=[(0., 0.), (1., 0.), (0., 1.)], faces=[(0, 1, 2)])
    part.preview_texture_dds_path = str(base)
    part.preview_material_texture_inputs = ({"parameter_name": "_baseColorTexture", "source_texture_path": "archive/base.dds",
                                           "slot_kind": "base"},)
    mesh = ParsedMesh(path=PAC, format="pac", submeshes=[part])
    mask = gradient()
    preview = translucency_preview_mesh(mesh, TranslucencyChoice(("Blade",), masks=(("Blade", mask),)))
    output = tmp_path / "preview"
    output.mkdir()
    resources = _mesh_texture_payloads(output, preview, expected_root_identity=_session_root_identity(output))
    assert {row["role"] for row in resources} == {"base_color"}
    pixels = rgba((output / resources[0]["file"]["path"]).read_bytes())
    assert np.array_equal(pixels[..., 3], 255 - np.frombuffer(mask.pixels, dtype=np.uint8).reshape(16, 64))
    assert part.preview_texture_dds_path == str(base)


@pytest.mark.parametrize("mode", ["blending", "translucency"])
def test_variant_switch_restores_the_owning_mask(monkeypatch, mode):
    app = QApplication.instance() or QApplication([])
    controller = _controller()
    first, second = controller._active_variant, ("second.prefab", "character/model/second.pac")
    monkeypatch.setattr(controller, "variant_choices", lambda: ((first, "First"), (second, "Second")))
    mask = gradient()
    if mode == "blending":
        controller.draft.shader_controls = (("Blade", controls(mask)),)
    else:
        controller.draft.shader_controls = ()
        controller.draft.translucency = TranslucencyChoice(("Blade",), masks=(("Blade", mask),))
    try:
        controller.select_variant(second)
        assert controller.draft.translucency is None and not controller.draft.shader_controls
        controller.select_variant(first)
        actual = (controller.draft.translucency.mask_for("Blade") if mode == "translucency"
                  else controller.draft.shader_controls[0][1].transparency_mask)
        assert actual == mask
    finally:
        controller.request_shutdown()
        _wait(app, lambda: not controller.iter_shutdown_workers())
        controller.deleteLater()
        app.processEvents()


def test_shared_atlas_is_rejected_before_a_mask_can_reach_other_parts(tmp_path):
    from tests.test_new_item_texture_fidelity import write_gltf, export_materials
    Image.new("RGBA", (16, 16), (120, 170, 90, 255)).save(tmp_path / "base.png")
    materials = [{"name": name, "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
                 for name in ("Glass", "Gem")]
    path = write_gltf(tmp_path, materials, ["base.png"])
    mask = gradient()
    with pytest.raises(ValueError, match="atlas parts separately"):
        export_materials(path, tmp_path, atlas=True, socket_attached=True,
            translucency=TranslucencyChoice(("Glass", "Gem"), masks=(("Glass", mask), ("Gem", mask))))


@pytest.mark.parametrize("font_size", [12, 20])
@pytest.mark.parametrize("language", ["en", "de", "fr", "ru"])
def test_painter_controls_fit_compact_window_and_large_fonts(font_size, language, tmp_path):
    from PySide6.QtGui import QFont
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
    app = QApplication.instance() or QApplication([])
    mask = gradient()
    prepared = TransparencyPaintSource(mask, bytes([90, 120, 160, 255]) * 1024)
    dialog = TransparencyPaintDialog(prepared, lambda _mask: None, part="Blade")
    try:
        localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code=language)
        localizer.apply(dialog)
        assert dialog.more.text() == localizer.translate("More transparent")
        font = QFont("Segoe UI")
        font.setPixelSize(font_size)
        dialog.setFont(font)
        dialog.resize(960, 720)
        dialog.show()
        app.processEvents()
        assert dialog.width() <= 960 and dialog.height() <= 720
        assert dialog.canvas.parentWidget().height() >= 160
        for widget in (dialog.more, dialog.less, dialog.undo_button, dialog.redo_button, dialog.value, dialog.brush_size, dialog.view):
            assert widget.isVisibleTo(dialog)
            assert widget.geometry().right() < dialog.width()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
