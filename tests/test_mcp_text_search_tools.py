import threading

from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_text_search_async_io import _app, _tab


def test_text_search_options_results_export_and_stop(tmp_path, monkeypatch):
    _app()
    tab = _tab(tmp_path)
    client = RailClient(tmp_path, widgets={"text_search": tab})
    source = tmp_path / "source"
    folder = tmp_path / "export"
    source.mkdir()
    folder.mkdir()
    (source / "sample.txt").write_text("MATCH 123\nmatch 456", encoding="utf-8")
    try:
        client.ok("search.text_action", action="start", source="loose", loose_root=str(source), query=r"MATCH \d+",
                  regex=True, case_sensitive=True, extensions=".txt", path_filter="sam")
        wait_for(lambda: tab.results_tree.topLevelItemCount() == 1 and not tab.is_busy())
        state = client.ok("search.text_state")
        assert state["rows"][0]["matches"] == "1"
        assert tab.last_search_case_sensitive and tab.last_search_regex_enabled
        tab.flush_settings_save()
        assert tab.settings.value("text_search/case_sensitive", False, type=bool)
        client.ok("search.text_action", action="preview", row=0, preview_query="MATCH", wrap=True)
        assert tab.preview_find_edit.text() == "MATCH" and tab.preview_wrap_checkbox.isChecked()
        client.ok("search.text_export", folder=str(folder), rows=[0])
        wait_for(lambda: not tab.is_busy())
        assert (folder / "sample.txt").read_text(encoding="utf-8") == "MATCH 123\nmatch 456"

        from cdmw.models import RunCancelled

        entered = threading.Event()

        def slow(*args, stop_event, **kwargs):
            entered.set()
            if stop_event.wait(5):
                raise RunCancelled("Stopped the owned search")
            raise AssertionError("The search did not receive Stop")

        monkeypatch.setattr("cdmw.ui.text_search.workers.search_loose_text_files", slow)
        client.ok("search.text_action", action="start", query="MATCH")
        wait_for(entered.is_set)
        client.ok("search.text_action", action="stop")
        wait_for(lambda: not tab.is_busy())
        assert not tab.stop_button.isEnabled()
    finally:
        tab.request_shutdown()
        wait_for(lambda: not any(thread for _name, thread, _worker in tab.iter_shutdown_workers()))
        tab.deleteLater()
