from __future__ import annotations

import argparse
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

from tools import headless_feature_stress as stress


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "profile": "quick",
        "output": Path("unused"),
        "game_root": None,
        "model_root": Path("Z:/missing-model-root"),
        "soak_minutes": stress.SOAK_MINUTES_DEFAULT,
        "max_model_files": None,
        "audit_zip_contents": False,
        "max_zip_audits": None,
        "cache_runs": None,
        "cache_only": False,
        "cache_real_root": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class HeadlessFeatureStressTests(unittest.TestCase):
    def test_command_construction_uses_argv_lists_and_preserves_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = stress.prepare_output_root(Path(temp_dir) / "out dir")
            model_root = Path(temp_dir) / "Model Root With Spaces"
            model_root.mkdir()

            tasks = stress.build_profile_tasks(
                _args(profile="corpus", model_root=model_root, max_model_files=7),
                output_root,
            )

        audit = next(task for task in tasks if task.name == "external-model-audit")
        self.assertIn("native-helper-preflight", [task.name for task in tasks])
        self.assertIsInstance(audit.argv, list)
        self.assertIn(str(model_root), audit.argv)
        self.assertEqual(audit.argv[audit.argv.index("--root") + 1], str(model_root))
        self.assertIn("7", audit.argv)
        self.assertIn("--audit-zip-contents", audit.argv)

    def test_safe_child_dir_rejects_paths_outside_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = stress.prepare_output_root(Path(temp_dir) / "out")

            child = stress.safe_child_dir(output_root, "children", "ok")

            self.assertTrue(child.is_dir())
            with self.assertRaises(ValueError):
                stress.safe_child_dir(output_root, "..", "escape")

    def test_report_merging_preserves_counts_reasons_and_timings(self) -> None:
        started = stress.time.perf_counter()
        report = stress.merge_report(
            profile="quick",
            argv=["--profile", "quick"],
            output_root=Path("out"),
            args=_args(),
            task_results=[
                {"name": "ok", "status": "passed", "required": True, "elapsed_s": 1.2},
                {"name": "skip", "status": "skipped", "required": False, "skip_reason": "missing root"},
                {"name": "fail", "status": "failed", "required": True, "elapsed_s": 0.4},
            ],
            started=started,
        )

        self.assertFalse(report["ok"])
        self.assertEqual({"passed": 1, "failed": 1, "skipped": 1}, report["counts"])
        self.assertEqual("missing root", report["skip_reasons"][0]["reason"])
        self.assertEqual(0.4, report["timings"]["task_elapsed_s"]["fail"])

    def test_missing_roots_become_profile_skips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = stress.prepare_output_root(Path(temp_dir) / "out")
            tasks = stress.build_profile_tasks(
                _args(profile="corpus", game_root=None, model_root=Path(temp_dir) / "missing"),
                output_root,
            )

        skipped = {task.name: task.skip_reason for task in tasks if task.skip_reason}
        self.assertIn("external-model-audit", skipped)
        self.assertIn("mesh-real-archive-rigging-smoke", skipped)
        self.assertIn("Model root not found", skipped["external-model-audit"])
        self.assertIn("Game root not found", skipped["mesh-real-archive-rigging-smoke"])

    def test_import_does_not_start_full_app_or_main_window(self) -> None:
        before = set(sys.modules)

        importlib.reload(stress)

        imported = set(sys.modules) - before
        self.assertNotIn("cdmw_app", imported)
        self.assertNotIn("cdmw.ui.main_window", imported)
        source = Path("tools/headless_feature_stress.py").read_text(encoding="utf-8")
        self.assertNotIn("cdmw_app", source)
        self.assertNotIn("cdmw.ui.main_window", source)

    def test_profile_selection_keeps_soak_opt_in_and_long(self) -> None:
        quick = stress.parse_args(["--output", "out"])
        soak = stress.parse_args(["--profile", "soak", "--output", "out", "--soak-minutes", "120"])
        cache = stress.parse_args(["--output", "out", "--cache-only", "--cache-runs", "10"])

        self.assertEqual("quick", quick.profile)
        self.assertEqual("soak", soak.profile)
        self.assertTrue(cache.cache_only)
        self.assertEqual(10, cache.cache_runs)
        with self.assertRaises(SystemExit):
            stress.parse_args(["--profile", "soak", "--output", "out", "--soak-minutes", "60"])
        with self.assertRaises(SystemExit):
            stress.parse_args(["--output", "out", "--cache-runs", "0"])

    def test_cache_only_builds_only_cache_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = stress.prepare_output_root(Path(temp_dir) / "out")
            tasks = stress.build_profile_tasks(_args(cache_only=True, cache_runs=10), output_root)

        self.assertEqual(["cache-probe"], [task.name for task in tasks])
        self.assertEqual(10, tasks[0].cache_cycles)

    def test_cache_only_can_target_real_readonly_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = stress.prepare_output_root(Path(temp_dir) / "out")
            real_root = Path(temp_dir) / "game"
            tasks = stress.build_profile_tasks(_args(cache_only=True, cache_runs=3, cache_real_root=real_root), output_root)

        self.assertEqual(["cache-probe"], [task.name for task in tasks])
        self.assertEqual(3, tasks[0].cache_cycles)
        self.assertEqual(real_root, tasks[0].cache_real_root)

    def test_cache_probe_covers_delete_rebuild_cold_warm_without_real_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "cache probe"

            result = stress.run_cache_probe(output_dir, cycles=1)

            self.assertEqual("passed", result["status"])
            cycle = result["cycles"][0]
            self.assertIn(cycle["cold"]["source"], {"cache+scan", "cache+native_scan"})
            self.assertEqual("cache", cycle["warm"]["source"])
            self.assertEqual("cache", cycle["fresh_process_warm"]["source"])
            self.assertIn(cycle["stale"]["source"], {"cache+scan", "cache+native_scan"})
            self.assertEqual(["0001/0.pamt"], cycle["stale"]["scan_calls"])
            self.assertGreater(cycle["delete"]["deleted_count"], 0)
            self.assertTrue(cycle["delete"]["within_output"])
            self.assertIn(cycle["rebuild"]["source"], {"cache+scan", "cache+native_scan"})
            self.assertIn(cycle["corrupt_recovery"]["source"], {"cache+scan", "cache+native_scan"})
            self.assertEqual(cycle["rebuild"]["entries"], cycle["corrupt_recovery"]["entries"])
            self.assertEqual("healthy", cycle["final_health"]["status"])
            self.assertIn("summary", result)
            self.assertEqual(1, result["summary"]["runs"])
            self.assertGreaterEqual(result["summary"]["cache_size_bytes"], 1)
            for path in output_dir.rglob("*"):
                self.assertTrue(path.resolve().is_relative_to(output_dir.resolve()))

    def test_native_helper_preflight_passes_when_helpers_exist_without_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            helper = root / "native" / "tool.exe"
            helper.parent.mkdir(parents=True)
            helper.write_bytes(b"exe")

            result = stress.run_native_helper_preflight(root / "out", helpers=[helper])

        self.assertEqual("passed", result["status"])
        self.assertFalse(result["build_ran"])
        self.assertEqual([], result["missing_after"])


if __name__ == "__main__":
    unittest.main()
