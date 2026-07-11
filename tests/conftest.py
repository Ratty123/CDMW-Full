from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_CACHE_ENV = "CDMW_TEMP_CACHE_ROOT"
_original_cache_root: str | None = None
_pytest_cache_root: Path | None = None


def pytest_configure() -> None:
    global _original_cache_root, _pytest_cache_root
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
