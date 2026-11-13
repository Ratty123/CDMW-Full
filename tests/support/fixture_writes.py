"""File writers for tests/support's rebuilt old installs (decision 46).

The modules here recreate, in owned game copies under tmp_path, what an older CDMW
wrote into the game, so the removal and Restore Backup have something real to work
on. CDMW's own writers (``cdmw.core.atomic_file``) refuse every game folder, so these
fixtures write with these instead: same publish-by-replace behaviour, no guard.
Nothing under ``cdmw/`` may import this module.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


@contextmanager
def atomic_binary_writer(path: Path | str, *, durable: bool = True) -> Iterator[BinaryIO]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            yield handle
            handle.flush()
            if durable:
                os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_bytes(path: Path | str, data: bytes, *, durable: bool = True) -> None:
    with atomic_binary_writer(path, durable=durable) as handle:
        handle.write(data)


def atomic_copy_file(source: Path | str, destination: Path | str) -> None:
    with Path(source).open("rb") as source_handle, atomic_binary_writer(destination) as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
