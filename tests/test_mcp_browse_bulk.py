"""Browse Archives selection and bulk output for AI tools: several files selected, filtered extraction."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

PATHS = ("character/a_body.pac", "character/b_head.pac", "ui/readme.txt", "character/c_hand.pam")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def browse(app, tmp_path, preserve_app_appearance, monkeypatch):
    from cdmw.app.events import AppEventBus
    from cdmw.models import ArchiveEntry
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    settings = create_settings(settings_file_path=tmp_path / "bulk.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        app.processEvents()
    archive = window.archive
    package = tmp_path / "game" / "0012"
    package.mkdir(parents=True)
    (package / "0.paz").write_bytes(b"x" * 16)
    entries = [ArchiveEntry(path, package / "0.pamt", package / "0.paz", 0, 1, 1, 0, 0) for path in PATHS]
    monkeypatch.setattr(archive, "archive_remote_bridge", None)
    archive.archive_entries = archive.archive_filtered_entries = entries
    archive.archive_tree.use_legacy_model()
    archive.archive_tree.set_archive_state(entries, mode="flat")
    app.processEvents()
    try:
        yield window
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_several_paths_are_selected_together(browse):
    from cdmw.mcp.view_tools import _select_listed

    archive = browse.archive
    outcome: dict = {}
    _select_listed(archive, ["character/a_body.pac", "character/c_hand.pam", "missing/file.pac"], outcome)
    assert outcome["shown"] == ["character/a_body.pac", "character/c_hand.pam"]
    assert outcome["missing"] == ["missing/file.pac"]
    assert sorted(entry.path for entry in archive._selected_archive_entries()) == ["character/a_body.pac",
                                                                                   "character/c_hand.pam"]
    assert archive._current_archive_entry().path == "character/a_body.pac"


def test_the_selected_models_are_what_batch_export_takes(browse):
    from cdmw.mcp.view_tools import _select_listed
    from cdmw.ui.archive_browser import mesh_batch_export_controller as batch

    archive = browse.archive
    _select_listed(archive, ["character/a_body.pac", "ui/readme.txt", "character/b_head.pac"], {})
    models = batch.selected_batch_models(archive, tuple(archive.archive_tree.selectedItems()))
    assert sorted(selection.entry.path for selection in models) == ["character/a_body.pac", "character/b_head.pac"]


def test_extract_filtered_takes_the_tools_destination(browse, tmp_path, monkeypatch):
    archive = browse.archive
    seen = {}
    monkeypatch.setattr(archive, "_run_archive_extract",
                        lambda entries, **options: seen.update(entries=[e.path for e in entries], **options))
    target = tmp_path / "filtered"
    archive.extract_filtered_archive_entries(output_root_override=target)
    assert seen["entries"] == list(PATHS)
    assert seen["output_root_override"] == target and seen["allow_original_dds_root"] is False
    archive.extract_filtered_archive_entries()
    assert seen["output_root_override"] is None and seen["allow_original_dds_root"] is True


def test_the_tool_schemas_offer_the_new_actions():
    from cdmw.mcp.catalogue import typed_tools

    tools = {tool.name: tool for tool in typed_tools()}
    actions = tools["files.browser_export"].input_schema["properties"]["action"]["enum"]
    assert {"extract_filtered", "folder", "batch_mesh", "mesh_neutral_obj", "paths_list"} <= set(actions)
    assert tools["files.browser_export"].input_schema["properties"]["scope"]["enum"] == ["all", "filtered",
                                                                                          "selected", "folder"]
    assert tools["view.open"].input_schema["properties"]["paths"]["maxItems"] == 4096
