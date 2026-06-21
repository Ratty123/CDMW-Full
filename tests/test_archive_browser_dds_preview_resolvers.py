from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.dds_preview_resolvers import (
    archive_dds_preview_resolver_pair,
    archive_dds_preview_source_for_path,
    archive_dds_preview_sources_for_basename,
)


def test_archive_dds_preview_source_for_path_normalizes_filters_and_skips_failures(tmp_path: Path) -> None:
    valid = tmp_path / "valid.dds"
    valid.write_bytes(b"dds")
    missing = tmp_path / "missing.dds"
    bad_entry = SimpleNamespace(extension=".dds", output=missing)
    non_dds_entry = SimpleNamespace(extension=".png", output=valid)
    valid_entry = SimpleNamespace(extension=".DDS", output=valid)
    failing_entry = SimpleNamespace(extension=".dds", fail=True)

    def ensure(entry: object) -> tuple[object, str]:
        if getattr(entry, "fail", False):
            raise RuntimeError("failed")
        return getattr(entry, "output", None), ""

    assert archive_dds_preview_source_for_path(
        r"Textures\Target.dds",
        {"textures/target.dds": (non_dds_entry, failing_entry, bad_entry, valid_entry)},
        ensure_preview_source=ensure,
    ) == valid
    assert archive_dds_preview_source_for_path("", {}, ensure_preview_source=ensure) is None


def test_archive_dds_preview_sources_for_basename_returns_existing_dds_paths(tmp_path: Path) -> None:
    first = tmp_path / "first.dds"
    second = tmp_path / "second.dds"
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    entries = (
        SimpleNamespace(extension=".dds", output=first),
        SimpleNamespace(extension=".png", output=tmp_path / "skip.png"),
        SimpleNamespace(extension=".dds", output=second),
    )

    assert archive_dds_preview_sources_for_basename(
        r"nested\Target.dds",
        {"target.dds": entries},
        ensure_preview_source=lambda entry: (getattr(entry, "output", None), ""),
    ) == (first, second)
    assert archive_dds_preview_sources_for_basename("", {}, ensure_preview_source=lambda _entry: (None, "")) == ()


def test_archive_dds_preview_resolver_pair_closes_over_entry_indexes(tmp_path: Path) -> None:
    first = tmp_path / "first.dds"
    second = tmp_path / "second.dds"
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    entries = (
        SimpleNamespace(extension=".dds", output=first),
        SimpleNamespace(extension=".dds", output=second),
    )

    resolve_path, resolve_basename = archive_dds_preview_resolver_pair(
        {"textures/target.dds": entries},
        {"target.dds": entries},
        ensure_preview_source=lambda entry: (getattr(entry, "output", None), ""),
    )

    assert resolve_path(r"Textures\Target.dds") == first
    assert resolve_basename("target.dds") == (first, second)
