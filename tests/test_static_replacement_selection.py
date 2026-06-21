from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_selection import (
    part_source_indices_for_commit,
    single_part_source_index_for_preview,
)


def test_part_source_indices_for_commit_requires_geometry_tab_and_mesh() -> None:
    mesh = SimpleNamespace(submeshes=[object(), object()])

    assert part_source_indices_for_commit((0,), mesh, geometry_tab_active=False) == ()
    assert part_source_indices_for_commit((0,), None, geometry_tab_active=True) == ()


def test_part_source_indices_for_commit_sorts_and_bounds_indices() -> None:
    mesh = SimpleNamespace(submeshes=[object(), object(), object()])

    assert part_source_indices_for_commit((2, 0, 5, -1, 1), mesh, geometry_tab_active=True) == (0, 1, 2)


def test_single_part_source_index_for_preview_requires_exactly_one_index() -> None:
    assert single_part_source_index_for_preview((4,)) == 4
    assert single_part_source_index_for_preview(()) == -1
    assert single_part_source_index_for_preview((1, 2)) == -1
