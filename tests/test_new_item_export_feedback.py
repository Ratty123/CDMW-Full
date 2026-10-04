"""Persistent export blockers and the existing-package recovery route."""

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.spec import NewItemSpec
from cdmw.services.new_item_mod_base import mod_folder_payloads
from tests.test_new_item_overlay_recovery import drain
from tests.test_new_item_rust_ui import TEMPLATE, _send, studio
from tests.test_new_item_service import BIN, _read, build_package


def _mounted_item(studio, manager):
    fixture, tab, _bridge = studio
    service = tab.controller.service
    first = service.plan(NewItemSpec(template_key=TEMPLATE, internal_name="Existing_Sword",
                                    display_names={"eng": "Existing <Sword>"}), tab.controller.snapshot)
    folder = fixture.root / "existing_mod"
    service.export_loose(first, folder, manager=manager)
    files = {entry.path: _read(entry) for entry in fixture.entries}
    files.update(first.loose_files)
    pamt = build_package(fixture.root / "mounted_game", files)
    tab.controller.snapshot = service.build_snapshot(parse_archive_pamt(pamt), read_entry=_read)
    return first, folder, pamt


def _build_new(studio, manager="DMM"):
    fixture, tab, bridge = studio
    tab.show_step(1)
    tab.identity_panel.internal_name.setText("Fresh_Sword")
    _send(bridge, tab.identity_panel.display_name, "text", "Fresh sword")
    tab.show_step(6)
    panel = tab.output_panel
    _send(bridge, panel.manager, "choose", panel.manager.findText(manager))
    _send(bridge, panel.export_root, "text", str(fixture.root / "mods"))
    _send(bridge, panel.open_folder_after_creation, "toggle", False)
    _send(bridge, panel.build_button, "activate")
    assert tab.controller.has_current_plan, panel.summary.toPlainText()
    return panel


@pytest.mark.parametrize("manager", ["CDUMM", "JMM", "DMM"])
def test_inherited_item_is_a_visible_block_before_writing(studio, manager):
    fixture, tab, bridge = studio
    first, _folder, pamt = _mounted_item(studio, manager)
    panel = _build_new(studio, manager)
    plan = tab.controller.plan
    assert plan.unselected_source_items == (f"Existing <Sword> (item {first.spec.item_key})",)
    assert panel.plan_state.plain_text() == "Export blocked"
    assert not panel.export_button.isEnabled()
    assert panel.choose_mod_base_button.isVisibleTo(tab)
    problem = bridge.document.widget(panel.export_problem, force=True)["props"]
    assert f"Existing <Sword> (item {first.spec.item_key})" in problem["text"]
    assert str(pamt) in problem["text"]
    assert "combine items" in problem["text"] and "separate mod" in problem["text"]
    assert problem["wrap"]
    tab.resize(1100, 650)
    QApplication.processEvents()
    assert not panel.export_problem.visibleRegion().isEmpty()
    assert not panel.choose_mod_base_button.visibleRegion().isEmpty()
    with patch.object(tab.controller, "start_export") as start:
        panel._export()
        start.assert_not_called()
    panel._busy_changed(False)
    assert panel.plan_state.plain_text() == "Export blocked"
    assert not panel.export_button.isEnabled()
    assert not (fixture.root / "mods").exists()


def test_choose_existing_mod_preserves_draft_and_exports_both_items(studio):
    _fixture, tab, bridge = studio
    first, folder, _pamt = _mounted_item(studio, "DMM")
    panel = _build_new(studio)
    before = {path: payload.read_bytes() for path, payload in mod_folder_payloads(folder).items()}
    with patch("cdmw.ui.new_item.panels_output.QFileDialog.getExistingDirectory", return_value=str(folder)):
        assert _send(bridge, panel.choose_mod_base_button, "activate")["type"] == "ack"
    assert panel.add_to_mod.isChecked()
    assert tab.controller.mod_base_folder == folder
    assert tab.controller.draft.internal_name == "Fresh_Sword"
    assert tab.controller.plan is None
    assert not panel.export_problem.isVisibleTo(tab)
    assert not panel.choose_mod_base_button.isVisibleTo(tab)
    assert not panel.export_button.isEnabled()
    assert {path: payload.read_bytes() for path, payload in mod_folder_payloads(folder).items()} == before

    _send(bridge, panel.build_button, "activate")
    plan = tab.controller.plan
    assert plan is not None and not plan.unselected_source_items
    assert panel.export_button.isEnabled()
    with patch("cdmw.ui.new_item.panels_output.QMessageBox.information"):
        _send(bridge, panel.export_button, "activate")
    payloads = mod_folder_payloads(folder)
    body = payloads[f"{BIN}/iteminfo.pabgb"].read_bytes()
    head = payloads[f"{BIN}/iteminfo.pabgh"].read_bytes()
    rows = {row.row_id: parse_iteminfo_row(body[start:end]).string_key
            for row, start, end in parse_pabgh_table(head, payload=body).row_spans(len(body))}
    assert rows[first.spec.item_key] == "Existing_Sword"
    assert rows[plan.spec.item_key] == "Fresh_Sword"
    for path in first.new_paths:
        assert payloads[path].read_bytes() == before[path]


def test_cancelling_mod_choice_keeps_the_block_and_original_plan(studio):
    _fixture, tab, bridge = studio
    _mounted_item(studio, "DMM")
    panel = _build_new(studio)
    plan, destination = tab.controller.plan, panel.export_root.text()
    with patch("cdmw.ui.new_item.panels_output.QFileDialog.getExistingDirectory", return_value=""):
        _send(bridge, panel.choose_mod_base_button, "activate")
    assert tab.controller.plan is plan
    assert panel.export_root.text() == destination
    assert not panel.add_to_mod.isChecked()
    assert panel.plan_state.plain_text() == "Export blocked"
    assert not panel.export_button.isEnabled()
    _send(bridge, panel.overlay_mode_button, "activate")
    assert not panel.export_problem.isVisibleTo(tab)
    assert not panel.choose_mod_base_button.isVisibleTo(tab)


@pytest.mark.parametrize("synchronous", [True, False])
def test_write_error_stays_visible_after_completion_and_clears_on_retry(studio, synchronous):
    fixture, tab, bridge = studio
    panel = _build_new(studio)
    plan = tab.controller.plan
    tab.controller._synchronous = synchronous
    message = "Cannot write the destination: access denied."
    with patch.object(type(tab.controller.service), "export_loose", side_effect=OSError(message)), \
            patch("cdmw.ui.new_item.panels_output.QMessageBox.information") as success:
        _send(bridge, panel.export_button, "activate")
        drain(QApplication.instance(), tab.controller)
        success.assert_not_called()
    assert not tab.controller.busy
    assert not panel.busy_bar.isVisibleTo(tab)
    assert panel.export_problem.isVisibleTo(tab)
    assert bridge.document.widget(panel.export_problem, force=True)["props"]["text"] == message
    assert panel.plan_state.plain_text() == "Export blocked"
    assert message in panel.log.toPlainText()
    assert tab.controller.plan is plan and panel.export_button.isEnabled()
    assert not panel.choose_mod_base_button.isVisibleTo(tab)
    assert not panel._package_root().exists()
    fixture.opened_folders.assert_not_called()

    with patch("cdmw.ui.new_item.panels_output.QMessageBox.information"):
        _send(bridge, panel.export_button, "activate")
        drain(QApplication.instance(), tab.controller)
    assert panel._package_root().is_dir()
    assert not panel.export_problem.isVisibleTo(tab)
    assert panel.plan_state.plain_text().startswith("Ready:")
