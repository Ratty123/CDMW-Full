"""Graduation guards for Placement Studio (Phase 6).

These check the wiring that only breaks somewhere expensive: a tab that is registered but has
no factory, a module tree that imports from source but not from a frozen build, and a tab that
raises into the shell when the game path is unset.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class PackagingGuardTests(unittest.TestCase):
    """`tools/` is a package but is not covered by the `cdmw` submodule sweep."""

    def test_spec_collects_the_studio_package(self) -> None:
        spec = (REPO_ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        self.assertIn('collect_submodules("tools.placement_studio")', spec)

    def test_every_studio_module_is_reachable_as_a_package(self) -> None:
        # If this drifts, the tab imports fine from source and fails only when frozen.
        package = REPO_ROOT / "tools" / "placement_studio"
        self.assertTrue((REPO_ROOT / "tools" / "__init__.py").is_file())
        self.assertTrue((package / "__init__.py").is_file())
        modules = {path.stem for path in package.glob("*.py")}
        for required in ("tab", "window", "session", "editing", "packaging", "meshes"):
            self.assertIn(required, modules)


class ShellRegistrationTests(unittest.TestCase):
    """A tab registered without a factory raises at startup, which is unmissable but late."""

    def setUp(self) -> None:
        self.source = (REPO_ROOT / "cdmw" / "ui" / "shell" / "tool_tabs.py").read_text(
            encoding="utf-8"
        )

    def test_factory_exists(self) -> None:
        self.assertIn("def _create_placement_studio_tab", self.source)

    def test_tab_is_added_lazily(self) -> None:
        # Eager construction would run an archive sweep during startup.
        self.assertIn('"placement_studio",', self.source)
        self.assertIn("_add_lazy_shell_tool", self.source)

    def test_tab_is_detachable_like_every_other_tool(self) -> None:
        self.assertIn(
            '_register_detachable_tool("placement_studio"', self.source
        )

    def test_generated_provider_manifest_is_in_sync(self) -> None:
        """Mixin members are bound from a generated manifest, so it must be regenerated."""

        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/generate_window_feature_provider_members.py", "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=600,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"Regenerate with scripts/generate_window_feature_provider_members.py\n"
            f"{result.stdout.decode(errors='replace')}{result.stderr.decode(errors='replace')}",
        )


class BootstrapTests(unittest.TestCase):
    def test_default_paths_are_plausible_game_paths(self) -> None:
        from tools.placement_studio.tab import _DEFAULT_STUDIO_PATHS

        self.assertTrue(_DEFAULT_STUDIO_PATHS)
        for path in _DEFAULT_STUDIO_PATHS:
            self.assertFalse(path.startswith("/"), path)
            self.assertEqual(path, path.lower(), path)
            self.assertTrue(
                path.startswith(("character/", "actionchart/", "gamedata/")), path
            )

    def test_default_paths_cover_what_the_studio_reads(self) -> None:
        from tools.placement_studio.tab import _DEFAULT_STUDIO_PATHS

        joined = " ".join(_DEFAULT_STUDIO_PATHS)
        self.assertIn(".pab.sockets.xml", joined)   # body sockets
        self.assertIn("characterdescription", joined)  # routing
        self.assertIn(".paac", joined)              # action charts
        self.assertIn("/weapon/", joined)           # child sockets

    def test_tab_exposes_a_shutdown_hook(self) -> None:
        from tools.placement_studio.tab import PlacementStudioTab

        self.assertTrue(callable(getattr(PlacementStudioTab, "shutdown", None)))
        self.assertTrue(callable(getattr(PlacementStudioTab, "closeEvent", None)))

    def test_worker_reports_failure_rather_than_raising(self) -> None:
        """A bad game root must surface as a message, never as an exception in the shell."""

        from tools.placement_studio.tab import BaselineWorker

        worker = BaselineWorker("Z:/definitely/not/a/game")
        captured: list = []
        worker.done.connect(lambda baseline, error: captured.append((baseline, error)))
        worker.run()

        self.assertEqual(len(captured), 1)
        baseline, error = captured[0]
        self.assertIsNone(baseline)
        self.assertTrue(error)


class IsolationTests(unittest.TestCase):
    """The studio must not import app UI code; only `cdmw.core`-level helpers."""

    def test_no_cdmw_ui_imports(self) -> None:
        # Parse imports rather than grepping text: prose may legitimately mention `cdmw.ui`
        # while the module does not import it, and the earlier grep flagged a docstring.
        import ast

        package = REPO_ROOT / "tools" / "placement_studio"
        offenders: list = []
        for path in sorted(package.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("cdmw.ui"):
                    offenders.append(f"{path.name}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    offenders.extend(
                        f"{path.name}:{node.lineno}"
                        for alias in node.names
                        if alias.name.startswith("cdmw.ui")
                    )
        self.assertEqual(offenders, [])

    def test_only_core_level_app_modules_are_used(self) -> None:
        """Record which app modules the studio depends on, so new coupling is deliberate."""

        import ast

        package = REPO_ROOT / "tools" / "placement_studio"
        used: set = set()
        for path in sorted(package.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                elif isinstance(node, ast.Import):
                    module = next((a.name for a in node.names if a.name.startswith("cdmw")), "")
                if module.startswith("cdmw"):
                    used.add(module)
        self.assertEqual(
            used,
            {
                "cdmw.core.archive_extraction",
                "cdmw.core.archive_format",
                "cdmw.core.mod_package",
                # Rig-behaviour formats the Studio reads and writes. Core-level and
                # UI-free, so they keep the isolation this guard exists to protect.
                "cdmw.core.papr_format",
                "cdmw.core.posemodifier_xml",
                "cdmw.domain.packages.export_policy",
                "cdmw.models",
                "cdmw.modding.mesh_parser",
                "cdmw.modding.skeleton_parser",
            },
        )


if __name__ == "__main__":
    unittest.main()
