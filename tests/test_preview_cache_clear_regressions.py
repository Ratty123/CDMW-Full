import threading

import pytest

from cdmw.rendering import native_preview_package_cache as cache
from tests.test_native_preview_package_cache_concurrency import _raw_cache_entry, _validate


@pytest.mark.parametrize("operation", ["scan", "prune", "evict", "clear_during_scan"])
def test_old_snapshot_cannot_overwrite_concurrent_cache_changes(tmp_path, monkeypatch, operation):
    _raw_cache_entry(tmp_path, "old")
    scanned, resume = threading.Event(), threading.Event()
    read = cache._read_metadata
    failures = []

    def pause_after_snapshot(entry):
        result = read(entry)
        if threading.current_thread() is reader and not scanned.is_set():
            scanned.set()
            assert resume.wait(5)
        return result

    def inspect():
        try:
            if operation in {"scan", "clear_during_scan"}:
                cache._cached_total_bytes(tmp_path)
            else:
                cache.prune_native_preview_package_cache(
                    tmp_path, max_bytes=1 if operation == "evict" else 1000, target_bytes=0,
                )
        except BaseException as exc:
            failures.append(exc)

    reader = threading.Thread(target=inspect)
    monkeypatch.setattr(cache, "_read_metadata", pause_after_snapshot)
    reader.start()
    try:
        assert scanned.wait(3)
        if operation == "clear_during_scan":
            cache.clear_native_preview_package_cache(tmp_path)
            assert cache._cached_total_bytes(tmp_path) == 0
        else:
            staging = _raw_cache_entry(tmp_path, "_staging_new")
            cache.store_native_preview_package_cache(
                tmp_path, "new", staging, {}, validate_package=_validate, max_bytes=1000, target_bytes=800,
            )
            assert cache._cached_total_bytes(tmp_path) == 132
    finally:
        resume.set()
        reader.join(5)
    assert not reader.is_alive()
    assert not failures
    expected = {"scan": 132, "prune": 132, "evict": 66, "clear_during_scan": 0}[operation]
    assert cache._cached_total_bytes(tmp_path) == expected


def test_clear_recounts_active_survivor_and_next_write_enforces_budget(tmp_path):
    active = _raw_cache_entry(tmp_path, "active")
    lease = cache.acquire_native_preview_package_cache_lease_for_path(active / "package")
    assert cache._cached_total_bytes(tmp_path) == 66
    try:
        cache.clear_native_preview_package_cache(tmp_path)
        assert active.exists()
        assert cache._cached_total_bytes(tmp_path) == 66
    finally:
        lease.release()
    staging = _raw_cache_entry(tmp_path, "_staging_next")
    hit = cache.store_native_preview_package_cache(
        tmp_path, "next", staging, {}, validate_package=_validate, max_bytes=100, target_bytes=80,
    )
    assert hit is not None
    assert hit.package_dir.exists()
    assert not active.exists()
    assert cache._cached_total_bytes(tmp_path) == 66


def test_clear_skips_busy_publisher_without_waiting(tmp_path):
    busy = _raw_cache_entry(tmp_path, "busy")
    disposable = _raw_cache_entry(tmp_path, "disposable")
    acquired, release, finished = threading.Event(), threading.Event(), threading.Event()

    def publisher():
        with cache.native_preview_package_cache_build_lock(tmp_path, "busy"):
            acquired.set()
            release.wait(5)

    def clear():
        cache.clear_native_preview_package_cache(tmp_path)
        finished.set()

    publisher_thread = threading.Thread(target=publisher)
    clear_thread = threading.Thread(target=clear)
    publisher_thread.start()
    try:
        assert acquired.wait(2)
        clear_thread.start()
        assert finished.wait(1), "clear waited for the publisher's lock"
        assert busy.exists()
        assert not disposable.exists()
        assert cache._cached_total_bytes(tmp_path) == 66
    finally:
        release.set()
        publisher_thread.join(5)
        if clear_thread.ident is not None:
            clear_thread.join(5)
    assert not publisher_thread.is_alive() and not clear_thread.is_alive()


def test_failed_deletion_stays_in_cache_accounting(tmp_path, monkeypatch):
    survivor = _raw_cache_entry(tmp_path, "locked_file")
    assert cache._cached_total_bytes(tmp_path) == 66
    monkeypatch.setattr(cache.shutil, "rmtree", lambda *args, **kwargs: None)
    cache.clear_native_preview_package_cache(tmp_path)
    assert survivor.exists()
    assert cache._cached_total_bytes(tmp_path) == 66


def test_publisher_increment_does_not_replace_invalidated_total(tmp_path):
    _raw_cache_entry(tmp_path, "survivor")
    cache._set_cached_total_bytes(tmp_path, 66)
    cache._invalidate_cached_total_bytes(tmp_path)
    _raw_cache_entry(tmp_path, "newly_published")
    cache._add_cached_total_bytes(tmp_path, 66)
    assert cache._cached_total_bytes(tmp_path) == 132
