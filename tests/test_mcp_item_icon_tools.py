from PIL import Image

from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_item_icon_output_workers import _app, _finish_tab, _prepared_tab


def test_item_icons_changes_and_export_use_the_compatible_output(tmp_path):
    _app()
    tab, source, entry = _prepared_tab(tmp_path)
    client = RailClient(tmp_path, widgets={"item_icons": tab})
    try:
        assert client.ok("item_icons.state")["rows"][0]["file"] == str(source)
        client.ok("item_icons.change", action="view", row=0, target=entry.path, background="keep_source")
        assert tab.settings.value("item_icons/background_mode") == "keep_source"
        assert tab._current_target_path() == entry.path
        opened = []
        tab.open_in_texture_editor_requested.connect(lambda path, _binding: opened.append(path))
        client.ok("item_icons.change", action="open_source_in_editor", row=0)
        assert opened == [str(source)]
        client.ok("item_icons.change", action="preview")
        wait_for(lambda: tab._final_preview_thread is None)
        out = tmp_path / "output"
        out.mkdir()
        result = client.ok("item_icons.make", folder=str(out))
        destination = out / entry.path
        assert result["destination"].casefold() == str(destination).casefold()
        wait_for(destination.is_file)
        # The worker writes the file before it reports; let it finish and show its notice before the
        # next call, so nothing of this export is still running when the test tears the tab down.
        wait_for(lambda: tab._output_thread is None and tab._mcp_icon_output is not None)
        with Image.open(destination) as image:
            assert image.size == (16, 16)
        assert client.call("item_icons.make", folder=str(out))["error"]["code"] == "refused"
    finally:
        _finish_tab(tab)
        tab.deleteLater()
