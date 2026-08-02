"""Delta temp cleanup is budgeted at exit and swept in the background later.

A sculpt session tracks one delta payload per accepted stroke sample; the
unbounded exit cleanup walked every one of them on the GUI thread and Windows
reported the window hung for 46+ seconds (recorded 2026-08-02 15:12, stack
inside ``shutil.rmtree`` under ``cleanup_native_preview_delta_paths``). The
cleanup now takes a time budget and reports what it left behind, and the
stale sweep removes abandoned entries -- by prefix and age only -- the next
time the Mesh Editor allocates a delta.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from cdmw.modding import mesh_native_core_temp_paths as temp_paths


def _track_files(tmp_path: Path, count: int) -> list[Path]:
    created = []
    for index in range(count):
        path = tmp_path / f"cdmw_mesh_preview_delta_test_{index}.bin"
        path.write_bytes(b"x")
        created.append(path)
        with temp_paths._native_preview_delta_paths_lock:
            temp_paths._native_preview_delta_paths.add(path)
    return created


def test_a_zero_budget_leaves_work_behind_and_reports_it(tmp_path: Path) -> None:
    created = _track_files(tmp_path, 8)
    try:
        remaining = temp_paths.cleanup_native_preview_delta_paths(time_budget_seconds=0.0)
        # A zero budget deletes at most the first entry per loop before the
        # deadline check trips; most of the batch must be reported undone.
        assert remaining >= len(created) - 2
    finally:
        for path in created:
            path.unlink(missing_ok=True)


def test_an_unbudgeted_cleanup_still_deletes_everything(tmp_path: Path) -> None:
    created = _track_files(tmp_path, 5)
    remaining = temp_paths.cleanup_native_preview_delta_paths()
    assert remaining == 0
    assert not [path for path in created if path.exists()]


def test_the_stale_sweep_removes_only_old_prefixed_entries(tmp_path: Path) -> None:
    stale_file = tmp_path / "cdmw_mesh_preview_delta_stale.bin"
    stale_dir = tmp_path / "cdmw_mesh_editor_delta_stale"
    fresh_file = tmp_path / "cdmw_mesh_preview_delta_fresh.bin"
    unrelated = tmp_path / "unrelated_delta.bin"
    stale_file.write_bytes(b"x")
    stale_dir.mkdir()
    (stale_dir / "payload.bin").write_bytes(b"x")
    fresh_file.write_bytes(b"x")
    unrelated.write_bytes(b"x")
    old = time.time() - 7200.0
    os.utime(stale_file, (old, old))
    os.utime(stale_dir, (old, old))

    removed = temp_paths.sweep_stale_native_preview_delta_temp(
        max_age_seconds=1800.0,
        temp_root=tmp_path,
    )

    assert removed == 2
    assert not stale_file.exists()
    assert not stale_dir.exists()
    assert fresh_file.exists()
    assert unrelated.exists()


def test_the_sweep_skips_entries_tracked_by_this_process(tmp_path: Path) -> None:
    tracked = tmp_path / "cdmw_mesh_preview_delta_tracked.bin"
    tracked.write_bytes(b"x")
    old = time.time() - 7200.0
    os.utime(tracked, (old, old))
    with temp_paths._native_preview_delta_paths_lock:
        temp_paths._native_preview_delta_paths.add(tracked)
    try:
        removed = temp_paths.sweep_stale_native_preview_delta_temp(
            max_age_seconds=1800.0,
            temp_root=tmp_path,
        )
        assert removed == 0
        assert tracked.exists()
    finally:
        with temp_paths._native_preview_delta_paths_lock:
            temp_paths._native_preview_delta_paths.discard(tracked)
        tracked.unlink(missing_ok=True)
