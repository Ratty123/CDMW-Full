"""Workflow regressions and read-only coverage of the installed language corpus."""

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from cdmw.core.paloc_format import LocalizationEntry, encode_paloc, parse_paloc
from tests.test_translation_studio import ENGLISH
from tests.test_translation_studio_loading import panel, until
from tools.translation_studio import ai_provider, ai_translate, catalogue, language_index


def split_catalogue():
    return catalogue.load_catalogue({
        f"gamedata/stringtable/binary__/eng/{name}.paloc": encode_paloc((
            LocalizationEntry(category=1, key=name, text=text),
        ))
        for name, text in (("bank", "Bank"), ("ui", "Menu"))
    }, "eng")


def test_repeated_export_removes_stale_payloads_and_returns_published_paths(tmp_path):
    cat = split_catalogue()
    cat.set_text(0, "Edited bank")
    first = catalogue.export_packages(cat, out_root=tmp_path, name="Translation")
    assert {result.manager for result in first} == {"CDUMM", "DMM", "JMM"}
    cat.reset()
    cat.set_text(1, "Edited menu")
    second = catalogue.export_packages(cat, out_root=tmp_path, name="Translation")
    for result in second:
        assert result.root.is_dir()
        payloads = list(result.root.rglob("*.paloc"))
        assert [path.name for path in payloads] == ["ui.paloc"]
        assert parse_paloc(payloads[0].read_bytes()).entries[0].text == "Edited menu"
        assert result.metadata_files


@pytest.mark.parametrize("failure_stage", ["build", "publish"])
def test_export_failure_preserves_previous_packages(tmp_path, monkeypatch, failure_stage):
    from tools.placement_studio import packaging

    cat = split_catalogue()
    cat.set_text(0, "First edit")
    catalogue.export_packages(cat, out_root=tmp_path, name="Translation")
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    original = packaging.build_package

    def fail_second(manager, *args, **kwargs):
        if manager == "DMM":
            raise OSError("disk failure")
        return original(manager, *args, **kwargs)

    if failure_stage == "build":
        monkeypatch.setattr(packaging, "build_package", fail_second)
    else:
        replace = Path.replace

        def fail_publish(path, target):
            if path.parent.name.startswith(".translation-") and path.name.endswith(" - DMM"):
                raise OSError("disk failure")
            return replace(path, target)

        monkeypatch.setattr(Path, "replace", fail_publish)
    cat.set_text(0, "Second edit")
    with pytest.raises(OSError, match="disk failure"):
        catalogue.export_packages(cat, out_root=tmp_path, name="Translation")
    assert before == {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_cancelled_export_does_not_publish_partial_packages(tmp_path):
    cat = split_catalogue()
    cat.set_text(0, "First")
    catalogue.export_packages(cat, out_root=tmp_path, name="Translation")
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    checks = []

    def cancelled():
        checks.append(True)
        return len(checks) > 1

    cat.set_text(0, "Second")
    with pytest.raises(InterruptedError):
        catalogue.export_packages(cat, out_root=tmp_path, name="Translation", is_cancelled=cancelled)
    assert before == {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_export_name_cannot_escape_the_chosen_folder(tmp_path):
    cat = split_catalogue()
    cat.set_text(0, "Edit")
    with pytest.raises(ValueError):
        catalogue.export_packages(cat, out_root=tmp_path / "chosen", name="../outside")
    assert not (tmp_path / "outside - CDUMM").exists()


@pytest.mark.parametrize("reply", ['{"0": null}', '{"0": {"text": "bad"}}', '[{"i": 0, "t": ["bad"]}]', '[{"i": 0.5, "t": "wrong row"}]'])
def test_malformed_model_values_cannot_become_game_text(reply):
    assert ai_translate.parse_translations(reply) == {}


def test_session_key_is_usable_after_encryption_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("CDMW_TS_WORK_ROOT", str(tmp_path))
    monkeypatch.setattr(ai_provider, "_dpapi", lambda *_args: None)
    ai_provider.save_config(ai_provider.ProviderConfig(model="test", api_key="test-session-only"))
    assert ai_provider.load_config().api_key == "test-session-only"
    assert "test-session-only" not in ai_provider.config_path().read_text()


@pytest.mark.parametrize("preset,field", [("openai", "max_completion_tokens"), ("openai_compatible", "max_tokens"), ("ollama", "max_tokens")])
def test_ai_token_limit_and_versioned_base_url_are_honored(preset, field):
    config = ai_provider.ProviderConfig(preset=preset, model="test", api_key="stored-key", max_tokens=4096,
                                        base_url="http://localhost:1234/v1/")
    request = ai_translate.build_request(config, "Instructions", "Input")
    assert request.url == "http://localhost:1234/v1/chat/completions"
    assert json.loads(request.body)[field] == 4096
    if preset == "ollama":
        assert "Authorization" not in request.headers


def test_http_rate_limit_honors_retry_after_header(monkeypatch):
    import io
    from urllib.error import HTTPError
    from tools.translation_studio import ai_job

    def limited(*_args, **_kwargs):
        raise HTTPError("http://localhost/test", 429, "Too many requests", {"Retry-After": "35"},
                        io.BytesIO(b'{"error":{"message":"slow down"}}'))

    monkeypatch.setattr(ai_job, "urlopen", limited)
    request = ai_translate.HttpRequest("http://localhost/test", {}, b"{}")
    with pytest.raises(ai_translate.ProviderError) as error:
        ai_job.http_transport(request, 10)
    assert error.value.retryable
    assert error.value.retry_after == 35


@pytest.mark.parametrize("preset", ["anthropic", "openai", "gemini"])
def test_provider_job_uses_real_http_with_unicode_and_preserved_markup(preset):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from tools.translation_studio import ai_job

    received = []
    translated = "Översatt.<br/>{Key:Key_Roll}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            answer = json.dumps([{"i": 7, "t": translated}], ensure_ascii=False)
            payload = {"anthropic": {"content": [{"type": "text", "text": answer}]},
                       "openai": {"choices": [{"message": {"content": answer}}]},
                       "gemini": {"candidates": [{"content": {"parts": [{"text": answer}]}}]}}[preset]
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        results = []
        summary = ai_job.run_job(
            config=ai_provider.ProviderConfig(preset=preset, model="test", api_key="fixture-only",
                base_url=f"http://127.0.0.1:{server.server_port}", timeout=5),
            brief=ai_translate.TranslationBrief(target_language="Swedish"),
            lines=[ai_translate.Line(7, "Translate.<br/>{Key:Key_Roll}")], on_result=results.append,
        )
        assert summary.translated == 1
        assert results[0].accepted == {7: translated}
        assert len(received) == 1
        assert received[0][1]["model"] == "test" if preset != "gemini" else "models/test:" in received[0][0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_reset_and_revert_refresh_the_edited_only_view(panel):
    tab, _edit, _settings = panel
    tab._on_loaded(catalogue.load_catalogue(ENGLISH, "eng"), "")
    tab.model.setData(tab.model.index(0, 2), "Edited", Qt.EditRole)
    tab.edited_only.setChecked(True)
    assert tab.model.rowCount() == 1
    tab.table.selectRow(0)
    tab.revert_button.click()
    until(lambda: tab.model.rowCount() == 0)
    tab.edited_only.setChecked(False)
    tab.model.setData(tab.model.index(0, 2), "Edited again", Qt.EditRole)
    tab.edited_only.setChecked(True)
    tab.reset_button.click()
    until(lambda: tab.model.rowCount() == 0)
    assert not tab.export_button.isEnabled()


def test_a_new_language_resets_the_previous_search_and_edited_filter(panel):
    tab, _edit, _settings = panel
    tab._on_loaded(catalogue.load_catalogue(ENGLISH, "eng"), "")
    tab.search_box.setText("does not exist")
    tab.edited_only.setChecked(True)
    tab._on_loaded(catalogue.load_catalogue(ENGLISH, "eng"), "")
    assert tab.model.rowCount() == 4
    assert not tab.search_box.text()
    assert not tab.edited_only.isChecked()


def test_edited_only_ai_scope_does_not_offer_unedited_rows(panel):
    tab, _edit, _settings = panel
    tab._on_loaded(catalogue.load_catalogue(ENGLISH, "eng"), "")
    tab.apply_ai_translations({0: "Edited"})
    tab.edited_only.setChecked(True)
    assert all([line.index for line in lines] == [0] for _label, lines in tab.ai_scopes())


def test_ai_scope_snapshots_edits_without_materializing_prompt_rows_on_ui(panel, monkeypatch):
    tab, _edit, _settings = panel
    cat = split_catalogue()
    tab._on_loaded(cat, "")
    original = ai_translate.Line
    created = []

    def line(*args, **kwargs):
        created.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(ai_translate, "Line", line)
    scopes = tab.ai_scopes()
    assert not created
    cat.set_text(0, "Changed later")
    assert scopes[0][1][0].text == "Bank"


def test_pending_summary_only_materializes_the_rows_it_displays(monkeypatch):
    cat = split_catalogue()
    cat.set_text(0, "First")
    cat.set_text(1, "Second")
    original = cat.row
    materialized = []

    def row(index):
        materialized.append(index)
        return original(index)

    monkeypatch.setattr(cat, "row", row)
    assert len(cat.describe_changes(limit=1)) == 1
    assert materialized == [0]


def test_loose_split_file_without_a_language_folder_uses_the_chosen_archive_path(panel, monkeypatch, tmp_path):
    from tools.translation_studio import tab as module

    tab, _edit, _settings = panel
    source = tmp_path / "bank.paloc"
    source.write_bytes(ENGLISH)
    target = "gamedata/stringtable/binary__/eng/bank.paloc"
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *_: (str(source), ""))
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *_args, **_kwargs: (target, True))
    tab.open_file_button.click()
    until(lambda: tab._catalogue is not None and not tab.iter_shutdown_workers())
    tab.apply_ai_translations({0: "Changed"})
    assert set(tab.mod_files()) == {target}


def test_mount_order_and_cache_follow_the_game_and_exclude_unmounted_tables(tmp_path, monkeypatch):
    from cdmw.core import archive_format
    from cdmw.core.papgt_format import PapgtDirectory, serialize_papgt

    root = tmp_path / "game"
    monkeypatch.setenv("CDMW_TS_WORK_ROOT", str(tmp_path / "cache"))
    sources = {}
    game_path = "gamedata/stringtable/binary__/eng/ui.paloc"
    for name in ("0001", "0020", "9999"):
        source = root / name / "0.pamt"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"fixture")
        sources[name] = source
    monkeypatch.setattr(archive_format, "parse_archive_pamt", lambda _source: [SimpleNamespace(path=game_path)])
    mount = root / "meta" / "0.papgt"
    mount.parent.mkdir()
    mount.write_bytes(serialize_papgt([PapgtDirectory(name="0001", flags=0, pamt_checksum=0), PapgtDirectory(name="0020", flags=0, pamt_checksum=0)]))
    first = language_index.language_index(root)
    assert first.tables_for("eng")[game_path] == sources["0001"]
    mount.write_bytes(serialize_papgt([PapgtDirectory(name="0020", flags=0, pamt_checksum=0), PapgtDirectory(name="0001", flags=0, pamt_checksum=0)]))
    assert language_index.load_cached(root) is None
    assert language_index.language_index(root).tables_for("eng")[game_path] == sources["0020"]


@pytest.mark.parametrize("field,value", [("fingerprint", [1]), ("sources", 2), ("tables", []), ("languages", "eng")])
def test_malformed_cache_fields_are_rebuilt(tmp_path, monkeypatch, field, value):
    from cdmw.core import archive_format

    monkeypatch.setenv("CDMW_TS_WORK_ROOT", str(tmp_path / "cache"))
    root = tmp_path / "game"
    source = root / "0001" / "0.pamt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture")
    monkeypatch.setattr(archive_format, "parse_archive_pamt", lambda _source: [SimpleNamespace(path="gamedata/stringtable/binary__/eng/ui.paloc")])
    language_index.build_index(root)
    cache = language_index.cache_path()
    payload = json.loads(cache.read_text())
    payload[field] = value
    cache.write_text(json.dumps(payload))
    assert language_index.load_cached(root) is None
    assert language_index.language_index(root).languages == ("eng",)


@pytest.mark.real_game
def test_all_installed_languages_round_trip_and_export(tmp_path, monkeypatch):
    from tools.placement_studio import corpus

    root = corpus.game_root()
    if not root.is_dir():
        pytest.skip("needs the installed game")
    monkeypatch.setenv("CDMW_TS_WORK_ROOT", str(tmp_path / "cache"))
    index = language_index.language_index(root)
    assert "eng" in index.languages
    total_rows = total_tables = 0
    for language in index.languages:
        files = catalogue.read_language_tables(language, root)
        cat = catalogue.load_catalogue(files, language)
        for path, payload in files.items():
            assert encode_paloc(parse_paloc(payload)) == payload, path
        for path, (start, end) in cat.source_ranges.items():
            if start < end:
                cat.set_text(start, cat.text_at(start) + " audit")
        changed = cat.changed_files()
        for path, payload in changed.items():
            start, end = cat.source_ranges[path]
            rebuilt = parse_paloc(payload)
            assert len(rebuilt) == end - start
            assert rebuilt.entries[0].text.endswith(" audit")
            assert rebuilt.entries[1:] == cat.table.entries[start + 1:end]
        total_rows += len(cat)
        total_tables += len(files)
        if language == "eng":
            started = time.perf_counter()
            cat.find("no-such-translation-audit-needle")
            print(f"Full English search: {time.perf_counter() - started:.3f}s")
            results = catalogue.export_packages(cat, out_root=tmp_path / "packages", name="Translation audit")
            for result in results:
                exported = {p.relative_to(result.root).as_posix().removeprefix("files/"): p.read_bytes()
                            for p in result.root.rglob("*.paloc")}
                assert set(exported) == set(changed)
                for path, payload in changed.items():
                    assert exported[path] == payload, path
        print(f"{language}: {len(cat):,} rows in {len(files)} tables")
    print(f"Verified {len(index.languages)} languages, {total_rows:,} rows, {total_tables} tables")
