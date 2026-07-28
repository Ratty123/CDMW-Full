from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_CACHE_ENV = "CDMW_TEMP_CACHE_ROOT"
_original_cache_root: str | None = None
_pytest_cache_root: Path | None = None


def _canonicalize_temp_root() -> None:
    """Make `tempfile` hand out the long form of the temp directory.

    On the GitHub runner `%TEMP%` is the 8.3 short form
    (`C:\\Users\\RUNNER~1\\AppData\\Local\\Temp`), so a test that builds an
    expected path from `tempfile` and compares it against one the application
    produced fails on the name rather than on the behaviour: the app resolves,
    and `C:\\Users\\RUNNER~1\\...` != `C:\\Users\\runneradmin\\...` even though
    both name the same directory. Nineteen tests across thirteen files failed
    that way and none of them was about short names.

    Both forms address the same directory, so resolving here changes what the
    comparison sees and nothing about where files go.
    """

    try:
        resolved = str(Path(tempfile.gettempdir()).resolve())
    except OSError:
        return
    tempfile.tempdir = resolved
    for variable in ("TMP", "TEMP", "TMPDIR"):
        if os.environ.get(variable):
            os.environ[variable] = resolved


def pytest_configure() -> None:
    global _original_cache_root, _pytest_cache_root
    _canonicalize_temp_root()
    _original_cache_root = os.environ.get(_CACHE_ENV)
    _pytest_cache_root = Path(tempfile.mkdtemp(prefix="cdmw-pytest-cache-"))
    os.environ[_CACHE_ENV] = str(_pytest_cache_root)


def pytest_unconfigure() -> None:
    if _original_cache_root is None:
        os.environ.pop(_CACHE_ENV, None)
    else:
        os.environ[_CACHE_ENV] = _original_cache_root
    if _pytest_cache_root is not None:
        shutil.rmtree(_pytest_cache_root, ignore_errors=True)
