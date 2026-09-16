from __future__ import annotations

import io
import os
from pathlib import Path
import time
from unittest.mock import patch

import pytest

from cdmw.models import RunCancelled
from cdmw.rendering import native_preview_temp as temp
from cdmw.rendering.native_preview_core import NativePreviewCoreServiceClient


@pytest.fixture
def owned_job(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(temp.tempfile, "tempdir", str(tmp_path))
    root = temp.create_preview_job_root()
    yield root
    temp.remove_preview_job_root(root)


@pytest.mark.parametrize("stopped", [False, True])
def test_cancelled_service_job_cleans_only_after_its_process_stops(owned_job: Path, stopped: bool):
    class Process:
        stdin = io.StringIO()

        def poll(self):
            return 0 if stopped else None

    client = NativePreviewCoreServiceClient(Path("unused-helper.exe"))
    client._process = Process()
    job = owned_job / "job.json"
    job.write_text("{}", encoding="utf-8")
    with (
        patch.object(client, "_start_locked"),
        patch.object(client, "_read_stdout_line_locked", side_effect=RunCancelled("cancel")),
        pytest.raises(RunCancelled),
    ):
        client.preview_job(job, owned_job / "report.json", timeout_seconds=1.0)
    assert job.exists() is not stopped
    client._process = None


def test_sweep_preserves_live_owner_and_removes_abandoned_marked_job(owned_job: Path):
    earlier = time.time() - 3600
    os.utime(owned_job, (earlier, earlier))
    assert temp.sweep_abandoned_preview_jobs(owned_job.parent) == 0
    # A second file handle must not acquire a live owner's lock, even when its
    # process-local registry is unavailable (as in a second CDMW instance).
    handle = temp._owners.pop(owned_job)
    try:
        assert temp.sweep_abandoned_preview_jobs(owned_job.parent) == 0
    finally:
        handle.close()
    assert temp.sweep_abandoned_preview_jobs(owned_job.parent) == 1
    assert not owned_job.exists()


def test_sweep_leaves_unknown_folders_and_recent_abandoned_jobs(owned_job: Path):
    unknown = owned_job.parent / "cdmw_preview_core_unowned"
    unknown.mkdir()
    (unknown / "keep.txt").write_text("user data", encoding="utf-8")
    earlier = time.time() - 86400
    os.utime(unknown, (earlier, earlier))
    handle = temp._owners.pop(owned_job)
    handle.close()
    assert temp.sweep_abandoned_preview_jobs(owned_job.parent) == 0
    assert (unknown / "keep.txt").read_text(encoding="utf-8") == "user data"
    assert owned_job.exists()
    # The test owns this marked folder, so it can remove it without age gating.
    assert temp.sweep_abandoned_preview_jobs(owned_job.parent, min_age_seconds=0) == 1


def test_remove_does_not_delete_an_unowned_path(tmp_path: Path):
    (tmp_path / "keep").touch()
    temp.remove_preview_job_root(tmp_path)
    assert (tmp_path / "keep").exists()


def test_unconfirmed_helper_is_not_swept_after_owner_disappears(owned_job: Path):
    temp.retain_preview_job_for_helper(owned_job)
    handle = temp._owners.pop(owned_job)
    handle.close()
    assert temp.sweep_abandoned_preview_jobs(owned_job.parent, min_age_seconds=0) == 0
    assert owned_job.exists()
