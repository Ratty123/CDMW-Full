from cdmw.core.paloc_format import parse_paloc
from tests.mcp_rail_helpers import RailClient, wait_for
from tests.test_translation_studio import ENGLISH
from tests.test_translation_studio_loading import panel


def test_translation_load_edit_review_and_save_through_the_page(panel, tmp_path):
    tab, _game_field, settings = panel
    source = tmp_path / "localizationstring_eng.paloc"
    source.write_bytes(ENGLISH)
    client = RailClient(tmp_path, widgets={"translation_studio": tab}, settings=settings)
    assert client.ok("translation.edit", action="open", path=str(source))["busy"]
    wait_for(lambda: tab.model.catalogue is not None and tab._thread is None)

    row = client.ok("translation.review")["rows"][0]
    client.ok("translation.edit", action="set", row=row["row"], text="Owned replacement")
    client.ok("translation.edit", action="search", query="Owned", edited_only=True)
    client.ok("translation.edit", action="replace", find="replacement", text="revision")
    wait_for(lambda: not tab._edit_refresh_timer.isActive())
    assert tab.model.catalogue.row(row["entry"]).text == "Owned revision"
    assert client.ok("translation.review")["rows"][0]["edited"]

    target = tmp_path / "mods"
    target.mkdir()
    client.ok("translation.save", folder=str(target), name="Rail proof")
    wait_for(lambda: tab._export_thread is None)
    assert "Wrote" in tab.export_note.text()
    paloc = next(target.rglob("*.paloc"))
    assert any(entry.text == "Owned revision" for entry in parse_paloc(paloc.read_bytes()).entries)


def test_machine_translation_uses_the_selected_line_and_the_page_worker(panel, tmp_path, monkeypatch):
    from tools.translation_studio import ai_panel
    from tools.translation_studio.ai_job import BatchResult, JobSummary
    from tools.translation_studio.ai_provider import ProviderConfig

    tab, _game_field, settings = panel
    source = tmp_path / "localizationstring_eng.paloc"
    source.write_bytes(ENGLISH)
    client = RailClient(tmp_path, widgets={"translation_studio": tab}, settings=settings)
    client.ok("translation.edit", action="open", path=str(source))
    wait_for(lambda: tab.model.catalogue is not None and tab._thread is None)
    original = client.ok("translation.review")["rows"][0]
    translated = "Fixture translation by the owned provider"

    def translate(*, brief, lines, on_result, on_progress, **_):
        assert brief.target_language == "Swedish" and len(lines) == 1
        on_result(BatchResult(1, 1, {original["entry"]: translated}))
        on_progress(1, 1)
        return JobSummary(batches=1, lines=1, translated=1)

    monkeypatch.setattr(ai_panel, "load_config", lambda: ProviderConfig(model="owned-fixture", api_key="fixture"))
    monkeypatch.setattr(ai_panel, "run_job", translate)
    client.ok("translation.edit", action="translate", row=original["row"], target_language="Swedish")
    wait_for(lambda: tab._mcp_translation_dialog._thread is None and not tab._mcp_translation_dialog.isVisible())
    assert tab.model.catalogue.text_at(original["entry"]) == translated
    assert "1 line(s) translated" in client.ok("translation.review")["translation"]
    saved = parse_paloc(next(iter(tab.mod_files().values())))
    assert saved.entries[original["entry"]].text == translated


def test_machine_translation_takes_several_rows(panel, tmp_path, monkeypatch):
    from tools.translation_studio import ai_panel
    from tools.translation_studio.ai_job import BatchResult, JobSummary
    from tools.translation_studio.ai_provider import ProviderConfig

    tab, _game_field, settings = panel
    source = tmp_path / "localizationstring_eng.paloc"
    source.write_bytes(ENGLISH)
    client = RailClient(tmp_path, widgets={"translation_studio": tab}, settings=settings)
    client.ok("translation.edit", action="open", path=str(source))
    wait_for(lambda: tab.model.catalogue is not None and tab._thread is None)
    rows = client.ok("translation.review")["rows"][:2]
    if len(rows) < 2:
        import pytest
        pytest.skip("the fixture table has one line")
    seen = []

    def translate(*, brief, lines, on_result, on_progress, **_):
        seen.append(len(lines))
        on_result(BatchResult(1, 1, {row["entry"]: f"Rad {row['entry']}" for row in rows}))
        on_progress(1, 1)
        return JobSummary(batches=1, lines=len(lines), translated=len(lines))

    monkeypatch.setattr(ai_panel, "load_config", lambda: ProviderConfig(model="owned-fixture", api_key="fixture"))
    monkeypatch.setattr(ai_panel, "run_job", translate)
    client.ok("translation.edit", action="translate", rows=[row["row"] for row in rows], target_language="Swedish")
    wait_for(lambda: tab._mcp_translation_dialog._thread is None and not tab._mcp_translation_dialog.isVisible())
    assert seen == [2]
    assert all(tab.model.catalogue.text_at(row["entry"]) == f"Rad {row['entry']}" for row in rows)
