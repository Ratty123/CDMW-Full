"""The UI thread's preview package check is not repeated while the package is unchanged.

The review measured 275 ms (Honor Guard set) and 108 ms (reselecting a model)
on the UI thread in the containment walk of the resident package check, and
the manifest parse before it. A package this process found valid is trusted
again while its manifest and every folder holding its files keep their
identity; a prune, an added or removed file, or a rewritten manifest makes
the next check walk again.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from cdmw.services import json_file_facts
from cdmw.services import mesh_rust_preview_files as preview_files
from cdmw.services import mesh_rust_preview_package as preview_package
from cdmw.services.mesh_rust_preview_cache import validate_resident_rust_preview_package


@pytest.fixture(autouse=True)
def _fresh_memos():
    getattr(preview_package, "forget_valid_preview_packages", lambda: None)()
    json_file_facts.forget_json_file_facts()
    yield
    getattr(preview_package, "forget_valid_preview_packages", lambda: None)()
    json_file_facts.forget_json_file_facts()


def _age(root: Path, seconds: float = 60.0) -> None:
    past = time.time() - seconds
    paths = sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    for path in [*paths, root]:
        os.utime(path, (past, past))


@pytest.fixture
def package(tmp_path) -> Path:
    built = preview_package.build_rust_preview_prewarm_package(tmp_path / "cache")
    _age(tmp_path / "cache")
    return Path(built.package_dir)


@pytest.fixture
def walks(monkeypatch):
    calls = []
    real = preview_files._contained_file

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(preview_files, "_contained_file", counting)
    return calls


@pytest.fixture
def parses(monkeypatch):
    calls = []
    real = json.loads

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(json, "loads", counting)
    return calls


def test_unchanged_package_is_not_walked_or_parsed_again(package, walks, parses):
    assert validate_resident_rust_preview_package(package) == (True, ())
    assert walks, "the first check walks the package"
    walked, parsed = len(walks), len(parses)
    for _ in range(3):
        assert validate_resident_rust_preview_package(package) == (True, ())
    assert len(walks) == walked
    assert len(parses) == parsed


def test_a_pruned_file_is_found_again(package, walks):
    assert validate_resident_rust_preview_package(package)[0] is True
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    document = package / manifest["document"]["path"]
    document.unlink()
    valid, missing = validate_resident_rust_preview_package(package)
    assert valid is False and missing


def test_a_rewritten_manifest_is_checked_again(package, walks):
    assert validate_resident_rust_preview_package(package)[0] is True
    walked = len(walks)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["session_id"] = ""
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    valid, missing = validate_resident_rust_preview_package(package)
    assert valid is False and missing


def test_package_from_path_reads_its_session_once(package, parses):
    first = preview_package.rust_preview_package_from_path(package)
    parsed = len(parses)
    again = preview_package.rust_preview_package_from_path(package)
    assert again.scene_session_id == first.scene_session_id != ""
    assert len(parses) == parsed


def test_full_checks_always_run_in_full(package, walks):
    assert preview_package.validate_rust_preview_package(package, hash_unverified=True) == ()
    walked = len(walks)
    assert preview_package.validate_rust_preview_package(package, hash_unverified=True) == ()
    assert len(walks) > walked


def test_the_workers_full_check_primes_the_ui_check(package, walks):
    from cdmw.services.mesh_rust_preview_cache import validate_rust_preview_cache_package

    assert validate_rust_preview_cache_package(package) == (True, ())
    walked = len(walks)
    assert validate_resident_rust_preview_package(package) == (True, ())
    assert len(walks) == walked, "the UI check walked a package the worker had just checked"


def test_a_package_written_just_now_is_not_remembered(tmp_path, walks):
    fresh = preview_package.build_rust_preview_prewarm_package(tmp_path / "fresh-cache")
    assert validate_resident_rust_preview_package(fresh.package_dir) == (True, ())
    walked = len(walks)
    assert validate_resident_rust_preview_package(fresh.package_dir) == (True, ())
    assert len(walks) > walked


def test_coarse_volume_times_are_not_trusted(package, walks):
    whole = (int(time.time()) - 60) * 1_000_000_000
    for path in [*package.rglob("*"), package]:
        os.utime(path, ns=(whole, whole))
    assert validate_resident_rust_preview_package(package) == (True, ())
    walked = len(walks)
    assert validate_resident_rust_preview_package(package) == (True, ())
    assert len(walks) > walked
