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
