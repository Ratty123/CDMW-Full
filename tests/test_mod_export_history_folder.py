"""Mod export history is filed in the CDMW folder; records filed in AppData earlier are still read."""

from __future__ import annotations

from pathlib import Path

from cdmw.app.app_folder import profile_override, workspace_folder
from cdmw.core import mod_export_history as history

# The module's own functions, before conftest points them at tmp_path for each test.
_HISTORY_ROOT = history._history_root
_LEGACY_ROOT = getattr(history, "_legacy_history_root", None)


def _package(root: Path, payload: bytes = b"mesh bytes") -> Path:
    path = root / "character" / "model" / "a.pac"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    return root


def test_records_are_filed_in_the_cdmw_folder() -> None:
    root = _HISTORY_ROOT()
    assert root == workspace_folder() / "mod_export_history"
    assert root.resolve().is_relative_to(profile_override())  # a test run's own profile


def test_records_filed_in_appdata_earlier_are_still_found_and_kept(tmp_path, monkeypatch) -> None:
    assert _LEGACY_ROOT is not None, "earlier records in AppData would no longer be read"
    current, earlier = tmp_path / "cdmw" / "mod_export_history", tmp_path / "appdata" / "mod_export_history"
    package = _package(tmp_path / "mod")
    # An earlier version filed this package's records in AppData.
    monkeypatch.setattr(history, "_history_root", lambda: earlier)
    monkeypatch.setattr(history, "_legacy_history_root", lambda: earlier)
    history.file_mod_history(package, {"new-item.json": b'{"made": "earlier"}'})
    assert history.mod_metadata_path(package, "new-item.json").read_bytes() == b'{"made": "earlier"}'

    monkeypatch.setattr(history, "_history_root", lambda: current)
    monkeypatch.setattr(history, "_legacy_history_root", lambda: earlier)
    found = history.mod_metadata_path(package, "new-item.json")
    assert found.read_bytes() == b'{"made": "earlier"}' and found.is_relative_to(earlier)
    # A new record for the same bytes goes to the CDMW folder and keeps the earlier one.
    filed = history.file_mod_history(package, {"cdmw-compatibility.json": b"{}"})
    assert filed.is_relative_to(current)
    assert (filed / "new-item.json").read_bytes() == b'{"made": "earlier"}'
    assert history.mod_metadata_path(package, "new-item.json").is_relative_to(current)
    assert (earlier / filed.name / "new-item.json").is_file(), "the earlier record was moved or removed"
