"""Captured Effects item sources must not read changing UI/controller state."""

import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.spec import MaterialRoute
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.model_import import ModelPlacement


def mesh():
    return ParsedMesh(
        path="captured.pac", format="pac",
        submeshes=[SubMesh(name="blade", vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], faces=[(0, 1, 2)])],
        bbox_min=(0.0, 0.0, 0.0), bbox_max=(1.0, 1.0, 0.0),
    )


def test_source_captures_import_and_placement_without_decoding():
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    reads = []
    original = mesh()

    def decode():
        reads.append(True)
        return original

    controller.model_import = SimpleNamespace(baked_preview_mesh=decode, baked_scene_mesh=decode)
    controller.model_placement = ModelPlacement(offset=(2.0, 0.0, 0.0))
    source = controller.item_effect_preview_source()
    assert reads == []
    controller.model_import = None
    controller.model_placement = ModelPlacement(offset=(99.0, 0.0, 0.0))
    prepared, label = source(threading.Event())
    assert reads == [True]
    assert label == "placed"
    assert prepared.submeshes[0].vertices[0] == (2.0, 0.0, 0.0)
    assert original.submeshes[0].vertices[0] == (0.0, 0.0, 0.0)
    controller.deleteLater()
    app.processEvents()


def test_source_defers_template_reads_and_keeps_the_captured_snapshot_and_key():
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    reads = []
    entry = SimpleNamespace(path="old.pac", basename="old.pac")

    def family(key):
        reads.append(("family", key))
        return SimpleNamespace(model_stem="old", model_folder="weapon", files_for=lambda _kind: (SimpleNamespace(path="old.pac", exists=True),))

    def payload(path):
        reads.append(("payload", path))
        return b"captured mesh"

    controller.snapshot = SimpleNamespace(family=family, entry=lambda _path: entry, payload=payload)
    controller.draft.template_key = 17
    source = controller.item_effect_preview_source()
    assert reads == []
    controller.snapshot = None
    controller.draft.template_key = 88
    with patch("cdmw.services.mesh_workflow_service.parse_pac", return_value=mesh()) as parse:
        prepared, label = source(threading.Event())
    parse.assert_called_once_with(b"captured mesh", "old.pac")
    assert prepared is not None and label == "template"
    assert reads == [("family", 17), ("payload", "old.pac")]
    controller.deleteLater()
    app.processEvents()


def test_cancelled_import_decode_does_not_start_mesh_baking():
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    stop = threading.Event()

    def decode():
        stop.set()
        return mesh()

    controller.model_import = SimpleNamespace(baked_preview_mesh=decode, baked_scene_mesh=decode)
    source = controller.item_effect_preview_source()
    with patch("cdmw.ui.new_item.effect_item_source.bake_mesh") as bake:
        with pytest.raises(RunCancelled):
            source(stop)
    bake.assert_not_called()
    controller.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("route", [MaterialRoute.PLAIN_PBR, MaterialRoute.BUILDER])
def test_source_glass_and_emission_follow_captured_material_route(route):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    original = mesh()
    part = original.submeshes[0]
    part.preview_material_parameters = [SimpleNamespace(parameter_name="_transmissionFactor", value="0.5")]
    part.preview_native_material_overrides = {"emissive_color": [1.0, 0.0, 0.0], "emissive_intensity": 10.0}
    controller.model_import = SimpleNamespace(baked_preview_mesh=lambda: original, baked_scene_mesh=lambda: original)
    controller.draft.material_route = route
    source = controller.item_effect_preview_source()
    controller.draft.material_route = MaterialRoute.BUILDER if route is MaterialRoute.PLAIN_PBR else MaterialRoute.PLAIN_PBR
    prepared, label = source(threading.Event())
    overrides = prepared.submeshes[0].preview_native_material_overrides
    assert label == "placed"
    assert overrides.get("translucency") == ([0.1, 0.3] if route is MaterialRoute.PLAIN_PBR else None)
    assert overrides["emissive_color"] == [1.0, 0.0, 0.0]
    assert overrides["emissive_intensity"] == 10.0
    assert "translucency" not in part.preview_native_material_overrides
    controller.deleteLater()
    app.processEvents()
