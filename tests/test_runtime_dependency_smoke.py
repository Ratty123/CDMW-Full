from __future__ import annotations

import importlib
import os
import subprocess
import sys
import unittest
from pathlib import Path


class RuntimeDependencySmokeTests(unittest.TestCase):
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
        from cdmw.ui.main_window import run_gui

        self.assertTrue(callable(run_gui))
        importlib.import_module("cdmw.core.texture_editor")
        importlib.import_module("cdmw.ui.texture_editor_tab")

    def test_gui_startup_smoke_constructs_main_window(self) -> None:
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["CDMW_GUI_STARTUP_SMOKE"] = "1"
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
        self.assertIn("$nativeBuildArgs = @{ Configuration = $nativeConfig }", source)
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
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("TEXTURE_EDITOR_IMPORT_ERROR", source)
        self.assertIn("UnavailableTextureEditorTab", source)
        self.assertIn('{"cv2", "numpy", "PIL"}', source)
        self.assertIn("python -m pip install -r requirements.txt", source)
        self.assertIn("CDMW_GUI_STARTUP_SMOKE", source)
        self.assertIn("if TextureEditorTab is None:", source)


if __name__ == "__main__":
    unittest.main()
