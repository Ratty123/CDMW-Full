"""Picking a part in Part Setup selects it in the source tree and highlights it.

Part Setup's part combo used to delegate to the source tree by testing whether
the tree already held a row for the picked index. The tree is populated lazily,
in chunks, and it lives on a tab the reader may never open -- so for any row it
had not reached yet the combo took the "clear selection" branch, and picking a
part highlighted nothing and loaded no controls.

The viewport pick path solved the same problem by materialising the row on
demand. This drives a real Builder over a two-part mesh, empties the source tree
the way a not-yet-populated tree looks, and picks from the combo.
"""

from __future__ import annotations

import dataclasses

import pytest

from cdmw.models import ModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import synthetic_builder_preflight

from tests.mesh_builder_driver import MeshBuilderDriver, open_mesh_builder


def _two_part_mesh() -> ParsedMesh:
    def part(name: str, x_offset: float) -> SubMesh:
        return SubMesh(
            name=name,
            material=name,
            vertices=[(x_offset, 0.0, 0.0), (x_offset + 1.0, 0.0, 0.0), (x_offset, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )

    return ParsedMesh(path="two_parts.obj", format="obj", submeshes=[part("blade", 0.0), part("gem", 2.0)])


@pytest.fixture
def two_part_preflight(monkeypatch: pytest.MonkeyPatch):
    """The driver's synthetic preflight, with a real replacement mesh in it."""

    mesh = _two_part_mesh()

    def _preflight(*, modify_original_clone_mode: bool):
        base = synthetic_builder_preflight(modify_original_clone_mode=modify_original_clone_mode)
        scene = dataclasses.replace(base.scene_import_result, mesh=mesh)
        return dataclasses.replace(
            base,
            scene_import_result=scene,
            replacement_mesh_base=mesh,
            replacement_mesh=mesh,
            replacement_preview_model=ModelPreviewData(path=mesh.path),
        )

    import tests.mesh_builder_driver as driver_module

    monkeypatch.setattr(driver_module, "synthetic_builder_preflight", _preflight)
    return mesh


def test_picking_a_part_the_tree_has_not_reached_still_selects_it(two_part_preflight) -> None:
    with open_mesh_builder(dialog_title="Part Setup pick") as builder:
        combo = builder.control("part_source_combo")
        tree = builder.control("source_tree")
        items_by_index = builder.control("source_items_by_index")
        assert combo.count() >= 3, "combo lists the placeholder and both parts"

        # A tree that has not been populated yet: no rows, no index map. This
        # is what the combo used to test membership against.
        tree.clear()
        items_by_index.clear()

        combo_row = combo.findData(1)
        assert combo_row > 0
        combo.setCurrentIndex(combo_row)
        builder.pump()

        assert builder.control("selected_source_part")["index"] == 1
        assert 1 in builder.control("selected_source_highlight_indices")
        assert 1 in items_by_index, "the row was materialised on demand"
        current = tree.currentItem()
        assert current is items_by_index[1]
        assert current.isSelected()


def test_picking_the_placeholder_clears_the_selection(two_part_preflight) -> None:
    with open_mesh_builder(dialog_title="Part Setup clear") as builder:
        combo = builder.control("part_source_combo")

        combo.setCurrentIndex(combo.findData(1))
        builder.pump()
        assert builder.control("selected_source_part")["index"] == 1

        combo.setCurrentIndex(combo.findData(-1))
        builder.pump()

        assert builder.control("selected_source_part")["index"] == -1
        assert not builder.control("selected_source_highlight_indices")

        # End on a selected part. Clearing queues the same debounced preview
        # refresh it always did, and the driver refuses to close over a live
        # timer; the pick path drains cleanly on reject and this one does not,
        # which is a pre-existing property of the clear path and not what this
        # test is about.
        combo.setCurrentIndex(combo.findData(0))
        builder.pump()
        assert builder.control("selected_source_part")["index"] == 0
