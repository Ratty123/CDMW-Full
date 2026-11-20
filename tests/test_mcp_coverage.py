"""P13 stage C, item 7: the coverage file names a tool or an accepted gap for everything."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.mcp.catalogue import typed_tools
from cdmw.mcp.coverage import GAPS, command_row, load_coverage
from cdmw.mcp.names import EFFECT_CLASSES, wire_name
from cdmw.mcp.tools import ToolTable


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_every_row_is_well_formed() -> None:
    document = load_coverage()
    assert document["schema"] == 1
    rows = [*document["commands"].values(), *document["command_patterns"], *document["capabilities"]]
    for row in rows:
        assert ("tool" in row) != ("gap" in row), row
        if "gap" in row:
            assert row["gap"] in GAPS, row
            if row["gap"] == "not_built":
                assert str(row.get("milestone", "")).startswith("P13"), row
            if row["gap"] == "needs_pointer":
                assert row.get("by_points"), row
            if row["gap"] in ("not_built", "needs_pointer"):
                assert row.get("class") in EFFECT_CLASSES, row
            if row["gap"] == "accepted":
                assert str(row.get("reason", "")).startswith("Accepted "), row
    ids = [row["id"] for row in document["capabilities"]]
    assert len(ids) == len(set(ids))


def test_every_built_tool_covers_a_capability_and_every_named_tool_exists() -> None:
    table = ToolTable(typed_tools())
    built = {tool.name: tool for tool in table.typed() if tool.built}
    document = load_coverage()
    named = {row["tool"] for row in document["capabilities"] if "tool" in row}
    assert named <= set(built), f"rows name tools that do not exist: {sorted(named - set(built))}"
    assert set(built) <= named, f"tools without a coverage row: {sorted(set(built) - named)}"
    for row in document["capabilities"]:
        if "tool" in row:
            assert row["class"] == built[row["tool"]].effect, row
        # The generic tools that reach a gap meanwhile exist too.
        assert set(row.get("also", ())) <= set(built), row
        # A pointer gap names a tool that takes points instead, and that tool exists.
        if "by_points" in row:
            assert row["by_points"] in set(built), row


def test_nothing_that_changes_writes_or_deletes_is_covered_by_a_tool_that_does_not_ask() -> None:
    built = {tool.name: tool for tool in ToolTable(typed_tools()).typed()}
    for row in load_coverage()["capabilities"]:
        if row["class"] != "read" and "tool" in row:
            assert built[row["tool"]].effect == row["class"] != "read", row
    document = load_coverage()
    for row in [*document["commands"].values(), *document["command_patterns"]]:
        if "tool" in row:
            # A command runs with its own class, worked out for each call.
            assert built[row["tool"]].effect_of is not None, row


def test_nothing_that_writes_into_the_game_has_a_tool() -> None:
    rows = [row for row in load_coverage()["capabilities"] if row.get("gap") == "writes_into_game"]
    # The direct patch routes are removed (decision 35); these are the ones left.
    assert {row["id"] for row in rows} >= {"archive.overlay_install", "archive.virtual_loading_install",
                                           "archive.restore_patch_backups"}
    names = {tool.name for tool in typed_tools()}
    for row in rows:
        assert row["id"] not in names and wire_name(row["id"]) not in {wire_name(n) for n in names}


def _registered_commands(app, tmp_path: Path) -> dict[str, object]:
    """The commands the real main window registers when built headlessly, plus the lazy tools' own."""

    from cdmw.ui.shell.app_context import AppContext
    from cdmw.app.events import AppEventBus
    from cdmw.domain.texture_editor_shortcuts import default_texture_editor_shortcuts
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.commands.registry import command_registry
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.texture_workflow.editor_commands import texture_editor_commands

    settings = create_settings(settings_file_path=tmp_path / "coverage.cfg")
    context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings),
                         event_bus=AppEventBus())
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.show()
        app.processEvents()
    try:
        registry = command_registry()
        commands = {command.id: command for command in registry.commands()}
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()

    class _Editor:
        document = None

        def _busy(self):
            return False

        def export_dds_dialog(self):
            return None

        def preview_compressed_dds(self):
            return None

    # The Texture Editor registers its commands when its tab is first built.
    keys = default_texture_editor_shortcuts()
    for command in texture_editor_commands(_Editor(), {key: (lambda: None) for key in keys}, keys):
        commands.setdefault(command.id, command)
    # Drafts & Mods registers Combine into One Mod when its page is first built.
    from cdmw.ui.mesh_editor.saved_work_commands import combine_command

    command = combine_command(object())
    commands.setdefault(command.id, command)
    return commands


def test_every_registry_command_has_a_row_and_no_row_names_a_missing_command(app, tmp_path, preserve_app_appearance) -> None:
    commands = _registered_commands(app, tmp_path)
    assert any(command_id.startswith("shell.") for command_id in commands)
    assert any(command_id.startswith("browse.") for command_id in commands), "Browse registers at start-up"
    missing = sorted(command_id for command_id in commands if command_row(command_id) is None)
    assert not missing, f"commands without a coverage row: {missing}"
    for command_id, command in commands.items():
        row = command_row(command_id)
        if "tool" in row:
            assert row["tool"] == "app.run_command", row
        if "class" in row and "prefix" not in row:
            # The row's class is the one its approval will ask for: the command's own.
            assert row["class"] == command.effect, f"{command_id}: row says {row['class']}, command {command.effect}"
    # Browse builds its buttons only for the panels it has; every row still names a real command id.
    from cdmw.ui.archive_browser.browse_commands import BROWSE_BUTTONS, command_id as browse_id

    known = {*commands, *(browse_id(name) for name in BROWSE_BUTTONS.values())}
    stale = sorted(set(load_coverage()["commands"]) - known)
    assert not stale, f"rows for commands that no longer exist: {stale}"


# ----- Surfaces: the scan of the source ties the coverage map to the app ---------------------

from cdmw.mcp.coverage import SURFACE_GAPS, SURFACE_KINDS, scan_surfaces, surface_rows


def test_every_surface_the_app_offers_has_a_row_and_every_row_is_still_there() -> None:
    found = scan_surfaces()
    rows = surface_rows()
    missing = sorted(set(found) - set(rows))
    assert not missing, ("these menu entries, dialogs, Mesh Editor host commands, helper controls or rail "
                         f"pages have no row in coverage.json 'surfaces': {missing}")
    stale = sorted(set(rows) - set(found))
    assert not stale, f"these 'surfaces' rows name something the source no longer has: {stale}"
    assert {key.split(":", 1)[0] for key in found} == set(SURFACE_KINDS)


def test_every_surface_row_names_a_tool_a_command_or_a_gap_with_its_reason() -> None:
    built = {tool.name for tool in ToolTable(typed_tools()).typed() if tool.built}
    document = load_coverage()
    commands = set(document["commands"])
    for row in document["surfaces"]:
        routes = [name for name in ("tool", "command", "gap") if name in row]
        assert len(routes) == 1, row
        if "tool" in row:
            assert row["tool"] in built, row
        elif "command" in row:
            assert row["command"] in commands, row
        else:
            assert row["gap"] in SURFACE_GAPS, row
            if row["gap"] in ("not_built", "generic_only"):
                assert str(row.get("milestone", "")).startswith("P13"), row
            if row["gap"] == "generic_only":
                assert isinstance(row.get("item"), int), row
            if row["gap"] == "needs_pointer":
                assert row.get("by_points") in built, row
            if row["gap"] == "user_only":
                assert row.get("reason"), row
            if row["gap"] == "accepted":
                assert str(row.get("reason", "")).startswith("Accepted "), row


def test_the_only_capabilities_still_to_build_wait_on_the_mesh_editor_helper() -> None:
    """MCP gap plan item 17: every other capability has a tool or an accepted gap."""
    open_rows = {row["id"] for row in load_coverage()["capabilities"] if row.get("gap") == "not_built"}
    assert open_rows == {"mesh.camera"}, open_rows


def test_a_new_menu_entry_without_a_row_fails_the_scan(tmp_path, monkeypatch) -> None:
    from cdmw.mcp import coverage

    module = tmp_path / "cdmw" / "ui" / "new_menu.py"
    module.parent.mkdir(parents=True)
    module.write_text("def build(menu):\n    menu.addAction('Brand New Entry...')\n", encoding="utf-8")
    monkeypatch.setattr(coverage, "_REPO", tmp_path)
    monkeypatch.setattr(coverage, "_HOST_COMMAND_FILES", ())
    monkeypatch.setattr(coverage, "scan_helper_controls", lambda: [])
    monkeypatch.setattr(coverage, "scan_rail_pages", lambda: [])
    found = coverage.scan_surfaces()
    assert found == {"menu:cdmw/ui/new_menu.py|Brand New Entry...": ("menu", "cdmw/ui/new_menu.py",
                                                                     "Brand New Entry...")}
    assert not set(found) <= set(surface_rows())
