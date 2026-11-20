"""Create New Item extras through the AI tools (Send to DMM, the advanced editors), on the real page with an owned archive."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.mcp import approvals
from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_independent_item_settings import extended_game  # noqa: F401  (a fixture)


@pytest.fixture
def page(tmp_path, monkeypatch, request):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.new_item.controller import NewItemStudioController
    from cdmw.ui.new_item.item_preview import ItemPreviewFrame
    from cdmw.ui.new_item.tab import NewItemStudioTab
    from tests.test_new_item_service import TEMPLATE, _read, build_package, synthetic_files

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("cdmw.constants.MOD_FOLDER_TOOLS_ENABLED", True)
    monkeypatch.setattr(ItemPreviewFrame, "_start_package", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("cdmw.ui.new_item.effect_placement_dialog._default_host_factory", lambda *_args: None)
    monkeypatch.setattr("cdmw.ui.new_item.panels_output.QDesktopServices.openUrl", lambda _url: True)
    monkeypatch.setattr("cdmw.ui.new_item.panels_output.resolve_settings_file_path", lambda: tmp_path / "CDMW.cfg")
    monkeypatch.setattr("cdmw.services.settings_service.resolve_settings_file_path", lambda: tmp_path / "CDMW.cfg")
    if getattr(request, "param", None) == "independent":
        # Game data with complete item settings, so the advanced editors can be used.
        request.getfixturevalue("extended_game")
        from tests.test_independent_items import setup_game
        _service, _snapshot, entries = setup_game(tmp_path / "snapshot")
    else:
        files = synthetic_files()
        effect = Path(__file__).parent / "fixtures" / "effects" / "fx_hit_common_fire_attach_a_loop.pae"
        files["effect/binary__/releasebin/fx_test_fire.pae"] = effect.read_bytes()
        entries = tuple(parse_archive_pamt(build_package(tmp_path / "snapshot", files)))

    presenter = QWidget()
    shell = SimpleNamespace(new_item_studio_tab=presenter,
                            settings=create_settings(settings_file_path=tmp_path / "studio.cfg"))
    window = SimpleNamespace(shell=shell)
    controller = NewItemStudioController(read_entry=_read, parent=presenter)
    controller.saved_work_root = tmp_path / "saved-work"
    tab = NewItemStudioTab(presenter, window=window, controller=controller, get_archive_entries=lambda: entries)
    presenter.workflow = tab
    presenter.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    presenter.resize(1200, 720)
    presenter.show()
    tab.start_snapshot()
    client = RailClient(tmp_path, window=window)
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"\0")
    client.settings.setValue(approvals.GAME_FOLDER_KEY, str(game))
    try:
        wait_for(lambda: controller.ready and tab._panels_built, timeout=60)
        assert client.ok("new_item.search", text=str(TEMPLATE))["templates"]
        client.ok("new_item.pick", row=0)
        wait_for(lambda: controller.draft.template_key == TEMPLATE, timeout=60)
        assert client.ok("new_item.set", fields={
            "internal_name": "Mcp_Sword", "display_names": {"eng": "MCP Sword"}})["refused"] == {}
        yield client, tab
    finally:
        tab.close()
        wait_for(lambda: not tab.iter_shutdown_workers(), timeout=60)
        presenter.close()
        presenter.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def _finished(client):
    wait_for(lambda: client.ok("new_item.plan")["build"]["status"] != "running", timeout=60)
    return client.ok("new_item.plan")["build"]


def test_send_to_dmm_writes_into_the_mods_folder_and_asks_before_replacing(page, tmp_path):
    client, tab = page
    dmm = tmp_path / "DMM"
    (dmm / "mods").mkdir(parents=True)
    (dmm / "DMM.exe").write_bytes(b"")

    # Without a current plan the page's own message comes back.
    assert client.call("new_item.send_to_dmm", dmm_folder=str(dmm))["error"]["code"] == "unavailable"
    assert client.ok("new_item.plan", action="refresh")["current"]
    elsewhere = tmp_path / "not-dmm"
    elsewhere.mkdir()
    assert client.call("new_item.send_to_dmm", dmm_folder=str(elsewhere))["error"]["code"] == "not_found"

    sent = client.ok("new_item.send_to_dmm", dmm_folder=str(dmm), mod_name="Copper Sword")
    assert sent["started"] and sent["dmm_mods_folder"] == str(dmm / "mods")
    first = _finished(client)
    assert first["status"] == "written" and Path(first["path"]).parent == dmm / "mods", first
    assert Path(first["path"]).is_dir() and not first.get("replaced")
    assert first["asked"][0]["answer"] == "ok"

    # A second send under the same name asks first, and no is the default.
    again = client.ok("new_item.send_to_dmm")
    assert not again["started"] and again["status"] == "cancelled" and "replace" in again["message"]
    replaced = client.ok("new_item.send_to_dmm", replace=True)
    assert replaced["started"]
    assert _finished(client)["replaced"]
    assert tab.output_panel.mod_name.text() == "Copper Sword"


@pytest.mark.parametrize("page", ["independent"], indirect=True)
def test_advanced_editors_change_the_draft_through_their_controls(page):
    client, tab = page
    draft = lambda: tab.controller.draft  # noqa: E731
    apply = lambda editor, *steps: client.ok("new_item.advanced", action="apply", editor=editor,  # noqa: E731
                                             steps=list(steps))
    refused = lambda editor, *steps: client.call("new_item.advanced", action="apply", editor=editor,  # noqa: E731
                                                 steps=list(steps))["error"]
    state = apply("item_settings", {"kind": "press", "control": "load"})
    assert state["fields"]["repair_item"]["count"] and state["buttons"]["reset"]["enabled"]
    state = apply("item_settings", {"kind": "set", "control": "policies.discardable", "value": False},
                  {"kind": "set", "control": "override_repairs", "value": True},
                  {"kind": "set", "control": "repair_item", "value": 1},
                  {"kind": "press", "control": "add_repair"},
                  {"kind": "cell", "control": "repairs", "row": 0, "column": 3, "value": str((1 << 64) - 1)},
                  {"kind": "set", "control": "cooldowns.1", "value": "18,446,744,073,709,551,615"})
    settings = draft().item_settings
    assert settings.discardable is False and settings.repairs[0].resource_count == (1 << 64) - 1
    assert settings.cooldowns == (0, (1 << 64) - 1, 0)
    assert state["applied_steps"] == 6 and state["tables"]["repairs"]["count"] == 1
    # The page's own checks refuse: an unknown choice, a control that is not there, a stock package save.
    error = refused("item_settings", {"kind": "set", "control": "repair_item", "value": 999999999})
    assert error["code"] == "invalid_arguments" and error["data"]["applied_steps"] == 0
    assert refused("item_settings", {"kind": "set", "control": "colour", "value": 1})["code"] == "not_found"
    assert refused("item_settings", {"kind": "press", "control": "write_stock"})["code"] == "unavailable"
    # A value the editor cannot store leaves the draft as it was.
    apply("item_settings", {"kind": "cell", "control": "repairs", "row": 0, "column": 3, "value": "1.5"})
    assert draft().item_settings.repairs[0].resource_count == (1 << 64) - 1

    # The definition page's tree: tick override, then edit a row by its path.
    definition = client.ok("new_item.advanced", action="state", editor="definition")
    assert definition["fields"]["section"]["count"]
    apply("definition", {"kind": "press", "control": "load"})
    state = apply("definition", {"kind": "set", "control": "section", "value": "text"},
                  {"kind": "set", "control": "field", "value": "knowledge_key"},
                  {"kind": "set", "control": "override", "value": True})
    assert state["tree"]["rows"][0] == {"path": [], "label": "Knowledge link", "value": "0", "editable": True}
    state = apply("definition", {"kind": "tree_value", "path": [], "value": "77"})
    assert state["tree"]["rows"][0]["value"] == "77"
    assert draft().definition_settings.fields == {"knowledge_key": 77}
    assert refused("definition", {"kind": "tree_value", "path": ["nope"], "value": "1"})["code"] == "not_found"
    # Game table changes: Set value waits for a loaded table and a chosen value, as on the page.
    tables = client.ok("new_item.advanced", action="state", editor="game_tables")
    assert tables["fields"]["table"]["count"] and tables["edits"] == []
    assert refused("game_tables", {"kind": "press", "control": "set"})["code"] == "unavailable"
    apply("item_settings", {"kind": "press", "control": "reset"})
    assert draft().item_settings is None


def test_emitters_and_saved_effects_through_the_effects_tool(page):
    client, tab = page
    effects = lambda **arguments: client.ok("new_item.effects", **arguments)  # noqa: E731
    effects(action="search", text="fx_test_fire")
    effects(action="pick", stem="fx_test_fire")
    workspace = tab.perks_panel.effects_workspace
    wait_for(lambda: workspace.placement is not None)
    # The preview helper process is not started here; hand the inspector the emitters it would list.
    workspace.placement.effect_preview_ready.emit(SimpleNamespace(emitters=(), editor_emitters=[
        {"name": "fire_core", "resolved": True, "enabled": True, "fields": ("_spawnCountMax", "_opacity"), "values": {}},
        {"name": "fire_sparks", "resolved": False, "enabled": True, "fields": (), "values": {}}]))
    emitters = effects()["emitters"]
    assert [row["resolved"] for row in emitters["list"]] == [True, False]
    staged = lambda: workspace.staged_state.resolved_layers()[workspace.staged_state.active_layer].look  # noqa: E731

    state = effects(action="emitter", emitter_row=0, emitter_enabled=False,
                    parameters=[{"key": "_spawnCountMax", "values": [12]}, {"key": "size", "values": [2.5]}],
                    curves={"opacity_curve": [0.0, 0.5, 0.0]}, texture="effect/texture/spark.dds")
    edit = next(edit for edit in staged().emitters if edit.index == 0)
    assert not edit.enabled and dict(edit.values)["_spawnCountMax"] == (12.0,) and edit.size == 2.5
    assert edit.opacity_curve == (0.0, 0.5, 0.0) and edit.texture == "effect/texture/spark.dds"
    rows = {row["key"]: row for row in state["emitters"]["parameters"]}
    assert rows["_spawnCountMax"]["use"] and rows["_spawnCountMax"]["values"] == [12.0]
    # The emitter's own limits apply, and an unresolved emitter cannot be edited.
    for bad in ({"parameters": [{"key": "_opacity", "values": [5]}]}, {"parameters": [{"key": "nope"}]},
                {"emitter_row": 9}):
        assert client.call("new_item.effects", action="emitter", **bad)["error"]["code"] == "unavailable", bad
    assert client.call("new_item.effects", action="emitter", emitter_row=1,
                       parameters=[{"key": "_opacity", "values": [0.5]}])["error"]["code"] == "unavailable"
    effects(action="emitter", emitter_row=0, emitter_operation="reset")
    assert not any(edit.index == 0 for edit in staged().emitters)

    # Saved effects: save under a name, load it back, delete it (which asks first).
    saved = effects(action="saved", saved_operation="save", saved_name="My flame")
    assert saved["emitters"]["saved"] == ["My flame"] and saved["asked"][0]["answer"] == "My flame"
    effects(action="saved", saved_operation="load", saved_name="My flame")
    assert client.call("new_item.effects", action="saved", saved_operation="load",
                       saved_name="Nope")["error"]["code"] == "unavailable"
    assert effects(action="saved", saved_operation="delete", saved_name="My flame")["emitters"]["saved"] == []



@pytest.mark.parametrize("page", ["independent"], indirect=True)
def test_wearers_reference_and_rig_export_go_through_the_page(page, tmp_path):
    client, tab = page
    wearers = client.ok("new_item.advanced", action="state", editor="wearers")
    assert set(wearers["fields"]) == {"choices.kliff", "choices.damiane", "choices.oongka"}
    assert wearers["message"] == "All characters are already allowed by this template."
    # The boxes are disabled for this template, and the page's reason comes back.
    refused = client.call("new_item.advanced", action="apply", editor="wearers",
                          steps=[{"kind": "set", "control": "choices.kliff", "value": False}])
    assert refused["error"]["code"] == "invalid_arguments"
    reference = client.ok("new_item.advanced", action="state", editor="fitting_reference")
    assert "never exported" in reference["tooltip"] and not reference["buttons"]["clear_reference_button"]["enabled"]
    assert client.ok("new_item.advanced", action="state", editor="rig")["message"] == "Template skeleton"

    # Export rig GLB: the page's folder prompt is answered, and its own failure comes back.
    out = tmp_path / "rig"
    out.mkdir()
    failed = client.call("new_item.export_rig", folder=str(out))
    assert failed["error"]["code"] == "unavailable" and "rig could not be exported" in failed["error"]["message"]
    assert not list(out.iterdir())
    entry = tab.controller.template_primary_entry()
    (out / (Path(str(entry.path)).stem + "_rig.glb")).write_bytes(b"mine")
    kept = client.call("new_item.export_rig", folder=str(out))
    assert "does not replace" in kept["error"]["message"]
    assert client.call("new_item.export_rig", folder=str(tmp_path / "Crimson Desert"))["error"]["code"] == "refused"
