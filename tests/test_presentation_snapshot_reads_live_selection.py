"""The embedded presentation snapshot carries the selection the reader made.

The resident viewport is told what to highlight two ways. A pick sends the
highlight directly, and every preview refresh republishes the whole
presentation snapshot -- display mode, grid, gizmo, highlights, hidden parts,
part transforms. The snapshot's factory bound those containers with
`context.get(key) or set()`. They are empty when the factory binds, empty is
false, and it bound a fresh private set for each: the snapshot published no
highlight, no hidden part and no part transform for the life of the dialog.

Read straight off the protocol log: `selection_update src=[1]`, an ack with
`highlighted_source_indices: [1]`, then ~100 ms later a second ack with `[]`
riding the refresh. Selected, then not. The owner saw it as parts that flicker
or stop being selected.

This drives a real Builder over a two-part mesh, picks a part, and reads the
snapshot the refresh path publishes.
"""

from __future__ import annotations

import dataclasses

import pytest

from cdmw.models import ModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import synthetic_builder_preflight
from cdmw.ui.archive_browser.static_replacement_shared_context import shared_context_container

from tests.mesh_builder_driver import open_mesh_builder


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


def test_an_empty_shared_container_is_bound_not_replaced() -> None:
    highlights: set[int] = set()
    context = {"selected_source_highlight_indices": highlights}

    bound = shared_context_container(context, "selected_source_highlight_indices", set)
    highlights.add(3)

    assert bound is highlights
    assert 3 in bound


def test_a_missing_shared_container_gets_a_fresh_one() -> None:
    assert shared_context_container({}, "selected_source_highlight_indices", set) == set()


def test_the_snapshot_carries_the_picked_part(two_part_preflight) -> None:
    with open_mesh_builder(dialog_title="Snapshot highlight") as builder:
        snapshot = getattr(builder.dialog, "_mesh_editor_embedded_presentation_state")
        assert callable(snapshot)

        combo = builder.control("part_source_combo")
        combo.setCurrentIndex(combo.findData(1))
        builder.pump()
        assert builder.control("selected_source_part")["index"] == 1

        state = snapshot()
        assert state["highlights"]["source_indices"] == [1]


def test_every_publish_after_a_pick_keeps_the_highlight(two_part_preflight) -> None:
    """The refresh path republishes the snapshot; none of those may clear it.

    This is the wire-level shape of the fault: the pick's own send carried the
    highlight and the refresh's send did not.
    """
    with open_mesh_builder(dialog_title="Snapshot republish") as builder:
        dialog = builder.dialog
        published: list[list[int]] = []
        dialog._mesh_editor_embedded_dotnet_active = True
        dialog._mesh_editor_embedded_set_presentation_state = lambda state: (
            published.append(list(state.get("highlights", {}).get("source_indices", []))) or True
        )

        combo = builder.control("part_source_combo")
        combo.setCurrentIndex(combo.findData(1))
        for _ in range(12):
            builder.pump()

        assert published, "the pick published nothing to the resident viewport"
        assert all(indices == [1] for indices in published), published
        builder.control("static_preview_refresh_timer").stop()


def test_the_snapshot_carries_a_hidden_part(two_part_preflight) -> None:
    """Part adjustments were bound the same way; a hidden part must reach it."""
    with open_mesh_builder(dialog_title="Snapshot hidden part") as builder:
        snapshot = getattr(builder.dialog, "_mesh_editor_embedded_presentation_state")
        ensure_adjustment = builder.control("_ensure_source_part_adjustment")

        adjustment = ensure_adjustment(1)
        adjustment.enabled = False

        state = snapshot()
        assert state["visibility"]["hidden_submesh_indices"] == [1]
        assert "1" in state["part_transforms"]
