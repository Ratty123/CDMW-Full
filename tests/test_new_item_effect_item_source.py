"""Captured Effects item sources must not read changing UI/controller state."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.spec import MaterialRoute, ModelSource
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
    controller.draft.model_source = ModelSource.IMPORTED
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
    controller.draft.model_source = ModelSource.IMPORTED
    source = controller.item_effect_preview_source()
    with patch("cdmw.ui.new_item.effect_item_source.bake_mesh") as bake:
        with pytest.raises(RunCancelled):
            source(stop)
    bake.assert_not_called()
    controller.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("route", [MaterialRoute.PLAIN_PBR, MaterialRoute.BUILDER])
@pytest.mark.parametrize("selected", [False, True])
def test_effects_glass_requires_a_captured_explicit_selection(route, selected):
    from cdmw.domain.new_item.translucency import TranslucencyChoice
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    original = mesh()
    part = original.submeshes[0]
    part.preview_material_parameters = [SimpleNamespace(parameter_name="_transmissionFactor", value="0.5")]
    part.preview_native_material_overrides = {"emissive_color": [1.0, 0.0, 0.0], "emissive_intensity": 10.0}
    controller.model_import = SimpleNamespace(baked_preview_mesh=lambda: original, baked_scene_mesh=lambda: original)
    controller.draft.model_source = ModelSource.IMPORTED
    controller.draft.material_route = route
    controller.draft.translucency = TranslucencyChoice(("blade",), 0.2, 0.4) if selected else None
    source = controller.item_effect_preview_source()
    controller.draft.material_route = MaterialRoute.BUILDER if route is MaterialRoute.PLAIN_PBR else MaterialRoute.PLAIN_PBR
    controller.draft.translucency = None if selected else TranslucencyChoice(("blade",))
    prepared, label = source(threading.Event())
    overrides = prepared.submeshes[0].preview_native_material_overrides
    assert label == "placed"
    assert overrides.get("translucency") == ([0.2, 0.4] if selected else None)
    assert overrides["emissive_color"] == [1.0, 0.0, 0.0]
    assert overrides["emissive_intensity"] == 10.0
    assert "translucency" not in part.preview_native_material_overrides
    controller.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("transformed", [False, True])
def test_template_choice_ignores_retained_import_and_captures_template_transform(native, transformed, tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    decode_import = Mock(side_effect=AssertionError("Inactive imports must not be decoded"))
    controller.model_import = SimpleNamespace(baked_preview_mesh=decode_import, baked_scene_mesh=decode_import)
    controller.model_result = SimpleNamespace(preview_model=object(), rebuilt_data=b"inactive result")
    controller.model_placement = ModelPlacement(offset=(99.0, 0.0, 0.0))
    controller.draft.model_source = ModelSource.TEMPLATE
    controller.draft.template_key = 17
    offset = 4.0 if transformed else 0.0
    controller.draft.template_transform = tuple(ModelPlacement(offset=(offset, 0.0, 0.0)).matrix()) if transformed else ()
    entry = SimpleNamespace(path="template.pac", basename="template.pac")
    controller.snapshot = SimpleNamespace(
        family=lambda _key: SimpleNamespace(model_stem="template", model_folder="weapon",
            files_for=lambda _kind: (SimpleNamespace(path=entry.path, exists=True),)),
        entry=lambda _path: entry, payload=lambda _path: b"template bytes",
    )
    native_build = Mock(side_effect=lambda stop, **kwargs: kwargs["consume_native_package"]("native-template"))
    if native:
        controller._template_preview_context = {"native_preview_core_cache_root": tmp_path}
    with patch.object(controller, "_template_preview_build", return_value=("template", native_build)):
        source = controller.item_effect_preview_source()
    assert source.source is None and source.preview_model is None and source.rebuilt_data == b""
    controller.draft.model_source = ModelSource.IMPORTED
    controller.draft.template_transform = ()
    with patch("cdmw.services.mesh_workflow_service.parse_pac", return_value=mesh()) as parse, \
         patch("cdmw.services.mesh_dotnet_reference_composite.decode_dotnet_native_preview_package", return_value=mesh()) as decode:
        prepared, label = source.consume(threading.Event(), lambda result: result)
    assert label == "template"
    assert prepared.submeshes[0].vertices[0] == (offset, 0.0, 0.0)
    assert native_build.call_count == decode.call_count == int(native)
    assert parse.call_count == int(not native)
    decode_import.assert_not_called()
    controller.deleteLater()
    app.processEvents()
