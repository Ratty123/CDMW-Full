"""Textures > Replace through the AI tools, on the real page without a workspace."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings

from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.replace_assistant_tab import ReplaceAssistantTab
from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_replace_assistant_archive_catalogue import _app, _entry


def _legacy_tab(tmp_path, entries):
    return ReplaceAssistantTab(
        settings=QSettings(str(tmp_path / "replace.ini"), QSettings.Format.IniFormat),
        base_dir=tmp_path, get_archive_entries=lambda: entries, get_original_root=lambda: "",
        get_current_config=lambda: None)


def test_replace_adds_matches_and_removes_queue_rows(tmp_path):
    _app()
    archive_entry = ArchiveCatalogueService.compatibility_entry(_entry(tmp_path, 41, "ui/icons/legacy.dds"))
    tab = _legacy_tab(tmp_path, (archive_entry,))
    client = RailClient(tmp_path, widgets={"replace_assistant": tab})
    first = tmp_path / "0009" / "ui" / "icons" / "legacy.png"
    second = tmp_path / "0009" / "ui" / "icons" / "unknown.png"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    try:
        wait_for(lambda: not tab.is_busy())
        assert client.call("textures.replace", action="add_files",
                           paths=[str(tmp_path / "missing.png")])["error"]["code"] == "invalid_arguments"
        client.ok("textures.replace", action="add_files", paths=[str(first), str(second)])
        wait_for(lambda: not tab.is_busy() and len(tab.items) == 2)
        client.ok("textures.replace", action="match_source", source="archive")
        client.ok("textures.replace", action="auto_match")
        wait_for(lambda: not tab.is_busy())
        state = client.ok("textures.replace_state")
        rows = {row["source"]: row for row in state["items"]}
        assert rows[str(first)]["matched"] and rows[str(first)]["original"] == "ui/icons/legacy.dds"
        assert not rows[str(second)]["matched"]
        # A row without its original stops Build Package with the page's own message.
        out = tmp_path / "out"
        out.mkdir()
        refused = client.call("textures.replace_build", folder=str(out))
        assert refused["error"]["code"] == "unavailable" and "unresolved" in refused["error"]["message"]
        unmatched = rows[str(second)]["row"]
        client.ok("textures.replace", action="remove", rows=[unmatched])
        assert [item.source_path for item in tab.items] == [first]
        assert client.call("textures.replace", action="remove", rows=[9])["error"]["code"] == "not_found"
        client.ok("textures.replace", action="clear")
        assert not tab.items
    finally:
        tab.request_shutdown()
        wait_for(lambda: not tab.is_busy())
        tab.deleteLater()
