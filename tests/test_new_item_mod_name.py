"""The Rust Output field reaches the package metadata a mod manager displays."""

import json
from unittest.mock import patch

import pytest

from tests.test_new_item_rust_ui import _send, studio


@pytest.mark.parametrize("manager", ["DMM", "CDUMM"])
@pytest.mark.parametrize(
    ("entered_name", "expected_name"),
    [("  Frost – Épée 冰  ", "Frost – Épée 冰"), ("", "Frost"), ("   ", "Frost")],
)
def test_rust_mod_name_reaches_export_metadata_without_replanning(studio, manager, entered_name, expected_name):
    fixture, tab, bridge = studio
    tab.show_step(1)
    tab.identity_panel.internal_name.setText("Frost_Internal_Sword")
    _send(bridge, tab.identity_panel.display_name, "text", "Frost")
    tab.show_step(6)
    panel = tab.output_panel
    assert _send(bridge, panel.manager, "choose", panel.manager.findText(manager))["type"] == "ack"
    folder = fixture.root / "named_mod"
    assert _send(bridge, panel.export_root, "text", str(folder))["type"] == "ack"
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
    with patch("cdmw.ui.new_item.panels_output.QMessageBox.information"):
        assert _send(bridge, panel.export_button, "activate")["type"] == "ack"

    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    modinfo = json.loads((folder / "modinfo.json").read_text(encoding="utf-8"))
    assert manifest["name"] == manifest["title"] == modinfo["name"] == expected_name
    assert "Frost_Internal_Sword" in modinfo["description"]
    if manager == "DMM":
        assert modinfo["title"] == expected_name
        assert (folder / "README.txt").read_text(encoding="utf-8").splitlines()[0] == expected_name


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
