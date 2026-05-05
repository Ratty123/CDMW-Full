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
        self.assertNotIn("C:\\Users\\Ratrider", source)
        self.assertNotIn("Desktop\\app", source)

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
