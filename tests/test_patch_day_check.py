"""Owned checks for `tools/patch_day_check.py`, the one-command patch-day sweep (no game needed)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tools import patch_day_check as pdc

TESTS = Path(__file__).resolve().parent


def _real_game_modules() -> set[str]:
    modules = set()
    for path in TESTS.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"pytest\.mark\.real_game|pytestmark\s*=.*real_game", text):
            modules.add("journeys" if path.parent.name == "journeys" else path.stem)
    return modules


def test_every_real_game_module_has_an_area():
    """A new `real_game` test must be given an area, or patch day reports it as UNMAPPED."""

    mapped = {key.partition("::")[0] for key in pdc.AREAS}
    missing = sorted(_real_game_modules() - mapped)
    assert not missing, f"add these to tools/patch_day_check.py AREAS: {missing}"


def test_area_prefers_the_most_specific_key():
    assert pdc.area_of("test_patch_day_format_guards::test_paver_reads_a_version_label[meta/0.paver]")[0] == \
        "Archives and indexes"
    assert pdc.area_of("test_patch_day_format_guards::test_static_table_decodes[detectinfo]")[0] == "Gameplay tables"
    assert pdc.area_of("test_iteminfo_row::VanillaItemInfoTests::test_x")[0] == "Gameplay tables"
    assert pdc.area_of("journeys/test_parity::test_x")[0].startswith("App journeys")
    assert pdc.area_of("test_something_new::test_x")[0] == "UNMAPPED"


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
<testcase classname="tests.test_a" name="test_still_ok"/>
<testcase classname="tests.test_a" name="test_known"><failure message="AssertionError: old">x</failure></testcase>
<testcase classname="tests.test_a.Cls" name="test_fixed"/>
<testcase classname="tests.test_b" name="test_broke"><failure message="ValueError: new layout">x</failure></testcase>
<testcase classname="tests.test_b" name="test_skip_ok"><skipped message="needs the native composer"/></testcase>
<testcase classname="tests.test_b" name="test_skip_new"><skipped message="file moved"/></testcase>
<testcase classname="tests.journeys.test_journeys" name="test_open"><skipped message="no profile"/></testcase>
</testsuite></testsuites>
"""


def test_junit_results_are_sorted_against_the_baseline(tmp_path, monkeypatch):
    junit = tmp_path / "r.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    results = pdc.read_junit(junit)
    assert set(results) == {"test_a::test_still_ok", "test_a::test_known", "test_a::Cls::test_fixed",
                            "test_b::test_broke", "test_b::test_skip_ok", "test_b::test_skip_new",
                            "journeys/test_journeys::test_open"}
    baseline = {
        "known_failures": {"test_a::test_known": {"entry": "P-99", "reason": "old"},
                           "test_a::Cls::test_fixed": {"entry": "P-98", "reason": "old"},
                           "test_c::test_gone": {"entry": "P-97", "reason": "old"}},
        "expected_skips": {"test_b::test_skip_ok": "native composer not built", "journeys/": "needs the app"},
    }
    monkeypatch.setattr(pdc, "AREAS", {"test_a": ("A", "P-1"), "test_b": ("B", "P-2"), "test_c": ("C", "-"),
                                       "journeys": ("J", "-")})
    rows = {row["test"]: row for row in pdc.classify(results, baseline)}
    assert rows["test_a::test_still_ok"]["verdict"] == "ok"
    assert rows["test_a::test_known"]["verdict"] == "known (P-99)"
    assert rows["test_a::Cls::test_fixed"]["verdict"].startswith("FIXED")
    assert rows["test_b::test_broke"]["verdict"] == "NEW FAILURE"
    assert rows["test_b::test_skip_ok"]["verdict"].startswith("expected skip")
    assert rows["test_b::test_skip_new"]["verdict"] == "UNEXPECTED SKIP"
    assert rows["journeys/test_journeys::test_open"]["verdict"].startswith("expected skip")
    assert rows["test_c::test_gone"]["verdict"] == "KNOWN FAILURE NO LONGER RUNS"
    new = sorted(key for key, row in rows.items() if pdc.is_new(row))
    assert new == ["test_b::test_broke", "test_b::test_skip_new", "test_c::test_gone"]
    text = pdc.render({"date": "2026-11-19", "build": {"exe": "1.0.0.1", "steam": "1", "baseline_exe": "1.0.0.0",
                                                       "baseline_steam": "0"},
                       "bootstrap": {"status": "known"}, "meta": {}, "tests": list(rows.values())})
    assert "NEW FAILURE: `test_b::test_broke`" in text and "| B | 3 | 0 | **2** | 0 | 1 | 0 |" in text


def test_inventory_diff_reports_new_removed_and_moved_extensions():
    diff = pdc.inventory_diff({".pac": 13307, ".new": 5, ".dds": 400000}, {".pac": 13300, ".old": 2, ".dds": 388451})
    assert diff == {"added": [".new"], "removed": [".old"], "moved": {".dds": [388451, 400000]}}


def test_the_bootstrap_hashes_come_from_the_virtual_loader_source():
    hashes = pdc.known_bootstrap_hashes()
    assert len(hashes) == 2 and all(len(h) == 64 for h in hashes)


def test_writing_a_baseline_keeps_known_reasons_and_adds_new_ones(tmp_path):
    previous = {"known_failures": {"t::a": {"entry": "P-31", "reason": "kept"}}, "expected_skips": {"t::s": "x"}}
    report = {"date": "d", "build": {"exe": "1.0.0.2", "steam": "2"},
              "meta": {"meta/0.paver": {"size": 28, "sha256": "ab", "changed": True}, "meta/x": {"missing": True}},
              "static_table_list": ["iteminfo"],
              "tests": [{"test": "t::a", "outcome": "failed", "message": "m"},
                        {"test": "t::b", "outcome": "error", "message": "boom"},
                        {"test": "t::s2", "outcome": "skipped", "message": "why"},
                        {"test": "t::c", "outcome": "passed", "message": ""}]}
    path = tmp_path / "baseline.json"
    pdc.write_baseline(report, previous, path)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["exe"] == "1.0.0.2" and written["static_tables"] == ["iteminfo"]
    assert written["meta"] == {"meta/0.paver": {"size": 28, "sha256": "ab"}}
    assert written["known_failures"] == {"t::a": {"entry": "P-31", "reason": "kept"},
                                         "t::b": {"entry": "unclassified", "reason": "boom"}}
    assert written["expected_skips"] == {"t::s": "x", "t::s2": "why"}


def test_the_tracked_baseline_names_a_register_entry_for_every_known_failure():
    baseline = json.loads(pdc.BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["exe"].startswith("1.0.0.")
    unnamed = [key for key, row in baseline["known_failures"].items()
               if not re.match(r"(P|S)-\d+", row.get("entry", ""))]
    assert not unnamed, unnamed
