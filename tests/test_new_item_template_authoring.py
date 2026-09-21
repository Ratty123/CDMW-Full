"""Template-only appearance/placement reaches owned output without modifying its source."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pac_xml_standard_material import find_material_wrappers, TRANSLUCENT_SHADER
from cdmw.domain.new_item.spec import GlowChoice, ModelSource
from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.new_item_service import NewItemService
from cdmw.services.new_item_template_model import prepare_template_model
from cdmw.services.new_item_variants import xml_path
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.model_import import ModelPlacement
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import build_package, _read, TEMPLATE, OTHER, PAC, PAC_XML
from tests.test_new_item_variant_authoring import selections
from tests.test_pac_xml_standard_material import SIDECAR, GLOWING, TEMPLATE as UNTOUCHED_WRAPPER
from tests.test_static_skin_weight_export import _skinned_pac


@pytest.fixture
def template_game(tmp_path):
    files = current_files()
    files[PAC], mesh = _skinned_pac()
    files[PAC_XML] = SIDECAR.encode("utf-8")
    entries = parse_archive_pamt(build_package(tmp_path / "game", files))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read), files, mesh


@pytest.mark.parametrize("variant", [False, True])
def test_template_appearance_and_placement_survive_plan_and_pac_reparse(template_game, variant):
    service, snapshot, original, mesh = template_game
    blade = find_material_wrappers(SIDECAR)[0].submesh_name
    glow = GlowChoice(parts=(blade,), color=(1, 0, 0), intensity=6)
    glass = TranslucencyChoice((blade,), 0.2, 0.4)
    placement = ModelPlacement(offset=(0.4, -0.2, 0.1), rotation=(0, 90, 0), scale=(1.5, 0.8, 1.2))
    choice = replace(spec(), glow=glow, translucency=glass, template_transform=tuple(placement.matrix()))
    if variant:
        binding = next(item for item in selections(snapshot) if item.model_path == PAC)
        choice = replace(choice, variants=(replace(binding, glow_parts=glow.parts,
            glow_color=glow.color, glow_intensity=glow.intensity, translucency=glass,
            template_transform=choice.template_transform),))
    assert choice.model_source is ModelSource.TEMPLATE
    assert choice.needs_own_family
    plan = service.plan(choice, snapshot)
    if variant:
        out_path = next(row["output_model"] for row in plan.manifest["variants"] if row["model_path"] == PAC)
    else:
        out_path = next(path for path in plan.loose_files if path.endswith("/" + plan.spec.stem + ".pac"))
    actual = parse_pac(plan.loose_files[out_path], out_path)
    np.testing.assert_allclose(actual.submeshes[0].vertices,
        [placement.apply(point) for point in mesh.submeshes[0].vertices], atol=2e-4)
    assert actual.submeshes[0].faces == mesh.submeshes[0].faces
    assert actual.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices
    assert actual.submeshes[0].bone_weights == mesh.submeshes[0].bone_weights
    np.testing.assert_allclose(actual.submeshes[0].uvs, mesh.submeshes[0].uvs, atol=1e-5)
    xml = plan.loose_files[xml_path(out_path)].decode("utf-8")
    assert GLOWING in xml and UNTOUCHED_WRAPPER in xml
    row = find_material_wrappers(xml)[0]
    assert row.shader == TRANSLUCENT_SHADER
    assert row.textures["_baseColorTexture"] == find_material_wrappers(SIDECAR)[0].textures["_baseColorTexture"]
    assert '_value="6.000000"' in xml and '_value="#ff0000ff"' in xml.lower()
    assert '_value="0.200000"' in xml and '_value="0.400000"' in xml
    assert row.textures["_emissiveIntensityTexture"] in plan.loose_files
    assert snapshot.payload(PAC) == original[PAC]
    assert snapshot.payload(PAC_XML) == original[PAC_XML]


def test_template_glow_keeps_an_authored_emission_mask(template_game):
    _, snapshot, original, _ = template_game
    row = find_material_wrappers(SIDECAR)[1]
    files = prepare_template_model(snapshot, [PAC], glow=GlowChoice((row.submesh_name,), (0, 0, 1), 2))
    changed = find_material_wrappers(files.side_files[PAC_XML].decode("utf-8"))[1]
    assert changed.textures == row.textures
    assert changed.shader == "SkinnedMeshEmissive_Ver2"
    assert not any(path.endswith(".dds") for path in files.side_files)
    assert files.pac_data == original[PAC]


def test_template_export_keeps_each_parts_translucency_settings(template_game):
    _, snapshot, _, _ = template_game
    blade, gem = (row.submesh_name for row in find_material_wrappers(SIDECAR)[:2])
    choice = TranslucencyChoice.from_settings({blade: (0.1, 0.2), gem: (0.7, 0.8)})
    files = prepare_template_model(snapshot, [PAC], translucency=choice)
    xml = files.side_files[PAC_XML].decode("utf-8")
    rows = find_material_wrappers(xml)
    assert '_value="0.200000"' in xml[rows[0].start:rows[0].end]
    assert '_value="0.800000"' in xml[rows[1].start:rows[1].end]


def test_template_transform_covers_all_lods_and_keeps_uv_skin_and_tangent_handedness():
    import struct
    from cdmw.modding.pac_cloth import pac_cloth_lods
    from cdmw.services.new_item_template_model import transform_template_pac
    from tests.test_mesh_editor_replacement_regressions import _distinct_lods
    source = bytearray(_distinct_lods())
    for level in pac_cloth_lods(source):
        for part in level.submeshes:
            for offset in part.source_vertex_offsets:
                struct.pack_into("<h", source, offset + 6, 32767)  # tangent along +X
                packed = struct.unpack_from("<I", source, offset + 16)[0]
                struct.pack_into("<I", source, offset + 16, (packed & 0x80000000) | (512 << 20) | (512 << 10) | 512)
    source = bytes(source)
    placement = ModelPlacement(rotation=(0, 0, 90), offset=(0.5, 0.1, -0.2), scale=(1.2, 0.8, 1.5))
    output = transform_template_pac(source, tuple(placement.matrix()))
    before, after = pac_cloth_lods(source), pac_cloth_lods(output)
    assert len(before) == len(after) == 4
    for old_level, new_level in zip(before, after):
        for old, new in zip(old_level.submeshes, new_level.submeshes):
            np.testing.assert_allclose(new.vertices, [placement.apply(point) for point in old.vertices], atol=1e-4)
            assert new.faces == old.faces
            for offset in old.source_vertex_offsets:
                assert output[offset + 8:offset + 16] == source[offset + 8:offset + 16]
                assert output[offset + 20:offset + 40] == source[offset + 20:offset + 40]
                assert (struct.unpack_from("<I", output, offset + 16)[0] & 0x80000000
                        == struct.unpack_from("<I", source, offset + 16)[0] & 0x80000000)
                tx = abs(struct.unpack_from("<h", output, offset + 6)[0] / 32767) * 2 - 1
                ty = (struct.unpack_from("<I", output, offset + 16)[0] & 1023) / 511.5 - 1
                assert abs(tx) < 0.01 and ty > 0.99, "normal-map tangent rotates from +X to +Y"


def test_controller_template_edits_and_discard_are_variant_scoped(template_game):
    app = QApplication.instance() or QApplication([])
    _, snapshot, _, _ = template_game
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    first, second = (item.identity for item in selections(snapshot)[:2])
    controller.select_variant(first)
    assert controller.material_parts()
    blade = controller.material_parts()[0][0]
    placement = ModelPlacement(offset=(0.5, 0, 0))
    controller.draft.glow_parts = (blade,)
    controller.draft.translucency = TranslucencyChoice((blade,))
    controller.set_model_placement(placement)
    chosen = controller.current_spec().variants[0]
    assert chosen.template_transform == tuple(placement.matrix())
    assert chosen.glow_parts == (blade,) and chosen.translucency is not None
    controller.select_variant(second)
    assert controller.model_placement.is_identity and not controller.draft.glow_parts
    controller.select_variant(first)
    assert controller.model_placement == placement
    controller.discard_model()
    assert not controller.draft.glow_parts and controller.draft.translucency is None
    assert not controller.draft.template_transform and controller.model_placement.is_identity
    assert controller.current_spec().model_source is ModelSource.TEMPLATE
    controller.shutdown()


def test_first_template_edit_targets_the_binding_already_shown_by_the_selector(template_game):
    app = QApplication.instance() or QApplication([])
    _, snapshot, _, _ = template_game
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    displayed = controller.current_variant_identity()
    controller.set_model_placement(ModelPlacement(offset=(0.2, 0, 0)))
    assert controller._active_variant == displayed
    assert tuple(choice.identity for choice in controller.current_spec().variants) == (displayed,)
    controller.shutdown()


def _events_until(app, condition, timeout=3):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert condition()


def test_template_selection_keeps_ui_alive_rejects_stale_and_drains_shutdown(template_game, monkeypatch):
    from cdmw.workers import new_item_template_selection as selection
    app = QApplication.instance() or QApplication([])
    _, snapshot, _, _ = template_game
    controller = NewItemStudioController()
    controller.snapshot = snapshot
    started, release = threading.Event(), threading.Event()
    real_prepare = selection.prepare_template
    worker_threads, committed, ticks = [], [], []

    def prepare(current, key, stop):
        worker_threads.append(threading.get_ident())
        if key == TEMPLATE:
            started.set()
            assert release.wait(3)
        return real_prepare(current, key, stop)

    monkeypatch.setattr(selection, "prepare_template", prepare)
    controller.template_changed.connect(committed.append)
    timer = QTimer()
    timer.setInterval(1)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        controller.set_template(TEMPLATE)
        _events_until(app, started.is_set)
        _events_until(app, lambda: len(ticks) >= 4)
        controller.set_template(OTHER)
        release.set()
        _events_until(app, lambda: controller.draft.template_key == OTHER)
        assert committed == [OTHER]
        assert all(identity != threading.get_ident() for identity in worker_threads)
        started.clear()
        release.clear()
        controller.set_template(TEMPLATE)
        _events_until(app, started.is_set)
        controller.request_shutdown()
        assert controller.iter_shutdown_workers()
        release.set()
        _events_until(app, lambda: not controller.iter_shutdown_workers())
        assert committed == [OTHER]
    finally:
        release.set()
        timer.stop()
        controller.request_shutdown()
        _events_until(app, lambda: not controller.iter_shutdown_workers())


@pytest.mark.parametrize("matrix", [(1,), (float("nan"),) * 16, (0,) * 16])
def test_invalid_template_placement_is_rejected(template_game, matrix):
    service, snapshot, _, _ = template_game
    with pytest.raises(ValueError, match="Template placement"):
        service.plan(replace(spec(), template_transform=matrix), snapshot)


def test_discarded_import_material_overrides_are_not_replayed(tmp_path, monkeypatch):
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    app = QApplication.instance() or QApplication([])
    frame = ItemPreviewFrame(output_root=tmp_path)
    states = {"material_parameters": [{"emissive_color": "red"}]}
    frame.host = SimpleNamespace(controller=SimpleNamespace(forget_state=lambda key: states.pop(key, None)))
    monkeypatch.setattr(frame, "_ensure_host", lambda: True)
    monkeypatch.setattr(frame, "_start_package", lambda pending: None)
    frame._pending = (("import", 1), object())
    frame._show(object(), token=("template", 1))
    assert "material_parameters" not in states
    states["material_parameters"] = ["current template override"]
    frame.is_ready = True
    frame._show(object(), token=("template", 1))
    assert states["material_parameters"] == ["current template override"]
    frame.host = None
    frame.shutdown()
