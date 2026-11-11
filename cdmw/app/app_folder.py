"""Where CDMW keeps what it writes: one folder per copy of the app.

Everything CDMW writes derives from :func:`cdmw_folder`: the settings file,
``workspace`` and ``workspace\\temp``. It resolves, in order:

1. ``CDMW_PROFILE_DIR``, a private profile for tests, timing harnesses and the
   automation bridge. A normal launch never sets it.
2. ``CDMW_APP_FOLDER``, the folder a launcher passes when the executable runs
   from somewhere else (the single-file start).
3. The executable's folder in a packaged build, the repository root when run
   from source.

The answer is read once per process. This module imports the standard
library only, so the entry script can call :func:`prepare_process_temp`
before anything else is imported.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

PROFILE_DIR_ENV = "CDMW_PROFILE_DIR"
APP_FOLDER_ENV = "CDMW_APP_FOLDER"
# The temp folder the first CDMW process of a run started with. A few paths
# must be agreed with a program CDMW does not start (the virtual loader's
# installation lock, checked inside the game), so they stay there.
SYSTEM_TEMP_ENV = "CDMW_SYSTEM_TEMP"
WORKSPACE_DIRNAME = "workspace"
TEMP_DIRNAME = "temp"

_folder: Path | None = None


class AppFolderNotWritable(RuntimeError):
    """The CDMW folder cannot hold the app's files."""

    def __init__(self, folder: Path, reason: str) -> None:
        super().__init__(f"CDMW cannot write to its folder {folder}: {reason}")
        self.folder = folder
        self.reason = reason


def default_app_folder() -> Path:
    """The executable's folder, or the repository root from source."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def profile_override() -> Path | None:
    """The private profile folder this process runs in, if any."""

    text = os.environ.get(PROFILE_DIR_ENV, "").strip()
    return Path(text).expanduser().resolve() if text else None


def cdmw_folder() -> Path:
    """The folder that holds this copy's settings, workspace and temp files."""

    global _folder
    if _folder is None:
        override = profile_override()
        if override is not None:
            _folder = override
        else:
            launcher = os.environ.get(APP_FOLDER_ENV, "").strip()
            _folder = Path(launcher).expanduser().resolve() if launcher else default_app_folder()
    return _folder


def workspace_folder() -> Path:
    return cdmw_folder() / WORKSPACE_DIRNAME


def workspace_temp_folder() -> Path:
    return workspace_folder() / TEMP_DIRNAME


def system_temp_dir() -> Path:
    """The temp folder the run started with, before CDMW moved its own."""

    text = os.environ.get(SYSTEM_TEMP_ENV, "").strip()
    return Path(text) if text else Path(tempfile.gettempdir())


def profile_scope() -> str:
    """A short stable name for the profile override, for process-wide names."""

    override = profile_override()
    if override is None:
        return ""
    return "profile-" + hashlib.sha256(str(override).casefold().encode("utf-8")).hexdigest()[:16]


def prepare_process_temp() -> Path:
    """Point this process and its children at ``workspace\\temp``.

    Sets :data:`tempfile.tempdir` and the ``TMP``, ``TEMP`` and ``TMPDIR``
    variables, which child processes inherit, and records the temp folder the
    run started with. Raises :class:`AppFolderNotWritable` instead of falling
    back to the system's temp folder.
    """

    os.environ.setdefault(SYSTEM_TEMP_ENV, tempfile.gettempdir())
    target = workspace_temp_folder()
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / f".write-check-{os.getpid()}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        raise AppFolderNotWritable(cdmw_folder(), exc.strerror or str(exc)) from exc
    text = str(target)
    for name in ("TMP", "TEMP", "TMPDIR"):
        os.environ[name] = text
    tempfile.tempdir = text
    return target


def report_unwritable_folder(error: AppFolderNotWritable) -> None:
    """Say plainly that the folder is read-only; there is no Qt yet."""

    message = (
        f"Crimson Desert Mod Workbench keeps its settings, workspace and temporary files in its own folder:\n\n"
        f"{error.folder}\n\nThat folder cannot be written to ({error.reason}). "
        "Move CDMW to a folder you can write to, for example one in your user folder, and start it again."
    )
    try:
        sys.stderr.write(message + "\n")
    except Exception:
        pass
    if os.name == "nt" and not os.environ.get("CDMW_NO_DIALOGS"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Crimson Desert Mod Workbench", 0x10)
        except Exception:
            pass


def _reset_for_tests() -> None:
    global _folder
    _folder = None
