"""Captured Effects item sources must not read changing UI/controller state."""

import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import RunCancelled
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
