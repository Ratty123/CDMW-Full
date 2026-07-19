from __future__ import annotations

from cdmw.domain.archives.backend_mode import (
    ARCHIVE_BACKEND_ENV,
    ArchiveBackendMode,
    resolve_archive_backend_mode,
)


def test_archive_backend_mode_defaults_to_v2_without_persistent_setting() -> None:
    selection = resolve_archive_backend_mode({})

    assert selection.mode is ArchiveBackendMode.V2
    assert selection.configured_value == ""
    assert selection.valid
    assert selection.displays_v2
    assert not selection.runs_shadow


def test_archive_backend_mode_accepts_only_developer_rollout_values() -> None:
    assert resolve_archive_backend_mode({ARCHIVE_BACKEND_ENV: " legacy "}).mode is ArchiveBackendMode.LEGACY
    assert resolve_archive_backend_mode({ARCHIVE_BACKEND_ENV: "V2"}).displays_v2
    assert resolve_archive_backend_mode({ARCHIVE_BACKEND_ENV: "shadow"}).runs_shadow


def test_invalid_archive_backend_mode_uses_v2_with_diagnostic_evidence() -> None:
    selection = resolve_archive_backend_mode({ARCHIVE_BACKEND_ENV: "automatic"})

    assert selection.mode is ArchiveBackendMode.V2
    assert selection.configured_value == "automatic"
    assert not selection.valid
