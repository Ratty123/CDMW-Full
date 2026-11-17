"""AI connections: a windowed build's bridge still tells the client's log why it cannot connect."""
from __future__ import annotations

import io
import os
import sys
from types import SimpleNamespace

import pytest

from cdmw.mcp import bridge

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


def test_a_windowed_bridge_writes_its_reason_to_the_handle_the_client_passed(monkeypatch, tmp_path) -> None:
    import _winapi
    import msvcrt

    log = tmp_path / "client-log.txt"
    holder = open(log, "wb")
    try:
        # The client's stderr, as a windowed CDMW.exe receives it: a handle, and no sys.stderr.
        handle = msvcrt.get_osfhandle(os.dup(holder.fileno()))
        monkeypatch.setattr(_winapi, "GetStdHandle", lambda which: handle if which == -12 else None)
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO()))
        monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=io.BytesIO()))
        monkeypatch.setattr(sys, "stderr", None)
        _stdin, _stdout, stderr = bridge._std_streams()
        stderr.write("cdmw-mcp: the reason\n")
        stderr.flush()
        stderr.close()
    finally:
        holder.close()
    assert log.read_text(encoding="utf-8") == "cdmw-mcp: the reason\n"


def test_without_any_handle_the_reason_goes_nowhere_and_nothing_fails(monkeypatch) -> None:
    import _winapi

    monkeypatch.setattr(_winapi, "GetStdHandle", lambda which: None)
    monkeypatch.setattr(sys, "stderr", None)
    stderr = bridge._std_error()
    stderr.write("nobody reads this\n")
    stderr.close()
