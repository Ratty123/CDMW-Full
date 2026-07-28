"""The conftest hook that stops 8.3 short names failing path comparisons.

The GitHub runner sets `%TEMP%` to `C:\\Users\\RUNNER~1\\AppData\\Local\\Temp`.
A test that builds an expected path from `tempfile` and compares it against one
the application produced then fails on the spelling rather than the behaviour,
because the application resolves and the test did not. This pins the fix so it
cannot be quietly removed by someone who cannot reproduce the failure locally.
"""

from __future__ import annotations

import ctypes
import os
import tempfile
from pathlib import Path

import pytest

from tests.conftest import _canonicalize_temp_root


def _short_path_name(path: Path) -> str:
    """The 8.3 alias Windows keeps for `path`, or "" when it has none."""

    if os.name != "nt":
        return ""
    buffer = ctypes.create_unicode_buffer(1024)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value if 0 < length < len(buffer) else ""


@pytest.mark.skipif(os.name != "nt", reason="8.3 aliases are a Windows behaviour")
def test_a_short_named_temp_root_is_restored_to_its_long_form(monkeypatch, tmp_path) -> None:
    # A directory whose name cannot fit 8.3, so Windows keeps an alias for it --
    # the same situation as `runneradmin` on the runner. Testing against the real
    # temp root would skip on any machine whose user name already fits.
    long_form = tmp_path / "canonicalization-probe-directory"
    long_form.mkdir()
    long_form = long_form.resolve()
    short_form = _short_path_name(long_form)
    if not short_form or Path(short_form) == long_form:
        pytest.skip("8.3 alias creation is disabled on this volume")

    monkeypatch.setenv("TEMP", short_form)
    monkeypatch.setenv("TMP", short_form)
    monkeypatch.setattr(tempfile, "tempdir", short_form)

    _canonicalize_temp_root()

    assert Path(tempfile.gettempdir()) == long_form
    assert Path(os.environ["TEMP"]) == long_form
    # The point of the exercise: a path built from tempfile now compares equal
    # to the same path after the application resolves it.
    built = Path(tempfile.gettempdir()) / "cache" / "probe.bin"
    assert built == built.resolve()


def test_the_configured_temp_root_needs_no_further_resolving() -> None:
    """Whatever the environment handed us, `tempfile` is already canonical."""

    root = Path(tempfile.gettempdir())
    assert root == root.resolve()
