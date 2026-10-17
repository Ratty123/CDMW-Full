from __future__ import annotations

import json
import textwrap

import pytest

from tools import report_format_decode_progress as report


def _entry(**overrides):
    return {
        "extension": ".test", "origin": "proprietary", "group": "test",
        "decode": "partial", "write": "constrained", "priority": "medium",
        "archive_files": 1, "evidence": "Synthetic report fixture.",
        "remaining": "A bounded editing limitation.", **overrides,
    }


def test_report_keeps_short_notes_escapes_cells_and_uses_a_neutral_empty_note():
    table, details = report._render_format_rows([
        _entry(remaining="First choice | second choice."),
        _entry(extension=".empty", archive_files=0, remaining=""),
    ])
    assert "First choice \\| second choice." in table
    assert "| `.empty` | 0 |" in table
    assert "No additional limits recorded here." in table
    assert "Nothing outstanding." not in table
    assert details == []


def test_long_limitation_has_one_readable_section_and_reusable_links(monkeypatch):
    monkeypatch.setattr(report, "load_inventory", lambda: {".test": 1})
    note = " ".join(["This limitation needs detailed explanation."] * 20)
    output = report.render_report({"extensions": [_entry(remaining=note, priority="high")]})
    wrapped = textwrap.fill(note, width=88, break_long_words=False, break_on_hyphens=False)
    assert output.count(wrapped) == 1
    assert output.count("[Detailed limitations](#test-limitations)") == 2
    assert output.count("### `.test` limitations") == 1
    assert output.index("### Open formats") < output.index("## Detailed format limitations")
    table_line = next(line for line in output.splitlines() if line.startswith("| `.test` |"))
    assert len(table_line) < 180


def test_open_format_gap_does_not_link_to_an_absent_engine_section(monkeypatch):
    monkeypatch.setattr(report, "load_inventory", lambda: {})
    note = "First paragraph.\n\nSecond paragraph."
    output = report.render_report({
        "extensions": [_entry(origin="open", archive_files=0, remaining=note, priority="high")],
    })
    assert "Detailed limitations](#test-limitations)" not in output
    assert note in output


@pytest.fixture
def isolated_report(monkeypatch, tmp_path):
    manifest_path = tmp_path / "capabilities.json"
    report_path = tmp_path / "report.md"
    manifest_path.write_text(json.dumps({
        "progress": {}, "extensions": [_entry()],
    }, indent=2) + "\n", encoding="utf-8")
    report_path.write_text("Stale report.\n", encoding="utf-8")
    read_manifest = report.load_manifest
    write_progress = report.write_manifest_progress
    monkeypatch.setattr(report, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(report, "REPORT_PATH", report_path)
    monkeypatch.setattr(report, "load_manifest", lambda: read_manifest(manifest_path))
    monkeypatch.setattr(report, "write_manifest_progress", lambda progress: write_progress(progress, manifest_path))
    monkeypatch.setattr(report, "load_inventory", lambda: {".test": 1})
    return manifest_path, report_path


@pytest.mark.parametrize("arguments", [[], ["--check"]])
@pytest.mark.parametrize("stale_target", ["manifest", "report"])
def test_read_only_modes_detect_drift_without_writing(isolated_report, arguments, stale_target):
    manifest_path, report_path = isolated_report
    if stale_target == "report":
        assert report.main(["--write"]) == 0
        report_path.write_text("Stale report.\n", encoding="utf-8")
    before = (manifest_path.read_bytes(), report_path.read_bytes())
    assert report.main(arguments) == 1
    assert (manifest_path.read_bytes(), report_path.read_bytes()) == before


def test_write_then_check_preserves_archive_records(isolated_report):
    manifest_path, report_path = isolated_report
    before = json.loads(manifest_path.read_text(encoding="utf-8"))["extensions"]
    assert report.main(["--write"]) == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["extensions"] == before
    assert manifest["progress"]["headline"]["all_formats"]["extensions"] == 1
    assert ".cditem" not in report_path.read_text(encoding="utf-8")
    assert report.main(["--check"]) == report.main([]) == 0


def test_cli_rejects_conflicting_modes_before_writing(isolated_report):
    paths = isolated_report
    before = tuple(path.read_bytes() for path in paths)
    with pytest.raises(SystemExit) as failure:
        report.main(["--write", "--check"])
    assert failure.value.code == 2
    assert tuple(path.read_bytes() for path in paths) == before
