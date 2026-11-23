"""Browse Archives' right-click actions are registry commands whose state follows the real menu."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.context_commands import CONTEXT_COMMANDS, command_reason

SAMPLES = ("object/castle_gate.prefab", "character/cd_phm_00_body.pac", "character/phm_basic.pab",
           "sound/voice_01.wem", "sound/ambience.bnk", "sequence/cutscene_01.paseq",
           "gamedata/inventory.staticinfobody", "action/player.paac", "ui/readme.txt")


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

    settings = create_settings(settings_file_path=tmp_path / "browse.cfg")
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
    entries = [ArchiveEntry(path, package / "0.pamt", package / "0.paz", 0, 1, 1, 0, 0) for path in SAMPLES]
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


def test_each_commands_reason_is_empty_exactly_when_the_menu_offers_its_entry(browse):
    from cdmw.mcp.ui_menus import clean_label
    from cdmw.mcp.ui_tree import act

    archive = browse.archive
    file_specs = [spec for spec in CONTEXT_COMMANDS if spec.needs == "file"]
    for path in SAMPLES:
        name = path.rsplit("/", 1)[-1]
        listed = act(archive.archive_tree, "menu", row=name, window=browse)
        # A greyed-out entry is shown with its reason, as the command gives it.
        offered = {clean_label(row["text"]) for row in listed["entries"] if row.get("enabled", True)}
        assert archive._current_archive_entry().path == path
        for spec in file_specs:
            in_menu = clean_label(spec.label) in offered
            reason = command_reason(archive, spec)
            assert in_menu == (reason == ""), f"{path}: {spec.name} menu={in_menu} reason={reason!r}"


def test_the_commands_are_registered_and_run_the_menus_handler(browse, monkeypatch):
    from cdmw.mcp.ui_tree import act
    from cdmw.ui.commands.registry import CommandRefused, command_registry

    archive = browse.archive
    registry = command_registry()
    for spec in CONTEXT_COMMANDS:
        assert f"browse.{spec.name}" in registry, spec.name
    opened = []
    monkeypatch.setattr(archive, "_open_current_archive_prefab_inspector", lambda: opened.append("prefab"))
    act(archive.archive_tree, "select", row="readme.txt", window=browse)
    assert registry.reason("browse.prefab_inspector").startswith("Offered for .prefab files")
    with pytest.raises(CommandRefused):
        registry.run("browse.prefab_inspector")
    act(archive.archive_tree, "select", row="castle_gate.prefab", window=browse)
    assert registry.reason("browse.prefab_inspector") == ""
    registry.run("browse.prefab_inspector")
    assert opened == ["prefab"]
    # Without a selection the command says what to do first.
    monkeypatch.setattr(archive, "_current_archive_entry", lambda: None)
    assert registry.reason("browse.add_bones") == "Select an archive file first."


def test_add_to_scene_and_remove_from_scene_reach_the_catalogue_bridge(browse, monkeypatch):
    from cdmw.mcp.ui_tree import act

    archive = browse.archive
    calls = []

    class _Bridge:
        displays_v2 = False  # the fixture lists its rows in the legacy tree

        def item_set_contains(self, _entry):
            return False

        def scene_add_reason(self):
            return ""

        def scene_file_count(self):
            return 1

        def add_to_scene(self):
            calls.append(("add", archive._current_archive_entry().path))
            return True

        def remove_from_scene(self, path):
            calls.append(("remove", path))
            return True

    monkeypatch.setattr(archive, "archive_remote_bridge", _Bridge())
    listed = act(archive.archive_tree, "menu", row="ambience.bnk", window=browse)
    assert "Add to scene" not in {row["text"] for row in listed["entries"]}
    act(archive.archive_tree, "menu", row="cd_phm_00_body.pac", menu="Add to scene", window=browse)
    assert calls == [("add", "character/cd_phm_00_body.pac")]
    # The Scene panel's Remove from scene goes to the same bridge.
    archive.archive_item_set_components.removeFileRequested.emit("character/cd_phm_00_body.pac")
    assert calls[-1] == ("remove", "character/cd_phm_00_body.pac")
