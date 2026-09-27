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
from PIL import Image, ImageOps
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
from tests.test_new_item_model_apply import studio as model_studio


@pytest.mark.parametrize("target", ["colour", "surface", "linked"])
@pytest.mark.parametrize("calibrated", [False, True])
def test_independent_eye_masks_preserve_exact_channels_before_encoding(target, calibrated, monkeypatch):
    from cdmw.core import texture_native
    files, mask = source_files(), gradient()
    selected = replace(controls(), transparency_mask=mask if target != "surface" else None,
        surface_response_mask=mask if target != "colour" else None,
        coverage_mapping="calibrated_v1" if calibrated else "raw", colour_coverage=254 / 255 if calibrated else None)
    before = dict(files.side_files)
    encoded = []
    real_encode = texture_native.encode_dds_with_directxtex
    def encode(source, output, **kwargs):
        encoded.append(np.asarray(Image.open(source).convert("RGBA")))
        return real_encode(source, output, **kwargs)
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", encode)
    output = apply_shader_controls(files, (("Blade", selected),))
    blade, gem = find_material_wrappers(output.side_files[XML].decode())
    old_blade, old_gem = find_material_wrappers(before[XML].decode())
    assert output.side_files[XML].decode()[gem.start:gem.end] == before[XML].decode()[old_gem.start:old_gem.end]
    assert files.side_files == before
    alpha, material = encoded
    if target != "colour":
        assert np.array_equal(alpha[..., 0], 255 - np.frombuffer(mask.pixels, dtype=np.uint8).reshape(16, 64))
    assert (alpha[..., 1:] == 255).all()
    original = np.asarray(Image.open(BytesIO(before[SP])).convert("RGBA").resize((material.shape[1], material.shape[0]), Image.Resampling.BILINEAR))
    assert np.array_equal(material[..., 1:], original[..., 1:])
    if target != "surface":
        assert np.array_equal(material[..., 0], np.frombuffer(selected.colour_mask_for_output().pixels, dtype=np.uint8).reshape(16, 64))
    for parameter, expected in (("_alphaTexture", alpha), ("_materialTexture", material)):
        actual = rgba(output.side_files[blade.textures[parameter]])
        error = np.abs(actual.astype(int) - expected.astype(int)).max()
        assert error <= 6, f"Measured BC7 maximum channel error {error}/255"
    assert gem.textures == old_gem.textures
    restored = apply_shader_controls(files, (("Blade", controls()),))
    assert find_material_wrappers(restored.side_files[XML].decode())[0].textures["_materialTexture"] != blade.textures["_materialTexture"] or target == "surface"


def test_two_mask_painter_links_atomically_and_keeps_untouched_target_inherited():
    from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
    app = QApplication.instance() or QApplication([])
    initial = TransparencyMask(32, 16, bytes(512))
    surface = TransparencyMask(16, 8, bytes([80]) * 128)
    prepared = TransparencyPaintSource(initial, bytes([90, 120, 160, 255]) * 512, surface, controls())
    accepted = []
    dialog = TransparencyPaintDialog(prepared, accepted.append, part="Blade")
    try:
        dialog.target.setCurrentIndex(1)
        dialog.value.setValue(140)
        dialog.fill_button.click()
        assert dialog._history[-1] == initial.pixels
        dialog.target.setCurrentIndex(0)
        dialog.target.setCurrentIndex(1)
        assert set(dialog._surface_history[-1]) == {140}
        dialog.target.setCurrentIndex(2)
        dialog.invert_button.click()
        assert set(dialog._history[-1]) == {255}
        assert set(dialog._surface_history[-1]) == {115}
        dialog.undo_button.click()
        assert dialog._history[dialog._history_index] == initial.pixels
        assert set(dialog._surface_history[dialog._history_index]) == {140}
        dialog.redo_button.click()
        dialog.undo_button.click()
        dialog.target.setCurrentIndex(1)
        dialog._apply()
        assert accepted[0].transparency_mask is None
        assert accepted[0].surface_response_mask == TransparencyMask(16, 8, bytes([140]) * 128)
        assert prepared.surface_mask == surface
    finally:
        dialog.close(); dialog.deleteLater(); app.processEvents()


def test_painter_prepares_two_lossless_masks_without_export_encoding(monkeypatch):
    from cdmw.core import texture_native
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", lambda *_a, **_k: pytest.fail("Painter preparation must not encode EyeCover output"))
    files, mask = source_files(), gradient()
    selected = replace(controls(mask), surface_response_mask=TransparencyMask(8, 8, bytes([33]) * 64))
    appearance = VariantAppearance("fixture.prefab", PAC, shader_controls=(("Blade", selected),))
    prepared = prepare_transparency_paint(snapshot_for(files), appearance, "Blade", "blending")
    assert prepared.mask == mask and prepared.surface_mask == selected.surface_response_mask
    assert prepared.controls == selected


@pytest.mark.parametrize("alpha_mode", ["OPAQUE", "BLEND"])
@pytest.mark.parametrize("saved", [False, True])
def test_imported_glass_painter_reads_source_alpha_without_exporting_textures(tmp_path, monkeypatch, alpha_mode, saved):
    from cdmw.core import texture_native
    from cdmw.modding.scene_importer import import_scene_mesh_with_report
    from cdmw.services.new_item_variants import variant_bindings, xml_path
    from tests.test_new_item_provenance import setup_game
    from tests.test_new_item_service import TEMPLATE
    from tests.test_new_item_texture_fidelity import write_gltf

    _, snapshot, _ = setup_game(tmp_path)
    binding, model_path = next(iter(variant_bindings(snapshot.family(TEMPLATE))))
    Image.new("RGBA", (24, 12), (100, 150, 200, 128)).save(tmp_path / "colour.png")
    scene = import_scene_mesh_with_report(write_gltf(tmp_path, [{
        "name": "Glass", "alphaMode": alpha_mode,
        "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "baseColorFactor": [1, 1, 1, 0.5]},
    }], ["colour.png"]))
    files = source_files()
    result = SimpleNamespace(rebuilt_data=files.pac_data,
        supplemental_file_specs=tuple(SimpleNamespace(target_path=xml_path(model_path) if key == XML else key, payload_data=data)
                                      for key, data in files.side_files.items()),
        source_owned_output_draw_sections=(SimpleNamespace(target_submesh_name="Blade", source_material_name="Glass"),))
    mask = gradient() if saved else None
    appearance = VariantAppearance(binding.prefab_path, model_path, custom_model=True,
        material_route=MaterialRoute.PLAIN_PBR.value, glow_parts=("Glass",),
        translucency=TranslucencyChoice.from_settings({"Glass": (.4, .6)}, {"Glass": (.9, 0)}, {"Glass": mask}))
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex",
                        lambda *_a, **_k: pytest.fail("Opening the painter must not export material textures"))
    prepared = prepare_transparency_paint(snapshot, appearance, "Glass", "translucency",
        template_key=TEMPLATE, result=result, scene=scene)
    if saved:
        assert prepared.mask == mask
    else:
        assert (prepared.mask.width, prepared.mask.height) == (24, 12)
        assert set(prepared.mask.pixels) == ({0} if alpha_mode == "OPAQUE" else {191})
    assert len(prepared.reference_rgba) == prepared.mask.width * prepared.mask.height * 4
    assert files == source_files()


@pytest.mark.parametrize("base_parameter", ["_baseColorTexture", "_overlayColorTexture"])
def test_prebuilt_glass_painter_keeps_alpha_without_encoding_surface_overrides(monkeypatch, base_parameter):
    from cdmw.core import texture_native
    from cdmw.services.new_item_planning import NewItemPlanError

    files = source_files()
    files = replace(files, side_files={**files.side_files,
        XML: files.side_files[XML].replace(b"_baseColorTexture", base_parameter.encode())})
    appearance = VariantAppearance("fixture.prefab", PAC, custom_model=True,
        material_route=MaterialRoute.PLAIN_PBR.value,
        translucency=TranslucencyChoice.from_settings({"Blade": (.4, .6)}, {"Blade": (.9, 0)}))
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex",
                        lambda *_a, **_k: pytest.fail("Opening the painter must not export material textures"))
    prepared = prepare_transparency_paint(snapshot_for(files), appearance, "Blade", "translucency", result=files)
    assert (prepared.mask.width, prepared.mask.height) == (8, 8)
    expected = ImageOps.invert(Image.open(BytesIO(files.side_files["character/texture/base.dds"])).getchannel("A"))
    assert prepared.mask.pixels == expected.tobytes()
    with pytest.raises(NewItemPlanError, match="Enable Plain PBR materials"):
        prepare_transparency_paint(snapshot_for(files), replace(appearance, material_route=MaterialRoute.BUILDER.value),
                                   "Blade", "translucency", result=files)


def test_linked_fill_authors_both_inherited_masks_even_when_pixels_already_match():
    from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
    app = QApplication.instance() or QApplication([])
    mask = TransparencyMask(8, 8, bytes(64))
    prepared = TransparencyPaintSource(mask, bytes([90, 120, 160, 255]) * 64, mask, controls())
    accepted = []
    dialog = TransparencyPaintDialog(prepared, accepted.append, part="Blade")
    try:
        dialog.target.setCurrentIndex(2)
        dialog.value.setValue(0)
        dialog.fill_button.click()
        dialog._apply()
        assert accepted[0].transparency_mask == mask
        assert accepted[0].surface_response_mask == mask
    finally:
        dialog.close(); dialog.deleteLater(); app.processEvents()


def test_mask_png_import_export_checks_layout_channel_orientation_and_cancel(tmp_path):
    from cdmw.services.transparency_masks import read_mask_image, write_mask_image
    mask, path = gradient(), tmp_path / "mask.png"
    write_mask_image(path, mask)
    assert read_mask_image(path, (64, 16)) == mask
    before = path.read_bytes()
    stop = threading.Event(); stop.set()
    with pytest.raises(RunCancelled):
        write_mask_image(path, TransparencyMask(64, 16, bytes(1024)), stop_event=stop)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="never stretched"):
        read_mask_image(path, (16, 64))
    Image.new("RGBA", (64, 16), (32, 64, 128, 192)).save(path)
    with pytest.raises(ValueError, match="explicit"):
        read_mask_image(path, (64, 16))
    assert set(read_mask_image(path, (64, 16), "B").pixels) == {128}
    exif = Image.Exif(); exif[274] = 6
    Image.new("L", (64, 16)).save(path, exif=exif)
    with pytest.raises(ValueError, match="orientation"):
        read_mask_image(path, (64, 16))


@pytest.mark.parametrize("mode", ["I;16", "P"])
def test_mask_import_rejects_implicit_bit_depth_and_palette_conversion(tmp_path, mode):
    from cdmw.services.transparency_masks import read_mask_image
    path = tmp_path / "mask.png"
    Image.new(mode, (64, 16)).save(path)
    with pytest.raises(ValueError, match="8-bit grayscale, RGB or RGBA"):
        read_mask_image(path, (64, 16), "R")


@pytest.mark.parametrize("pattern", ["keep", "remove", "half", "hole", "gradient"])
def test_cutout_recipe_endpoints_mips_and_bc7_decode(pattern):
    from cdmw.services.transparency_masks import cutout_mips, encode_cutout_texture
    from cdmw.core.dds_native import inspect_dds_native
    pixels = np.zeros((16, 64), dtype=np.uint8)
    if pattern == "remove": pixels[:] = 255
    if pattern == "half": pixels[:, 32:] = 255
    if pattern == "hole": pixels[6:10, 30:34] = 255
    if pattern == "gradient": pixels[:] = np.arange(64) * 4
    mask = TransparencyMask(64, 16, pixels.tobytes())
    mips = list(cutout_mips(mask))
    expected = pixels / 255 > .50025
    for index, image in enumerate(mips):
        channels = np.asarray(image)
        assert (channels[..., 0] == 255).all() and (channels[..., 1] == 0).all()
        # Actual two-channel shader equation, including the differently scaled red sample.
        cut = np.clip(2 * np.clip(2 * (channels[..., 2] / 255) - .5, 0, 1) - channels[..., 0] / 255, 0, 1) > .001
        if index == 0:
            assert np.array_equal(cut, expected)
        assert abs(cut.mean() - expected.mean()) <= .5 / cut.size + 1e-12
    encoded = encode_cutout_texture(mask)
    info = inspect_dds_native(encoded)
    assert info.format_name == "BC7_UNORM" and len(info.mip_levels) == len(mips) == 7
    import struct
    for level, expected_mip in zip(info.mip_levels, mips):
        header = bytearray(encoded[:148])
        struct.pack_into("<II", header, 12, level.height, level.width)
        struct.pack_into("<I", header, 28, 1)
        decoded_mip = rgba(bytes(header) + encoded[level.offset:level.offset + level.byte_count])
        assert np.abs(decoded_mip.astype(int) - np.asarray(expected_mip).astype(int)).max() <= 3
    actual = rgba(encoded)
    assert np.abs(actual.astype(int) - np.asarray(mips[0]).astype(int)).max() <= 3
    cut = np.clip(2 * np.clip(2 * (actual[..., 2] / 255) - .5, 0, 1) - actual[..., 0] / 255, 0, 1) > .001
    assert np.array_equal(cut, expected)


def test_cutout_export_and_preview_share_recipe_and_preserve_raw_reveal(tmp_path):
    from cdmw.services.shader_controls_preview import shader_preview_mesh
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    files, mask = source_files(), gradient()
    selected = ShaderControls("SkinnedMeshWing", (("_wingFlowProgress", (1.25,)),), cutout_mask=mask)
    output = apply_shader_controls(files, (("Blade", selected),))
    blade, gem = find_material_wrappers(output.side_files[XML].decode())
    assert blade.shader == "SkinnedMeshWing" and blade.value("_wingFlowProgress") == "0.5"
    assert blade.value("_wingFlowInverse") == "0"
    assert all(blade.textures[name] == find_material_wrappers(files.side_files[XML].decode())[0].textures[name]
               for name in ("_baseColorTexture", "_materialTexture"))
    assert gem.shader == "SkinnedMeshEmissive"
    mesh = ParsedMesh(path=PAC, format="pac", submeshes=[SubMesh(name="Blade", material="Blade")])
    preview = shader_preview_mesh(mesh, (("Blade", selected),), plain_pbr=True)
    binding = next(item for item in preview.submeshes[0].preview_material_texture_inputs if item.parameter_name == "_wingFlowTex1")
    assert np.abs(rgba(Path(binding.source_dds_path).read_bytes()).astype(int) - rgba(output.side_files[blade.textures["_wingFlowTex1"]]).astype(int)).max() <= 3
    assert preview_factors(selected)[4:6] == (.5, 0.) and preview_factors(selected)[30] == 1.
    assert preview_factors(replace(selected, cutout_mask=None))[4] == 1.25


@pytest.mark.parametrize("mode", ["blending", "translucency"])
def test_template_preview_transports_authored_channels_through_native_graph(tmp_path, mode):
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
    from cdmw.services.shader_controls_preview import shader_preview_mesh
    from cdmw.services.new_item_translucency import translucency_preview_mesh
    from cdmw.services.mesh_rust_preview_package import build_rust_preview_package
    import json
    source = tmp_path / "native_source"; source.mkdir()
    files = source_files()
    base, material_path = source / "base.dds", source / "material.dds"
    base.write_bytes(files.side_files["character/texture/base.dds"])
    material_path.write_bytes(files.side_files[SP])
    parts = []
    for index, name in enumerate(("Blade", "Gem")):
        part = SubMesh(name=name, material=name, vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                       uvs=[(0., 0.), (1., 0.), (0., 1.)], faces=[(0, 1, 2)])
        part.preview_texture_dds_path = str(base)
        part.preview_material_texture_dds_path = str(material_path)
        part.preview_material_texture_inputs = tuple(SimpleNamespace(parameter_name=parameter, source_texture_path=str(path),
            source_dds_path=str(path), preview_texture_path=str(path), material_name=name, submesh_name=name,
            owner_slot_index=index, binding_authority="authoritative")
            for parameter, path in (("_baseColorTexture", base), ("_materialTexture", material_path)))
        part.preview_native_material_overrides = {"preview_core_material_source": {
            "package": str(source), "conservation": {"conserved": True, "declared_parameter_count": 2, "transported_parameter_count": 2},
            "batch": {"index": index, "material_name": name, "base_color": [1., 1., 1.], "material_layers": [{
                "material_wrapper_index": index, "owner_wrapper_item_id": str(index + 100), "layer_role": "base",
                "diffuse_source": "base.dds", "material_source": "material.dds", "source_parameter": "_baseColorTexture"}]}}}
        parts.append(part)
    mesh = ParsedMesh(path=PAC, format="pac", submeshes=parts)
    selected = replace(controls(gradient()), surface_response_mask=gradient())
    preview = (shader_preview_mesh(mesh, (("Blade", selected),)) if mode == "blending" else
               translucency_preview_mesh(mesh, TranslucencyChoice(("Blade",), masks=(("Blade", gradient()),))))
    package = build_rust_preview_package(preview, output_root=tmp_path / "packages")
    data = json.loads(package.manifest_path.read_text())
    graph = data["preview_core_material_graph"]["materials"]
    assert graph[0]["authoring_channels"] == (2 if mode == "blending" else 1)
    assert "authoring_channels" not in graph[1]
    assert graph[0]["layers"][0]["owner_wrapper_item_id"] == "100"
    role = "material" if mode == "blending" else "base_color"
    resource = next(row for row in data["textures"] if row["role"] == role and row["material_indices_by_lod"] == [[0]])
    pixels = rgba((package.package_dir / resource["file"]["path"]).read_bytes())
    expected = np.frombuffer(gradient().pixels, dtype=np.uint8).reshape(16, 64)
    assert np.array_equal(pixels[..., 0 if mode == "blending" else 3], expected if mode == "blending" else 255 - expected)
    if mode == "blending":
        surface = next(row for row in data["textures"] if row["role"] == "shader_mask" and row["material_indices_by_lod"] == [[0]])
        assert np.array_equal(rgba((package.package_dir / surface["file"]["path"]).read_bytes())[..., 0], 255 - expected)
    assert "painted_texture_channels" not in parts[0].preview_native_material_overrides


@pytest.mark.parametrize("ending", ["apply", "close", "stale"])
def test_mask_file_worker_is_cancelled_on_close_and_rejects_stale_drafts(ending):
    from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
    from cdmw.domain.cancellation import raise_if_cancelled
    app = QApplication.instance() or QApplication([])
    controller = _controller()
    controller.draft.shader_controls = (("Blade", controls()),)
    session = (controller.snapshot, controller.current_variant_identity(), controller.model_import,
               controller.model_result, controller._draft_revision, "Blade", "blending")
    prepared = TransparencyPaintSource(gradient(), bytes([90, 120, 160, 255]) * 1024)
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()
    dialog = TransparencyPaintDialog(prepared, lambda mask: controller.apply_transparency_paint(session, mask), part="Blade",
        run_file_task=lambda task, done, failed: controller.start_transparency_mask_io(session, task, done, failed),
        cancel_file_task=lambda: controller.cancel_operation("transparency_mask"))
    worker_threads = []
    def task(_log, stop_event):
        worker_threads.append(threading.get_ident()); started.set()
        try:
            while not release.wait(.005):
                raise_if_cancelled(stop_event)
            raise_if_cancelled(stop_event)
            return TransparencyMask(64, 16, bytes([123]) * 1024)
        finally:
            stopped.set()
    try:
        dialog._file_task(task, lambda mask: dialog._remember(mask.pixels))
        _wait(app, started.is_set)
        assert worker_threads != [threading.get_ident()]
        assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Apply).isEnabled()
        if ending == "close":
            dialog.reject()
        if ending == "stale":
            controller._draft_revision += 1
        release.set()
        _wait(app, lambda: stopped.is_set() and not controller.iter_shutdown_workers())
        if ending == "apply":
            assert set(dialog._history[-1]) == {123}
            dialog._apply()
            assert set(controller.draft.shader_controls[0][1].transparency_mask.pixels) == {123}
        else:
            assert controller.draft.shader_controls[0][1].transparency_mask is None
            assert dialog._history == [prepared.mask.pixels]
    finally:
        release.set(); dialog.close(); controller.request_shutdown()
        _wait(app, lambda: not controller.iter_shutdown_workers())
        dialog.deleteLater(); controller.deleteLater(); app.processEvents()


def test_cutout_cancellation_during_mips_never_publishes_model_changes(monkeypatch):
    from cdmw.core import texture_native
    files = source_files(); original = dict(files.side_files)
    stop = threading.Event()
    real_encode = texture_native.encode_dds_with_directxtex
    def cancel_after_mip(*args, **kwargs):
        result = real_encode(*args, **kwargs)
        stop.set()
        return result
    monkeypatch.setattr(texture_native, "encode_dds_with_directxtex", cancel_after_mip)
    with pytest.raises(RunCancelled):
        apply_shader_controls(files, (("Blade", ShaderControls("SkinnedMeshWing", cutout_mask=gradient())),), stop_event=stop)
    assert files.side_files == original


def test_surface_restore_does_not_clear_colour_or_calibration():
    from cdmw.ui.new_item.shader_controls_editor import ShaderControlsEditor
    app = QApplication.instance() or QApplication([])
    selected = replace(controls(gradient()), surface_response_mask=gradient(), coverage_mapping="calibrated_v1", colour_coverage=128 / 255)
    editor = ShaderControlsEditor(); changed = []
    try:
        editor.refresh((("Blade", "Blade"),), (("Blade", selected),))
        editor.changed.connect(changed.append)
        assert not next(row for row in editor._rows if row[0].name == "surface_alpha")[1].isEnabled()
        editor.restore_surface_channel.click()
        actual = changed[-1][0][1]
        assert actual.surface_response_mask is None
        assert actual.transparency_mask == selected.transparency_mask
        assert actual.colour_coverage == selected.colour_coverage
        editor.restore_colour_channel.click()
        assert changed[-1][0][1].coverage_mapping == "raw" and changed[-1][0][1].transparency_mask is None
    finally:
        editor.deleteLater(); app.processEvents()


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


@pytest.mark.parametrize("textured", [False, True])
@pytest.mark.parametrize("alpha_mode", ["OPAQUE", "BLEND"])
def test_painted_glass_preview_matches_export_with_source_colour_and_alpha(tmp_path, textured, alpha_mode):
    from tests.test_new_item_texture_fidelity import write_gltf, export_materials, pixels
    from cdmw.ui.new_item.model_import import load_model_import_source
    from cdmw.services.new_item_translucency import translucency_preview_mesh
    from cdmw.services.mesh_rust_authoring import _mesh_texture_payloads, _mesh_material_presentations, _session_root_identity

    colour, source_alpha = [.3, .5, .7], .2
    pbr = {"baseColorFactor": [*colour, source_alpha]}
    if textured:
        Image.new("RGBA", (64, 16), (100, 150, 190, 45)).save(tmp_path / "base.png")
        pbr["baseColorTexture"] = {"index": 0}
    path = write_gltf(tmp_path, [{"name": name, "alphaMode": alpha_mode, "pbrMetallicRoughness": pbr}
                               for name in ("Unpainted", "Glass")], ["base.png"] if textured else [])
    mask = gradient()
    choice = TranslucencyChoice(("Glass",), masks=(("Glass", mask),))
    source = load_model_import_source(path)
    try:
        mesh = source.baked_preview_mesh()
        original = _mesh_material_presentations(mesh)
        preview = translucency_preview_mesh(mesh, choice)
        presentations = _mesh_material_presentations(preview)
        assert presentations[1]["opacity"] == 1., "The mask replaces source alpha, including its scalar factor."
        assert presentations[1]["alpha_mode"] == "blend"
        assert presentations[1]["texture_tint"] == pytest.approx(colour)
        assert presentations[1]["base_tint_strength"] == 0.
        assert presentations[0] == original[0], "Other parts must retain their authored alpha."
        assert _mesh_material_presentations(mesh) == original, "Painting must not change the reusable import."

        output = tmp_path / "preview"
        output.mkdir()
        resources = _mesh_texture_payloads(output, preview, expected_root_identity=_session_root_identity(output))
        resource = next(row for row in resources if row["role"] == "base_color" and row["material_indices_by_lod"] == [[1]])
        actual = rgba((output / resource["file"]["path"]).read_bytes())
        expected = 255 - np.frombuffer(mask.pixels, dtype=np.uint8).reshape(mask.height, mask.width)
        assert np.array_equal(actual[..., 3], expected)
        assert (actual[..., :3] == ([100, 150, 190] if textured else [255, 255, 255])).all()

        _, files, wrappers = export_materials(path, tmp_path, translucency=choice)
        exported = pixels(files, wrappers["Glass"])
        assert np.abs(exported[..., 3].astype(int) - actual[..., 3]).max() <= 3
        restored = translucency_preview_mesh(mesh, replace(choice, masks=()))
        assert _mesh_material_presentations(restored)[1]["opacity"] == source_alpha
    finally:
        source.cleanup()


def test_painted_glass_rejects_an_unavailable_declared_base_texture(tmp_path):
    from cdmw.services.transparency_masks import preview_masked_part

    part = SimpleNamespace(name="Glass", material="Glass", preview_texture_path=str(tmp_path / "missing.png"))
    with pytest.raises(ValueError, match="preview texture is unavailable"):
        preview_masked_part(part, gradient(), glass=True)


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
@pytest.mark.parametrize("toggle_glow", [False, True])
def test_painter_opens_after_async_placement_without_a_glow_reset(model_studio, monkeypatch, mode, toggle_glow):
    from cdmw.modding.scene_material_audit import ImportedMaterialBinding
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
    from tests.test_new_item_model_apply import _import

    app, tab = model_studio
    source = _import(tab)
    source.scene = replace(source.scene, material_bindings=(ImportedMaterialBinding(material_name="Blade", submesh_index=0),))
    controller, panel = tab.controller, tab.model_panel
    controller._material_parts = ()
    controller.draft.material_route = MaterialRoute.PLAIN_PBR
    controller.draft.glow_parts = ("Blade",)
    if mode == "blending":
        controller.draft.shader_controls = (("Blade", controls()),)
    else:
        controller.draft.translucency = TranslucencyChoice(("Blade",))
    controller.invalidate_plan()
    panel.refresh_glow_parts()
    tab.show_step(2)
    tab.show()
    bridge = NewItemPresentationBridge(tab)
    _send(bridge, panel.inspector_tabs, "tab", 1)
    button = (panel.shader_controls_editor if mode == "blending" else panel.translucency_editor).paint_mask
    messages = []
    controller.status_message.connect(lambda text, _error: messages.append(text))
    _send(bridge, button, "activate")
    _wait(app, lambda: not controller.busy)
    assert any("Apply the placement" in message for message in messages)
    assert button.isEnabled()
    built = source_files()
    monkeypatch.setattr("cdmw.ui.new_item.controller.build_placed_import", lambda *_a, **_k: built)
    _send(bridge, panel.apply_button, "activate")
    _wait(app, lambda: not controller.busy)
    assert controller.model_result is built
    _send(bridge, panel.inspector_tabs, "tab", 1)
    assert button.isEnabled()
    if toggle_glow:
        _send(bridge, panel.glow_box, "toggle", False)
        _send(bridge, panel.glow_box, "toggle", True)
    _send(bridge, button, "activate")
    _wait(app, lambda: not controller.busy)
    dialog = panel._transparency_painter
    try:
        assert dialog.isVisible()
        assert button.isEnabled()
        assert panel.operation_banner.isHidden()
    finally:
        dialog.close()


@pytest.mark.parametrize("mode", ["blending", "surface", "linked", "cutout", "translucency"])
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
    shaders = ShaderControls("SkinnedMeshWing", cutout_mask=mask) if mode == "cutout" else replace(
        controls(mask if mode in {"blending", "linked"} else None), surface_response_mask=mask if mode in {"surface", "linked"} else None)
    request = replace(spec(), translucency=TranslucencyChoice(("Blade",), masks=(("Blade", mask),)) if mode == "translucency" else None,
                      shader_controls=(("Blade", shaders),) if mode != "translucency" else ())
    entry = snapshot.entry(TEMPLATE_PAC)
    archives = {Path(path): Path(path).read_bytes() for path in (entry.pamt_path, entry.paz_file)}
    plan = service.plan(request, snapshot)
    output = next(path for path in plan.loose_files if path.endswith(".pac"))
    blade = find_material_wrappers(plan.loose_files[xml_path(output)].decode("utf-8-sig"))[0]
    parameter, channel = ({"translucency": ("_baseColorTexture", 3), "surface": ("_alphaTexture", 0),
                           "cutout": ("_wingFlowTex1", 2)}.get(mode, ("_materialTexture", 0)))
    texture = blade.textures[parameter]
    service.export_loose(plan, tmp_path / "mod", manager="DMM")
    entries = parse_archive_pamt(tmp_path / "mod/0036/0.pamt")
    payload = read_archive_entry_data(next(entry for entry in entries if entry.path == texture))[0]
    assert payload == plan.loose_files[texture]
    if mode == "linked":
        surface = blade.textures["_alphaTexture"]
        assert read_archive_entry_data(next(entry for entry in entries if entry.path == surface))[0] == plan.loose_files[surface]
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


@pytest.mark.parametrize("mode", ["blending", "surface", "linked", "cutout", "translucency"])
def test_variant_switch_restores_the_owning_mask(monkeypatch, mode):
    app = QApplication.instance() or QApplication([])
    controller = _controller()
    first, second = controller._active_variant, ("second.prefab", "character/model/second.pac")
    monkeypatch.setattr(controller, "variant_choices", lambda: ((first, "First"), (second, "Second")))
    mask = gradient()
    if mode != "translucency":
        selected = ShaderControls("SkinnedMeshWing", cutout_mask=mask) if mode == "cutout" else replace(
            controls(mask if mode in {"blending", "linked"} else None), surface_response_mask=mask if mode in {"surface", "linked"} else None)
        controller.draft.shader_controls = (("Blade", selected),)
    else:
        controller.draft.shader_controls = ()
        controller.draft.translucency = TranslucencyChoice(("Blade",), masks=(("Blade", mask),))
    try:
        controller.select_variant(second)
        assert controller.draft.translucency is None and not controller.draft.shader_controls
        controller.select_variant(first)
        actual = (controller.draft.translucency.mask_for("Blade") if mode == "translucency"
                  else controller.draft.shader_controls[0][1].cutout_mask if mode == "cutout"
                  else controller.draft.shader_controls[0][1].surface_response_mask if mode == "surface"
                  else controller.draft.shader_controls[0][1].transparency_mask)
        assert actual == mask
        if mode != "translucency":
            assert ShaderControls.from_dict(controller.draft.shader_controls[0][1].to_dict()) == selected
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
@pytest.mark.parametrize("dual", [False, True])
def test_painter_controls_fit_compact_window_and_large_fonts(font_size, language, dual, tmp_path):
    from PySide6.QtGui import QFont
    from cdmw.ui.localization import UiLocalizer
    from cdmw.ui.new_item.transparency_painter import TransparencyPaintDialog
    app = QApplication.instance() or QApplication([])
    mask = gradient()
    prepared = TransparencyPaintSource(mask, bytes([90, 120, 160, 255]) * 1024,
        mask if dual else None, controls() if dual else None)
    dialog = TransparencyPaintDialog(prepared, lambda _mask: None, part="Blade",
        run_file_task=(lambda *_args: True) if dual else None)
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
        if dual:
            for widget in (dialog.target, dialog.import_button, dialog.export_button, dialog.import_channel):
                assert widget.isVisibleTo(dialog)
                assert widget.geometry().right() < dialog.width()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
