from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.report_format_decode_progress import (  # noqa: E402
    DECODE_WEIGHTS,
    MANIFEST_PATH,
    REPORT_PATH,
    ManifestError,
    load_manifest,
    main,
    render_report,
    summarize,
    validate,
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return load_manifest()


@pytest.fixture(scope="module")
def entries(manifest: dict) -> list[dict]:
    return list(manifest["extensions"])


def test_manifest_entries_are_valid(entries: list[dict]) -> None:
    validate(entries)


def test_every_entry_carries_progress_fields(entries: list[dict]) -> None:
    for entry in entries:
        for field in ("origin", "decode", "write", "priority", "archive_files", "evidence", "remaining"):
            assert field in entry, f"{entry['extension']} is missing {field}"


def test_archive_counts_match_the_shipped_build_inventory(entries: list[dict]) -> None:
    from tools.report_format_decode_progress import load_inventory

    inventory = load_inventory()
    assert inventory, "the extension inventory should be committed alongside the manifest"
    for entry in entries:
        expected = inventory.get(entry["extension"], 0)
        assert entry["archive_files"] == expected, (
            f"{entry['extension']} claims {entry['archive_files']} files, inventory says {expected}"
        )


def test_formats_absent_from_the_build_are_not_claimed_as_gaps(entries: list[dict]) -> None:
    # .ui was carried here for years as a high-priority binary format. The build ships
    # none, so it cannot be a gap; the guard stops that being reintroduced silently.
    for entry in entries:
        if entry["archive_files"] == 0:
            assert entry["priority"] == "none", (
                f"{entry['extension']} is not in the shipped build but is ranked "
                f"{entry['priority']}"
            )


def test_stored_progress_matches_recomputed(manifest: dict, entries: list[dict]) -> None:
    assert manifest.get("progress") == summarize(entries), (
        "run: python tools/report_format_decode_progress.py --write"
    )


def _require_generated_report() -> Path:
    """The rendered progress report, which lives under the local-only docs tree.

    The manifest it is rendered from is committed and is checked above, so the
    contract that matters is still enforced everywhere. This pair only asks
    whether the rendered copy on disk is current, which is a question a fresh
    clone cannot answer because it never receives one.
    """

    if not REPORT_PATH.exists():
        pytest.skip(f"{REPORT_PATH.name} is local-only and absent here")
    return REPORT_PATH


def test_generated_report_is_current(manifest: dict) -> None:
    report_path = _require_generated_report()
    assert report_path.read_text(encoding="utf-8") == render_report(manifest), (
        "run: python tools/report_format_decode_progress.py --write"
    )


def test_check_mode_passes() -> None:
    _require_generated_report()
    assert main([]) == 0


def test_schema_version_stays_at_one(manifest: dict) -> None:
    # Cdmw.Archive.Content rejects any other value; progress fields are additive
    # and are ignored by that reader, so the contract version does not move.
    assert manifest["schema_version"] == 1


def test_manifest_stays_one_entry_per_line() -> None:
    # ArchiveContentRegistry embeds this file; the compact layout keeps entry
    # diffs readable when a status changes.
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    entry_lines = [line for line in text.splitlines() if line.strip().startswith('{ "extension"')]
    assert len(entry_lines) == len(json.loads(text)["extensions"])


def test_proven_formats_are_not_claimed_without_evidence(entries: list[dict]) -> None:
    for entry in entries:
        if entry["decode"] == "full" and entry["origin"] == "proprietary":
            assert len(str(entry["evidence"])) > 30, (
                f"{entry['extension']} claims a full decode without pointing at where it is proven"
            )


def test_effect_capabilities_match_current_authoring_and_preview(entries: list[dict]) -> None:
    by_extension = {entry["extension"]: entry for entry in entries}

    for extension in (".pae", ".paem"):
        entry = by_extension[extension]
        assert entry["decode"] == "full"
        assert entry["write"] == "constrained"
        assert entry["visual"] is True
        assert "approximate particle preview" in entry["evidence"]
        assert "does not reproduce" in entry["remaining"]


def test_validate_rejects_an_unknown_status(entries: list[dict]) -> None:
    broken = [dict(entries[0], decode="mostly")]
    with pytest.raises(ManifestError):
        validate(broken)


def test_validate_rejects_a_silent_gap(entries: list[dict]) -> None:
    broken = [dict(entries[0], write="none", priority="high", remaining="")]
    with pytest.raises(ManifestError):
        validate(broken)


def test_decode_weights_are_ordered() -> None:
    assert DECODE_WEIGHTS["full"] > DECODE_WEIGHTS["partial"] > DECODE_WEIGHTS["surface"] > DECODE_WEIGHTS["none"]
