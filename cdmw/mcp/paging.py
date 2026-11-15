"""Large results in pages (P13 stage C, design record 2.4 step 5).

A paged tool names the list in its result (``Tool.paged``). The server
returns the first ``limit`` rows with ``total`` and, when more remain, a
``next_page_token``; calling the same tool with that token returns the next
page from what was already found, without searching again. Tokens belong to
one tool and expire after ``TOKEN_LIFETIME_S``.
"""

from __future__ import annotations

import secrets
import threading
import time

from cdmw.mcp.errors import INVALID_ARGUMENTS, NOT_FOUND, ToolError

TOKEN_LIFETIME_S = 15 * 60
MAX_STORED = 64


class _Stored:
    def __init__(self, tool: str, field: str, rows: list, rest: dict, offset: int = 0,
                 created: float | None = None) -> None:
        self.tool, self.field, self.rows, self.rest, self.offset = tool, field, rows, rest, offset
        self.created = time.monotonic() if created is None else created


class PageStore:
    def __init__(self) -> None:
        self._pages: dict[str, _Stored] = {}
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = time.monotonic()
        for token in [t for t, s in self._pages.items() if now - s.created > TOKEN_LIFETIME_S]:
            del self._pages[token]
        while len(self._pages) > MAX_STORED:
            oldest = min(self._pages, key=lambda t: self._pages[t].created)
            del self._pages[oldest]

    def _page(self, stored: _Stored, offset: int, limit: int) -> dict[str, object]:
        rows = stored.rows[offset:offset + limit]
        page = {**stored.rest, stored.field: rows, "total": len(stored.rows), "offset": offset}
        following = offset + len(rows)
        if following < len(stored.rows):
            token = secrets.token_hex(12)
            with self._lock:
                self._pages[token] = _Stored(stored.tool, stored.field, stored.rows, stored.rest, following,
                                             stored.created)
                self._expire()
            page["next_page_token"] = token
        return page

    def first(self, tool: str, field: str, result: object, limit: int) -> object:
        if not isinstance(result, dict) or not isinstance(result.get(field), (list, tuple)):
            return result
        rest = {k: v for k, v in result.items() if k != field}
        return self._page(_Stored(tool, field, list(result[field]), rest), 0, limit)

    def next(self, tool: str, token: str, limit: int) -> dict[str, object]:
        with self._lock:
            self._expire()
            stored = self._pages.pop(str(token), None)
        if stored is None:
            raise ToolError(NOT_FOUND, "That page is gone: it was already read or is more than 15 minutes old. "
                                       "Run the search again.")
        if stored.tool != tool:
            raise ToolError(INVALID_ARGUMENTS, "That page token belongs to another tool.")
        return self._page(stored, stored.offset, limit)
