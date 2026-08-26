from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from cdmw.ui.shell.startup_controller import StartupPromptMixin
from cdmw.workers.archive_scan_workers import ArchiveScanWorker


FEATURE = "new_item_archive_snapshot"


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:  # noqa: N802 - QSettings contract
        self.values[key] = value

    def sync(self) -> None:
        pass


class _StartupHarness(StartupPromptMixin):
    def __init__(self) -> None:
        self.settings = _Settings()


def _record(executable: Path, sha256: str, **extra: object) -> dict[str, object]:
    stat_result = executable.stat()
    return {
        "path": str(executable),
        "sha256": sha256,
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "checked_at": 1.0,
        **extra,
    }


def test_archive_scan_records_a_real_hash_transition_and_preserves_feature_proof(tmp_path: Path) -> None:
    executable = tmp_path / "CrimsonDesert.exe"
    executable.write_bytes(b"new executable")
    executable_key = str(executable).lower()
    previous_hash = "a" * 64
    worker = ArchiveScanWorker(
        tmp_path,
        tmp_path / "cache",
        game_executable_fingerprints={
            executable_key: {
                **_record(executable, previous_hash),
                "mtime_ns": executable.stat().st_mtime_ns - 1,
                "compatible_features": {FEATURE: previous_hash},
            }
        },
    )
    logs: list[str] = []
    worker.log_message.connect(logs.append)

    with patch("cdmw.workers.archive_scan_workers.invalidate_archive_browser_cache", return_value=[]):
        worker._check_game_update_and_invalidate_archive_cache()

    records = worker.updated_game_executable_fingerprints
    assert records is not None
    current = records[executable_key]
    assert current["sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    assert current["previous_sha256"] == previous_hash
    assert float(current["update_detected_at"]) > 0.0
    assert current["compatible_features"] == {FEATURE: previous_hash}
    assert any("Game update detected via CrimsonDesert.exe hash" in message for message in logs)


def test_first_hash_baseline_is_not_recorded_as_an_update(tmp_path: Path) -> None:
    executable = tmp_path / "CrimsonDesert.exe"
    executable.write_bytes(b"first executable")
    worker = ArchiveScanWorker(tmp_path, tmp_path / "cache")

    worker._check_game_update_and_invalidate_archive_cache()

    records = worker.updated_game_executable_fingerprints
    assert records is not None
    current = records[str(executable).lower()]
    assert "previous_sha256" not in current
    assert "update_detected_at" not in current


def test_update_note_requires_direct_old_good_to_current_transition_and_clears_after_success(tmp_path: Path) -> None:
    executable = tmp_path / "CrimsonDesert.exe"
    executable.write_bytes(b"current executable")
    executable_key = str(executable).lower()
    previous_hash = "b" * 64
    current_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    harness = _StartupHarness()
    harness._save_game_executable_fingerprints(
        {
            executable_key: _record(
                executable,
                current_hash,
                previous_sha256=previous_hash,
                update_detected_at=2.0,
                compatible_features={FEATURE: previous_hash},
            )
        }
    )

    assert harness._game_update_feature_error_evidence(tmp_path, FEATURE)

    assert harness._record_game_feature_compatibility(tmp_path, FEATURE)
    assert not harness._game_update_feature_error_evidence(tmp_path, FEATURE)
    saved = json.loads(str(harness.settings.value("archive/game_executable_fingerprints")))
    assert saved[executable_key]["compatible_features"][FEATURE] == current_hash


def test_update_note_refuses_stale_executable_metadata(tmp_path: Path) -> None:
    executable = tmp_path / "CrimsonDesert.exe"
    executable.write_bytes(b"recorded executable")
    executable_key = str(executable).lower()
    previous_hash = "c" * 64
    harness = _StartupHarness()
    harness._save_game_executable_fingerprints(
        {
            executable_key: _record(
                executable,
                hashlib.sha256(executable.read_bytes()).hexdigest(),
                previous_sha256=previous_hash,
                update_detected_at=3.0,
                compatible_features={FEATURE: previous_hash},
            )
        }
    )
    executable.write_bytes(b"changed again before the next archive scan")

    assert not harness._game_update_feature_error_evidence(tmp_path, FEATURE)
