"""AI connections: read tools against the shapes the app's services answer with, no worker needed.

Each test hands a tool a stand-in for the archive catalogue that answers the
way the real service does (its page sizes, its refused rows), so a tool that
reads only the first page, or calls a refused row missing, fails here.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from cdmw.mcp.errors import ToolError
from cdmw.mcp.read_tools import read_tools
from cdmw.mcp.schema import validate_arguments


def _tool(name: str):
    return next(tool for tool in read_tools() if tool.name == name)


def _call(name: str, arguments: dict, context) -> SimpleNamespace:
    tool = _tool(name)
    call = SimpleNamespace(tool=tool, arguments=validate_arguments(arguments, tool.schema_for_clients()),
                           context=context, cancel_event=threading.Event(), progress=lambda *_a: None,
                           check_cancelled=lambda: None)
    return call


@dataclass(frozen=True)
class _Row:
    key: str


class _CharacterCatalogue:
    """Body & Face Finder's worker: at most 72 rows a request, as ArchiveCharacterCatalog.cs clamps."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.requests = []

    def __call__(self, method, *args, **_kwargs):
        from cdmw.domain.archives.character_catalogue import CharacterCatalogSearchResult

        if method == "build_character_catalog":
            return None
        request = args[0]
        self.requests.append(request)
        size = max(1, min(request.page_size, 72))
        indices = range(request.page_start, min(request.page_start + size, self.total))
        return CharacterCatalogSearchResult(request.session_id, self.total, request.page_start, size,
                                            tuple(_Row(f"body-{i}") for i in indices), (), ("a warning",))


def _character_context(catalogue) -> SimpleNamespace:
    service = SimpleNamespace(character_catalog_available=True)
    return SimpleNamespace(archive_session=lambda: SimpleNamespace(session_id="s1"),
                           catalogue_service=lambda: service, ui_call=lambda function: function(),
                           catalogue_call=catalogue)


def test_body_and_face_finder_reads_every_page_the_worker_answers_in() -> None:
    catalogue = _CharacterCatalogue(total=200)
    tool = _tool("search.characters")
    result = tool.handler(_call("search.characters", {"max_results": 150}, _character_context(catalogue)))
    assert len(result["characters"]) == 150 and result["total_matches"] == 200 and result["truncated"]
    assert [r.page_start for r in catalogue.requests] == [0, 72, 144]
    assert result["characters"][0] == {"key": "body-0"} and result["characters"][-1] == {"key": "body-149"}
    every = tool.handler(_call("search.characters", {"max_results": 1000}, _character_context(
        _CharacterCatalogue(total=100))))
    assert len(every["characters"]) == 100 and not every["truncated"] and every["warnings"] == ["a warning"]


def test_body_and_face_finder_takes_only_its_own_views_and_tabs() -> None:
    schema = _tool("search.characters").schema_for_clients()
    assert validate_arguments({"view": "appearances", "tab": "faces"}, schema)["tab"] == "faces"
    for wrong in ({"view": "bodies"}, {"tab": "hair"}):
        with pytest.raises(ToolError) as refused:
            validate_arguments(wrong, schema)
        assert refused.value.code == "invalid_arguments"
    assert _tool("search.characters").title == "Body & Face Finder"
