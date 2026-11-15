"""Settings objects for tests that live in the run's private profile, never the registry.

A QSettings built from an organisation and an application name always uses the
native format, which on Windows is the registry (here `HKEY_CURRENT_USER\\Software\\
CDMWTests`), and `setDefaultFormat` does not change that constructor. Every run added
keys there, many with a unique name per run. This gives the same named store as an
INI file in the CDMW folder, which tests/conftest.py makes the run's temporary profile.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QSettings


def owned_settings(name: str) -> QSettings:
    """An INI-file QSettings named ``name`` in the run's profile."""

    from cdmw.app.app_folder import cdmw_folder

    folder = cdmw_folder() / "test-settings"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)) or "settings"
    return QSettings(str(folder / f"{safe}.ini"), QSettings.Format.IniFormat)
