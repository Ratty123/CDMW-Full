from tests.mcp_rail_helpers import RailClient
from tests.test_research_tab_workflows import research_tab
from tools.format_explorer.tab import FormatExplorerTab


def test_research_reads_the_note_and_the_formats_pages(research_tab, tmp_path):
    formats = FormatExplorerTab()
    client = RailClient(tmp_path, widgets={"research": research_tab, "format_explorer": formats})
    try:
        research_tab.notes_target_edit.setText("object/owned.txt")
        research_tab.notes_edit.setPlainText("Evidence from the owned page")
        research_tab.notes_save_button.click()
        assert client.ok("research.read", action="notes", key="object/owned.txt")["text"] == "Evidence from the owned page"
        report = client.ok("research.read", action="formats", key=".pac")
        assert formats.selected_row().extension == ".pac"
        assert report["text"] == formats.detail.toPlainText()
    finally:
        formats.deleteLater()


def test_research_change_refreshes_saves_a_note_and_exports_the_report(research_tab, tmp_path):
    from tests.mcp_rail_helpers import wait_for
    from tests.test_research_tab_workflows import _refresh_idle

    client = RailClient(tmp_path, widgets={"research": research_tab})
    client.ok("research.change", action="refresh")
    wait_for(lambda: _refresh_idle(research_tab))
    assert client.ok("research.read", action="status")["busy"]["refresh"] is False
    client.ok("research.change", action="save_note", path="object/texture/rock_01.dds", tags="rock",
              text="Tiled rock albedo")
    assert client.ok("research.read", action="notes", key="object/texture/rock_01.dds")["text"] == "Tiled rock albedo"
    assert client.call("research.change", action="resolve")["error"]["code"] == "invalid_arguments"
    report = tmp_path / "analysis.json"
    saved = client.ok("research.export", save_file=str(report))
    assert saved["saved"] == str(report) and report.read_text(encoding="utf-8").strip()
    assert client.call("research.export", save_file=str(tmp_path / "analysis.txt"))["error"]["code"] == "invalid_arguments"
    assert client.ok("research.read", action="ui_constraints")["total"] == 0
