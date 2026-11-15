"""REPORT-crash item 3: a failed SetParent is seen and reported, not passed as success."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from cdmw.ui.preview import dotnet_host_protocol as protocol

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 only")


class _Host(protocol.DotNetPreviewHostProtocolMixin):
    def __init__(self) -> None:
        self._embedded_child_hwnd = 77
        self.controller = SimpleNamespace(process_id=4242)
        self.shown: list[tuple[str, bool]] = []
        self.sized = False

    def _host_hwnd(self) -> int:
        return 99

    def show_preparation_status(self, message: str, *, hold: bool = False, busy: bool = True) -> None:
        self.shown.append((message, busy))


def test_a_reparent_that_fails_stops_and_says_so(monkeypatch) -> None:
    import ctypes

    host = _Host()

    def owner(_hwnd, pid):
        pid._obj.value = 4242
        return 1

    def set_parent(_child, _parent):
        ctypes.set_last_error(1400)  # ERROR_INVALID_WINDOW_HANDLE
        return None

    def size(*_args):
        host.sized = True
        return 1

    fake = SimpleNamespace(IsWindow=lambda _h: 1, GetWindowThreadProcessId=owner, GetParent=lambda _h: None,
                           SetParent=set_parent, GetClientRect=lambda *_a: 1, SetWindowPos=size)
    monkeypatch.setattr(protocol, "_typed_user32", lambda: fake)
    host._sync_embedded_child_geometry()
    assert not host.sized, "a window that was never parented to the viewport was sized to it"
    assert host.embedding_error == protocol.EMBEDDING_FAILED.format(code=1400)
    assert host.shown == [(host.embedding_error, False)]
