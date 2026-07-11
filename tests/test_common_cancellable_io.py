from __future__ import annotations

import threading
from pathlib import Path

import pytest

from cdmw.core.common import read_file_bytes_cancellable, read_text_file_cancellable
from cdmw.models import RunCancelled


def test_cancellable_file_read_enforces_limit_and_decodes_text(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("hello", encoding="utf-8")
    assert read_file_bytes_cancellable(source, max_bytes=5) == b"hello"
    assert read_text_file_cancellable(source, max_bytes=5) == "hello"
    with pytest.raises(ValueError, match="too large"):
        read_file_bytes_cancellable(source, max_bytes=4)


def test_cancellable_file_read_stops_before_io(tmp_path: Path) -> None:
    source = tmp_path / "sample.bin"
    source.write_bytes(b"payload")
    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled):
        read_file_bytes_cancellable(source, stop_event=stop_event)
