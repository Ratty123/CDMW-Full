from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.benchmark_app_startup import (
    FIRST_TAB_ROUTES,
    _comparison,
    _stage_probe_summaries,
    percentile,
    summarize_timings,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "benchmark_app_startup.py"
SCHEMA = ROOT / "schemas" / "startup" / "app-startup-benchmark.schema.json"


def test_first_tab_routes_use_complete_shell_navigation_keys() -> None:
    assert FIRST_TAB_ROUTES["mesh_editor_tab"] == "mesh_editor"
    assert FIRST_TAB_ROUTES["research_tab"] == "research"
    assert FIRST_TAB_ROUTES["texture_editor_tab"] == "texture_editor"


def test_percentile_and_timing_summary_are_deterministic() -> None:
    assert percentile([40, 10, 30, 20], 0.0) == 10
    assert percentile([40, 10, 30, 20], 0.5) == 25
    assert percentile([40, 10, 30, 20], 1.0) == 40
    summary = summarize_timings([3, 1, 2])
    assert summary == {
        "samples_ms": [3.0, 1.0, 2.0],
        "minimum_ms": 1.0,
        "median_ms": 2.0,
        "p95_ms": 2.9,
        "maximum_ms": 3.0,
    }


def test_stage_timing_summaries_preserve_each_probe_stage() -> None:
    summaries = _stage_probe_summaries(
        [
            {"stages_ms": {"shell_module_import": 30.0, "window_construction": 20.0}},
            {"stages_ms": {"shell_module_import": 10.0, "window_construction": 40.0}},
        ]
    )

    assert tuple(summaries) == ("shell_module_import", "window_construction")
    assert summaries["shell_module_import"]["samples_ms"] == [30.0, 10.0]
    assert summaries["shell_module_import"]["median_ms"] == 20.0
    assert summaries["window_construction"]["p95_ms"] == 39.0
    assert summaries["window_construction"]["status"] == "ok"


def test_schema_requires_cold_and_warm_startup_probe_surfaces() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == 2
    required = set(schema["properties"]["probes"]["required"])
    assert required == {
        "public_facade_import",
        "first_window",
        "first_tab",
        "warm_process",
        "helper_protocol_ready",
    }


def test_v1_false_first_tab_baseline_is_not_used_as_a_regression_gate() -> None:
    artifact = {
        "probes": {
            "public_facade_import": {"p95_ms": 40.0, "forbidden_modules_seen": []},
            "first_window": {"p95_ms": 700.0},
            "first_tab": {
                "p95_ms": 400.0,
                "created_every_run": True,
                "painted_every_run": True,
                "gui_heartbeat_max_gap": {"maximum_ms": 80.0},
            },
            "helper_protocol_ready": {"status": "skipped"},
        }
    }
    baseline = {
        "schema_version": 1,
        "generated_at_utc": "2026-07-11T00:00:00+00:00",
        "probes": {
            "first_window": {"p95_ms": 1_000.0},
            "first_tab": {"p95_ms": 5.0, "created_every_run": False},
            "helper_protocol_ready": {"status": "skipped"},
        },
    }

    comparison, gates = _comparison(artifact, baseline)

    assert gates["first_tab_regression_within_10_percent"] is None
    assert comparison["first_tab_comparison_skipped"]
    assert gates["first_tab_created_every_run"] is True
    assert gates["first_tab_painted_every_run"] is True


def test_nested_window_probe_waits_for_creation_and_first_paint(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--child-probe",
            "window",
            "--settings-path",
            str(tmp_path / "settings.ini"),
            "--first-tab",
            "texture_editor_tab",
        ],
        cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    pair = json.loads(result.stdout.splitlines()[-1])
    for temperature in ("cold_process", "warm_process"):
        payload = pair[temperature]
        assert payload["first_tab_created"] is True
        assert payload["first_tab_painted"] is True
        assert payload["first_tab_first_paint_ms"] >= payload["first_tab_ms"] > 0.0
        assert set(
            (
                "worker_preload",
                "gui_module_import",
                "widget_construction",
                "final_hookup",
                "navigation_activation",
                "queued_dispatch_wait",
                "first_visible_paint",
                "gui_heartbeat_max_gap",
            )
        ).issubset(payload["stages_ms"])


@pytest.mark.parametrize("run_count", [1])
def test_public_probe_emits_a_lightweight_import_result(run_count: int) -> None:
    result = subprocess.run(
        [sys.executable, str(TOOL), "--child-probe", "public"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert float(payload["elapsed_ms"]) < 500.0
    assert payload["forbidden_modules"] == []
    assert int(payload["module_count"]) > run_count


def test_static_replacement_prompt_stays_lazy_and_compatibility_export_is_cached() -> None:
    script = "\n".join(
        (
            "import sys",
            "import cdmw.ui.archive_browser.static_replacement_dialog as facade",
            "prompt_name = 'cdmw.ui.archive_browser.static_replacement_dialog_prompt'",
            "assert prompt_name not in sys.modules",
            "first = facade.prompt_archive_static_replacement_options",
            "assert prompt_name in sys.modules",
            "assert first is facade.prompt_archive_static_replacement_options",
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_loading_main_window_class_does_not_import_static_replacement_prompt() -> None:
    script = "\n".join(
        (
            "import os, sys",
            "os.environ['CDMW_MAIN_WINDOW_CLASS_ONLY'] = '1'",
            "import cdmw.ui.shell.app_window as app_window",
            "deferred = ('cdmw.ui.shell.app_startup', 'cdmw.ui.shell.startup_controller', "
            "'cdmw.ui.shell.startup_splash', 'cdmw.ui.shell.icon_controller')",
            "assert not [name for name in deferred if name in sys.modules]",
            "assert 'cdmw.ui.archive_browser.static_replacement_dialog_prompt' not in sys.modules",
            "assert isinstance(app_window.run_gui(), type)",
            "assert not [name for name in deferred if name in sys.modules]",
            "assert 'cdmw.ui.archive_browser.static_replacement_dialog_prompt' not in sys.modules",
            "assert 'numpy' not in sys.modules",
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_class_resolution_does_not_create_and_discard_settings() -> None:
    script = "\n".join(
        (
            "import os, tempfile",
            "from pathlib import Path",
            "os.environ['CDMW_MAIN_WINDOW_CLASS_ONLY'] = '1'",
            "import cdmw.ui.shell.app_window as app_window",
            "path = Path(tempfile.mkdtemp(prefix='cdmw-class-resolution-')) / 'settings.ini'",
            "app_window.resolve_settings_file_path = lambda: path",
            "app_window.create_settings = lambda **_kwargs: (_ for _ in ()).throw(AssertionError('discarded settings'))",
            "assert isinstance(app_window.run_gui(), type)",
        )
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
