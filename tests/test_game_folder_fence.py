"""No test can write under a real Crimson Desert installation (tests/conftest.py's fence).

The probes name paths that do not exist, so without the fence they fail with
"not found" and write nothing; with it they are refused first.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from tests import conftest

GAME = Path(conftest._REAL_GAME_FOLDERS[0])


def _absent() -> Path:
    return GAME / f".cdmw-fence-probe-{uuid4().hex}" / "probe.bin"


def test_the_real_game_folder_is_fenced() -> None:
    assert conftest._fenced(GAME / "0009" / "0.paz")
    assert conftest._fenced(str(GAME).upper() + "\\META\\0.PAPGT")  # Windows paths ignore case
    assert not conftest._fenced(Path(str(GAME) + " Backup") / "0.paz")  # a sibling is not the game


@pytest.mark.parametrize("write", [
    lambda path: open(path, "wb"),
    lambda path: open(path, "a", encoding="utf-8"),
    lambda path: path.write_bytes(b"x"),
    lambda path: os.open(path, os.O_WRONLY | os.O_CREAT),
    lambda path: os.remove(path),
    lambda path: os.replace(path, path.with_suffix(".old")),
    lambda path: shutil.rmtree(path.parent),
    lambda path: shutil.copyfile(__file__, path),
], ids=["open-wb", "open-a", "write_bytes", "os.open", "remove", "replace", "rmtree", "copyfile"])
def test_a_write_under_the_real_game_folder_is_refused(write) -> None:
    with pytest.raises(PermissionError, match="real game installation"):
        write(_absent())


def test_reading_the_real_game_folder_is_still_allowed(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        open(_absent(), "rb")
    (tmp_path / "x").write_bytes(b"ok")  # and writes elsewhere are untouched
