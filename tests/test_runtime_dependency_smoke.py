from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


class RuntimeDependencySmokeTests(unittest.TestCase):
    def test_mesh_editor_runtime_events_are_connected_to_shell_log(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "cdmw" / "ui" / "shell" / "tool_tabs.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("tab.runtime_event_requested.connect", source)
        self.assertIn("sink(event, **dict(fields or {}))", source)

    def test_documented_runtime_dependencies_import(self) -> None:
        packages = {
            "PySide6": "PySide6",
            "cryptography": "cryptography",
            "lz4": "lz4.block",
            "Pillow": "PIL",
            "numpy": "numpy",
            "opencv-python-headless": "cv2",
        }
        missing: list[str] = []
        for package_name, import_name in packages.items():
            try:
                importlib.import_module(import_name)
            except Exception as exc:  # pragma: no cover - failure message is the test value
                missing.append(f"{package_name} ({import_name}): {type(exc).__name__}: {exc}")
        self.assertFalse(
            missing,
            "Missing runtime dependencies. Install them with: python -m pip install -r requirements.txt\n"
            + "\n".join(missing),
        )

    def test_gui_and_texture_editor_import_smoke(self) -> None:
        from cdmw.ui.main_window import MainWindow, run_gui

        self.assertTrue(callable(MainWindow))
        self.assertTrue(callable(run_gui))
        importlib.import_module("cdmw.core.texture_editor")
        importlib.import_module("cdmw.ui.texture_editor_tab")

    def test_public_gui_entry_imports_lazily(self) -> None:
        script = "\n".join(
            (
                "import importlib",
                "import sys",
                "main_window = importlib.import_module('cdmw.ui.main_window')",
                "assert callable(main_window.MainWindow)",
                "assert callable(main_window.run_gui)",
                "assert 'cdmw.ui.shell.run_gui' not in sys.modules",
                "assert 'cdmw.ui.shell.app_window' not in sys.modules",
                "shell_run_gui = importlib.import_module('cdmw.ui.shell.run_gui')",
                "assert callable(shell_run_gui.run_gui)",
                "assert 'cdmw.ui.shell.app_window' not in sys.modules",
            )
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )

        self.assertEqual(
            0,
            result.returncode,
            f"Lazy GUI import smoke failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

    def test_gui_startup_smoke_constructs_main_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "gui-startup-result.json"
            result_path.write_text('{"ok": false, "stage": "stale"}\n', encoding="utf-8")
            env = os.environ.copy()
            env["QT_QPA_PLATFORM"] = "offscreen"
            env["CDMW_GUI_STARTUP_SMOKE"] = "1"
            env["CDMW_GUI_STARTUP_SMOKE_RESULT"] = str(result_path)
            env["CDMW_SINGLE_INSTANCE_SCOPE"] = f"runtime-smoke-{os.getpid()}-{uuid.uuid4().hex}"
            env.pop("CDMW_GUI_STARTUP_SMOKE_TARGET", None)
            result = subprocess.run(
                [sys.executable, "cdmw_app.py"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=45,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"GUI startup smoke failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
            )
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertIs(True, payload.get("ok"))
        self.assertEqual("post_construction", payload.get("stage"))
        self.assertEqual("default", payload.get("target"))
        self.assertGreater(int(payload.get("pid", 0)), 0)

    def test_gui_startup_smoke_publishes_clean_heartbeat_after_qt_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "smoke.cfg"
            result_path = root / "gui-startup-result.json"
            heartbeat_path = root / "workspace" / "logs" / "app_heartbeat.json"
            script = "\n".join(
                (
                    "import json, os, sys",
                    "from pathlib import Path",
                    "os.environ['QT_QPA_PLATFORM'] = 'offscreen'",
                    "os.environ['CDMW_GUI_STARTUP_SMOKE'] = '1'",
                    f"os.environ['CDMW_GUI_STARTUP_SMOKE_RESULT'] = {str(result_path)!r}",
                    "import cdmw.ui.shell.app_window as app_window",
                    f"app_window.resolve_settings_file_path = lambda: Path({str(settings_path)!r})",
                    "exit_code = app_window.run_gui()",
                    f"heartbeat = json.loads(Path({str(heartbeat_path)!r}).read_text(encoding='utf-8'))",
                    "assert heartbeat['clean_shutdown'] is True",
                    "assert heartbeat['phase'] == 'closed'",
                    "raise SystemExit(exit_code)",
                )
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=45,
            )

        self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_gui_startup_smoke_lock_collision_is_not_success(self) -> None:
        from cdmw.app import bootstrap

        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "gui-startup-result.json"
            with (
                patch.dict(
                    os.environ,
                    {
                        "CDMW_GUI_STARTUP_SMOKE": "1",
                        "CDMW_GUI_STARTUP_SMOKE_RESULT": str(result_path),
                        "CDMW_GUI_STARTUP_SMOKE_TARGET": "",
                    },
                ),
                patch("cdmw.app.bootstrap.acquire_single_instance_guard", return_value=False),
                patch("cdmw.app.bootstrap.request_existing_instance_activation") as activate,
                patch("cdmw.app.bootstrap.update_pyinstaller_boot_splash"),
            ):
                exit_code = bootstrap.main([])
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(3, exit_code)
        self.assertIs(False, payload.get("ok"))
        self.assertEqual("single_instance_guard", payload.get("stage"))
        activate.assert_not_called()


class RuntimeDependencySourceGuardTests(unittest.TestCase):
    def test_pyinstaller_spec_uses_repo_relative_paths(self) -> None:
        source = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        self.assertIn("ROOT = Path(SPECPATH).resolve()", source)
        self.assertIn("pathex=[str(ROOT)]", source)
        self.assertIn("CDMW_PYINSTALLER_MODE", source)
        self.assertIn("CDMW_PYINSTALLER_PROFILE", source)
        self.assertNotIn("splash = Splash(", source)
        self.assertNotIn("splash.binaries", source)
        self.assertNotIn("text_pos=", source)
        self.assertNotIn("text_default=", source)
        self.assertNotIn("C:\\Users\\Ratrider", source)
        self.assertNotIn("Desktop\\app", source)

    def test_pyinstaller_spec_excludes_unused_qml_webengine_stack(self) -> None:
        source = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        hiddenimports_section = source.split("unused_qt_modules", 1)[0]

        self.assertNotIn("PySide6.QtWebEngineCore", hiddenimports_section)
        self.assertNotIn("PySide6.QtWebEngineWidgets", hiddenimports_section)
        for module_name in (
            "PySide6.QtQml",
            "PySide6.QtQuick",
            "PySide6.QtQuickWidgets",
            "PySide6.QtWebEngineCore",
            "PySide6.QtWebEngineWidgets",
        ):
            self.assertIn(f'"{module_name}"', source)
        self.assertIn("*unused_qt_modules", source)
        self.assertIn("unused_qt_runtime_payloads", source)
        for payload_name in (
            "PySide6\\Qt6Qml.dll",
            "PySide6\\Qt6Quick.dll",
            "PySide6\\Qt6VirtualKeyboard.dll",
            "PySide6\\plugins\\platforminputcontexts\\qtvirtualkeyboardplugin.dll",
            "PySide6\\plugins\\imageformats\\qpdf.dll",
        ):
            self.assertIn(payload_name.replace("\\", "\\\\"), source)

    def test_pyinstaller_spec_embeds_windows_version_metadata_without_elevation(self) -> None:
        source = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")

        self.assertIn("write_windows_version_resource", source)
        self.assertIn("pyinstaller-version-info.txt", source)
        self.assertEqual(source.count("version=str(version_info_path)"), 2)
        self.assertEqual(source.count("uac_admin=False"), 2)
        self.assertEqual(source.count("uac_uiaccess=False"), 2)

    def test_windows_builder_uses_maintained_spec(self) -> None:
        source = Path("build_pyside6_app.ps1").read_text(encoding="utf-8")
        self.assertIn("CrimsonDesertModWorkbench.spec", source)
        self.assertIn("BuildProfile", source)
        self.assertIn("CDMW_PYINSTALLER_MODE", source)
        self.assertIn("CDMW_PYINSTALLER_PROFILE", source)
        self.assertIn("$nativeBuildArgs = @{ Configuration = $Configuration }", source)
        self.assertIn('if ($BuildProfile -ne "fast")', source)
        self.assertIn("$nativeBuildArgs.Clean = $true", source)
        self.assertIn("Assert-CleanPythonSitePackages", source)
        self.assertIn("* - Copy*", source)
        self.assertNotIn('"--collect-all", "numpy"', source)
        self.assertNotIn('$pyInstallerArgs += "cdmw_app.py"', source)

        batch_source = Path("build.bat").read_text(encoding="utf-8")
        for expected in ("onefile", "onedir", "release", "fast", "debug"):
            self.assertIn(expected, batch_source)
        self.assertIn("build_gui.py", batch_source)

        gui_source = Path("build_gui.py").read_text(encoding="utf-8")
        self.assertIn("build_pyside6_app.ps1", gui_source)
        self.assertIn("PixelProgress", gui_source)
        self.assertIn("BuildSelection", gui_source)

    def test_texture_editor_missing_dependency_fallback_is_wired(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/shell/app_startup.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/shell/tool_tabs.py").read_text(encoding="utf-8")
        )
        fallback_source = Path("cdmw/ui/texture_workflow/unavailable_editor.py").read_text(encoding="utf-8")
        self.assertIn("_texture_editor_import_error", source)
        self.assertIn("UnavailableTextureEditorTab", source)
        self.assertIn('{"cv2", "numpy", "PIL"}', source)
        self.assertIn("python -m pip install -r requirements.txt", fallback_source)
        self.assertIn("CDMW_GUI_STARTUP_SMOKE", source)
        self.assertIn("if texture_editor_tab_class is None:", source)


if __name__ == "__main__":
    unittest.main()
