"""AI connections select rows of Browse Archives' live file list as the user's clicks do.

The live list in flat view draws its rows in a table inside the tree, and the tree's own
model is then an empty stand-in. A tool that asked the tree for its rows saw none: view_open
with 'paths' never returned, and mesh_open with 'set' replaced the set with a one-file scope.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTreeView

from cdmw.mcp.mesh_tools import _select_listed_path
from cdmw.mcp.view_tools import select_every_listed_row
from tests.test_archive_bulk_extract_ui import _publish, app, window  # noqa: F401  (fixtures)


def _paths(archive) -> list[str]:
    return sorted(entry.path for entry in archive._selected_archive_entries())


def test_every_row_of_the_live_flat_list_is_selected(window, app):
    archive = window.archive
    _publish(window, total=3)
    app.processEvents()
    tree = archive.archive_tree
    assert tree.remote_flat_view_active
    # The reason the tool must not ask the tree for its rows.
    assert QTreeView.model(tree).rowCount() == 0
    assert select_every_listed_row(archive, 4) == -1, "fewer rows than expected: still loading"
    assert _paths(archive) == []
    assert select_every_listed_row(archive, 3) == 3
    assert _paths(archive) == ["object/data.custom", "object/image.dds", "object/mesh.pac"]
    assert archive._current_archive_entry().path == "object/data.custom"


def test_one_listed_row_becomes_the_current_file(window, app):
    archive = window.archive
    _publish(window, total=3)
    app.processEvents()
    assert _select_listed_path(archive, "Object\\Mesh.pac")
    assert archive._current_archive_entry().path == "object/mesh.pac"
    assert _paths(archive) == ["object/mesh.pac"]
    assert not _select_listed_path(archive, "object/not_listed.pac")
    assert archive._current_archive_entry().path == "object/mesh.pac"
