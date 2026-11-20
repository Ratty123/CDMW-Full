"""Body & Face Finder buttons through the AI tools, against the real window with a fake catalogue."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.domain.archives.character_catalogue import CharacterCatalogScopeResult
from cdmw.mcp.character_finder_tools import character_finder_tools
from cdmw.mcp.errors import ToolError
from cdmw.mcp.schema import validate_arguments
from cdmw.mcp.server import ToolCall
from cdmw.ui.ai_connections.executor import UiExecutor
from tests.test_character_finder_dialog import detail, finder, publish_rows, row  # noqa: F401 - fixture


def _call(dialog, name, answer, **args):
    """Run a worker tool while the test answers the finder's catalogue requests on the UI thread."""

    window = dialog._window
    window._character_finder_dialogs = {dialog}
    executor = UiExecutor(dialog)
    context = SimpleNamespace(window=window, ui_call=executor.call, game_folder=lambda: "")
    tool = {tool.name: tool for tool in character_finder_tools()}[name]
    request = ToolCall(tool, validate_arguments(args, tool.input_schema), context)
    answered = set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(tool.handler, request)
        deadline = time.monotonic() + 10
        while not future.done() and time.monotonic() < deadline:
            QApplication.processEvents()
            for kind, token in list(dialog._requests.items()):
                if token not in answered:
                    answered.add(token)
                    answer(kind)
            time.sleep(0.005)
        return future.result(timeout=1)


def test_show_exact_files_selects_the_row_and_scopes_browse(finder):
    dialog, service, scopes = finder
    wanted = row(2)

    def answer(kind):
        if kind == "search":
            publish_rows(dialog, service, [row(1), wanted])
        elif kind == "detail":
            service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail",
                                      detail(service.calls[-1][1].key and wanted))
        elif kind == "scope":
            service.result_ready.emit(dialog._requests["scope"], "scope_character_catalog",
                                      CharacterCatalogScopeResult("session-a", (7,), 1, 1, False))

    result = _call(dialog, "characters.finder", answer, action="show_exact_files", key=wanted.key, path=wanted.path)
    search = [request for _token, request, _kw in service.calls if hasattr(request, "query")][-1]
    assert search.query == wanted.path and search.view == "assets"
    assert scopes and scopes[-1][0] == (7,) and result["experimental"]


def test_a_row_the_finder_does_not_list_is_refused(finder):
    dialog, service, _scopes = finder

    def answer(kind):
        if kind == "search":
            publish_rows(dialog, service, [])

    with pytest.raises(ToolError, match="did not list that row"):
        _call(dialog, "characters.finder", answer, action="open_npc_finder", key="asset:9", path="nowhere.pac")


def test_export_fbx_answers_the_folder_and_returns_the_report(finder, monkeypatch, tmp_path):
    from tests.test_character_finder_dialog import ExportPreparation

    dialog, service, _scopes = finder
    wanted = row(3)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr("cdmw.ui.character_finder.preview_preparation.CharacterPreviewPreparation", ExportPreparation)
    started = []

    def answer(kind):
        if kind == "search":
            publish_rows(dialog, service, [wanted])
        elif kind == "detail":
            service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", replace(
                detail(wanted), models=(SimpleNamespace(entry_id=1, path=wanted.path),)))

    def finish(*_args):
        # The export's own completion: status line, then the window's report box.
        started.append(dialog._export_pending)
        dialog._export_pending = None
        dialog._status.setText(f"Exported 1 of 1 models to {out}")
        box = QMessageBox(QMessageBox.Icon.Information, "Export FBX", "Exported 1 of 1 models.", parent=dialog)
        box.open()

    monkeypatch.setattr(ExportPreparation, "start", lambda self, _detail, _token: QApplication.instance()
                        and __import__("PySide6.QtCore", fromlist=["QTimer"]).QTimer.singleShot(0, finish))
    result = _call(dialog, "characters.export", answer, action="fbx", key=wanted.key, path=wanted.path,
                   folder=str(out))
    assert started and started[0][1] == out
    assert result["report"] == "Exported 1 of 1 models." and result["folder"] == str(out)
