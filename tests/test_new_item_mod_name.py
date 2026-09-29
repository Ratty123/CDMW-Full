"""The Rust Output field reaches the package metadata a mod manager displays."""

import json
from pathlib import Path
from unittest.mock import patch
import zipfile

import pytest

from tests.test_new_item_rust_ui import _send, studio
from cdmw.domain.packages.layout import sanitize_mod_package_folder_name


@pytest.mark.parametrize(
    ("entered_name", "expected_name"),
    [("  Frost – Épée 冰  ", "Frost – Épée 冰"), ("", "Frost"), ("   ", "Frost")],
)
@pytest.mark.parametrize(("create_zip", "open_folder"), [(False, True), (True, False)])
def test_rust_mod_name_reaches_export_metadata_without_replanning(studio, entered_name, expected_name, create_zip, open_folder):
    fixture, tab, bridge = studio
    tab.show_step(1)
    tab.identity_panel.internal_name.setText("Frost_Internal_Sword")
    _send(bridge, tab.identity_panel.display_name, "text", "Frost")
    tab.show_step(6)
    panel = tab.output_panel
    assert [panel.manager.itemText(i) for i in range(panel.manager.count())] == ["DMM", "CDUMM", "JMM"]
    assert tab.controller.draft.manager == "DMM"
    assert _send(bridge, panel.manager, "choose", panel.manager.findText("DMM"))["type"] == "ack"
    parent = fixture.root / "mods"
    parent.mkdir()
    (parent / "unrelated.txt").write_text("keep")
    assert _send(bridge, panel.export_root, "text", str(parent))["type"] == "ack"
    assert not panel.add_to_mod.isChecked()
    assert tab.controller.mod_base_folder is None
    assert _send(bridge, panel.build_button, "activate")["type"] == "ack"
    plan = tab.controller.plan
    assert plan is not None, panel.summary.toPlainText()
    assert panel.mod_name.placeholderText() == "Frost"

    assert _send(bridge, panel.mod_name, "text", entered_name)["type"] == "ack"
    assert tab.controller.draft.mod_name == entered_name
    assert tab.controller.plan is plan and tab.controller.has_current_plan
    assert panel.export_button.isEnabled()
    assert plan.spec.internal_name == "Frost_Internal_Sword"
    assert plan.spec.display_names["eng"] == "Frost"
    folder = parent / sanitize_mod_package_folder_name(expected_name)
    assert str(folder) in panel.destination_note.text()
    assert _send(bridge, panel.create_zip, "toggle", create_zip)["type"] == "ack"
    assert _send(bridge, panel.open_folder_after_creation, "toggle", open_folder)["type"] == "ack"
    assert tab.controller.plan is plan
    with patch("cdmw.ui.new_item.panels_output.QMessageBox.information"):
        assert _send(bridge, panel.export_button, "activate")["type"] == "ack"

    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    modinfo = json.loads((folder / "modinfo.json").read_text(encoding="utf-8"))
    assert manifest["name"] == manifest["title"] == modinfo["name"] == expected_name
    assert "Frost_Internal_Sword" in modinfo["description"]
    assert modinfo["title"] == expected_name
    assert (folder / "README.txt").read_text(encoding="utf-8").splitlines()[0] == expected_name
    assert manifest["manager_targets"] == ["dmm"]
    assert manifest["structure"] == "archive_group" and manifest["archive_group"] == "0036"
    assert (folder / "0036/0.pamt").is_file() and (folder / "0036/0.paz").is_file()
    assert not (folder / "meta/0.papgt").exists()
    assert (parent / "unrelated.txt").read_text() == "keep"
    assert not (parent / "manifest.json").exists()
    expected_zip = folder.with_name(f"{folder.name}.zip")
    assert expected_zip.exists() == create_zip
    if create_zip:
        with zipfile.ZipFile(expected_zip) as archive:
            files = {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
            assert {name: archive.read(name) for name in archive.namelist()} == files
    assert panel.open_folder_after_creation.isChecked() is open_folder
    if open_folder:
        fixture.opened_folders.assert_called_once()
        assert Path(fixture.opened_folders.call_args.args[0].toLocalFile()) == folder.resolve()
    else:
        fixture.opened_folders.assert_not_called()


@pytest.mark.parametrize("manager", ["Unknown", ""])
def test_new_item_refuses_unavailable_managers_before_starting_export(studio, manager):
    fixture, tab, _bridge = studio
    folder = fixture.root / "unavailable_manager"
    with patch.object(tab.controller, "_run") as run:
        assert not tab.controller.start_export(folder, manager)
        run.assert_not_called()
    assert not folder.exists()


@pytest.mark.parametrize("manager", ["CDUMM", "JMM"])
def test_rust_manager_selection_exports_the_complete_loose_package(studio, manager):
    from cdmw.services.new_item_mod_base import mod_folder_payloads

    fixture, tab, bridge = studio
    tab.show_step(1)
    tab.identity_panel.internal_name.setText("Manager_Test_Sword")
    _send(bridge, tab.identity_panel.display_name, "text", "Manager test")
    tab.show_step(6)
    panel = tab.output_panel
    assert _send(bridge, panel.manager, "choose", panel.manager.findText(manager))["type"] == "ack"
    assert tab.controller.draft.manager == manager
    assert not panel.dmm_warning.isVisibleTo(tab)
    _send(bridge, panel.export_root, "text", str(fixture.root / "mods"))
    _send(bridge, panel.mod_name, "text", "Manager test")
    _send(bridge, panel.open_folder_after_creation, "toggle", False)
    assert _send(bridge, panel.build_button, "activate")["type"] == "ack"
    plan = tab.controller.plan
    assert plan is not None, panel.summary.toPlainText()
    with patch("cdmw.ui.new_item.panels_output.QMessageBox.information"):
        assert _send(bridge, panel.export_button, "activate")["type"] == "ack"
    folder = fixture.root / "mods" / "Manager test"
    payloads = mod_folder_payloads(folder)
    assert {path: payload.read_bytes() for path, payload in payloads.items()} == dict(plan.loose_files)
    if manager == "CDUMM":
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["manager_targets"] == ["cdumm"]
        assert (folder / "files").is_dir()
    else:
        assert (folder / "gamedata").is_dir()
        assert not (folder / "files").exists()
    _send(bridge, panel.manager, "choose", panel.manager.findText("DMM"))
    assert panel.dmm_warning.isVisibleTo(tab)


def test_dmm_warning_is_readable_in_rust_and_scoped_to_mod_folder(studio):
    _, tab, bridge = studio
    tab.show_step(6)
    panel = tab.output_panel
    warning = bridge.document.widget(panel.dmm_warning, force=True)
    assert panel.dmm_warning.isVisibleTo(tab)
    assert "DMM compatibility warning:" in warning["props"]["text"]
    assert "Some exports may not load or work correctly." in warning["props"]["text"]
    assert warning["props"]["wrap"]
    assert any(span.get("bold") for span in warning["props"]["spans"])
    _send(bridge, panel.overlay_mode_button, "activate")
    assert not panel.dmm_warning.isVisibleTo(tab)
    _send(bridge, panel.folder_mode_button, "activate")
    assert panel.dmm_warning.isVisibleTo(tab)


def test_mod_name_follows_item_name_until_overridden_and_survives_item_edits(studio):
    _, tab, bridge = studio
    tab.show_step(1)
    _send(bridge, tab.identity_panel.display_name, "text", "Frost")
    tab.show_step(6)
    panel = tab.output_panel
    assert panel.mod_name.placeholderText() == "Frost"
    _send(bridge, panel.mod_name, "text", "My weapon pack")
    tab.show_step(1)
    _send(bridge, tab.identity_panel.display_name, "text", "Ice")
    tab.show_step(6)
    assert panel.mod_name.placeholderText() == "Ice"
    assert panel.mod_name.text() == tab.controller.draft.mod_name == "My weapon pack"
    _send(bridge, panel.mod_name, "text", "")
    assert panel.mod_name.placeholderText() == "Ice"
    assert tab.controller.draft.mod_name == ""


def test_open_folder_choice_is_saved_in_cfg_and_only_changes_when_toggled(studio):
    from PySide6.QtCore import QSettings
    from cdmw.ui.new_item.panels_output import OutputPanel, _OPEN_FOLDER_SETTING

    fixture, tab, bridge = studio
    tab.show_step(6)
    panel = tab.output_panel
    assert panel.open_folder_after_creation.isChecked()
    for checked in (False, True):
        assert _send(bridge, panel.open_folder_after_creation, "toggle", checked)["type"] == "ack"
        panel._settings.sync()
        settings = QSettings(str(fixture.root / "CDMW.cfg"), QSettings.Format.IniFormat)
        assert settings.value(_OPEN_FOLDER_SETTING, type=bool) is checked
        reopened = OutputPanel(tab.controller, tab, settings=settings)
        try:
            assert reopened.open_folder_after_creation.isChecked() is checked
            tab.controller.set_template(tab.controller.draft.template_key)
            _send(bridge, panel.overlay_mode_button, "activate")
            _send(bridge, panel.folder_mode_button, "activate")
            assert panel.open_folder_after_creation.isChecked() is checked
        finally:
            reopened.close()
            reopened.deleteLater()


def test_existing_mod_is_explicit_and_new_export_does_not_overwrite_it(studio):
    fixture, tab, bridge = studio
    tab.show_step(1)
    _send(bridge, tab.identity_panel.display_name, "text", "heahea")
    tab.show_step(6)
    panel = tab.output_panel
    parent = fixture.root / "mods"
    folder = parent / "heahea"
    folder.mkdir(parents=True)
    (folder / "keep.txt").write_text("original")
    _send(bridge, panel.export_root, "text", str(parent))
    _send(bridge, panel.open_folder_after_creation, "toggle", False)
    _send(bridge, panel.build_button, "activate")
    _send(bridge, panel.export_button, "activate")
    assert (folder / "keep.txt").read_text() == "original"
    assert not (folder / "manifest.json").exists()
    assert "already exists" in panel.log.toPlainText()
    fixture.opened_folders.assert_not_called()
    _send(bridge, panel.add_to_mod, "toggle", True)
    _send(bridge, panel.export_root, "text", str(folder))
    assert tab.controller.mod_base_folder == folder
    assert "keeps its existing items" in panel.mod_base_note.text()
    assert panel._package_root() == folder
    _send(bridge, panel.add_to_mod, "toggle", False)
    assert tab.controller.mod_base_folder is None
