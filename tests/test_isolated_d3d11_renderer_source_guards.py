from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class RetiredNativeRendererSourceGuardTests(unittest.TestCase):
    def test_native_renderer_project_and_python_hosts_are_absent(self) -> None:
        for relative in (
            "native/cdmw_d3d11_preview/CMakeLists.txt",
            "cdmw/rendering/native_d3d11_host.py",
            "cdmw/rendering/native_preview_screenshot.py",
            "cdmw/ui/native_d3d11_preview_host.py",
            "cdmw/ui/mesh_editor/native_preview_runtime.py",
            "tools/mesh_harness/native_protocol.py",
            "tools/mesh_harness/native_smoke.py",
            "tools/mesh_harness/real_d3d.py",
        ):
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_build_and_packaging_do_not_require_retired_renderer(self) -> None:
        native_build = _read("build_native_windows.ps1")
        app_build = _read("build_pyside6_app.ps1")
        spec = _read("CrimsonDesertModWorkbench.spec")

        self.assertNotIn("Invoke-NativeBuild `\n    -ProjectDir (Join-Path $scriptDir \"native\\cdmw_d3d11_preview\")", native_build)
        self.assertNotIn("cdmw-d3d11-preview.exe\",\n        \"native", spec)
        self.assertNotIn("native\\cdmw_d3d11_preview\\build\\$Configuration", app_build)
        self.assertIn("Retired cdmw-d3d11-preview.exe payload must not be present", spec)
        self.assertIn('ROOT.rglob("cdmw-d3d11-preview.exe")', spec)
        self.assertIn("tools\\dotnet_mesh_editor_experiment", native_build)

    def test_only_shared_dotnet_host_owns_visible_preview_processes(self) -> None:
        shared = _read("cdmw/ui/preview/dotnet_session.py")
        archive = _read("cdmw/ui/archive_browser/preview_layout.py")
        model_library = _read("cdmw/ui/model_library/panels.py")
        mesh_workspace = _read("cdmw/ui/mesh_editor/workspace_shell_builder.py")

        self.assertIn("class DotNetPreviewSessionController(QObject):", shared)
        self.assertIn("DotNetPreviewProfile.PREVIEW", archive)
        self.assertIn("DotNetPreviewProfile.PREVIEW", model_library)
        self.assertIn("DotNetPreviewProfile.AUTHORING", mesh_workspace)
        self.assertIn("profile=self.profile.value", shared)
        self.assertNotIn("WM_COPYDATA", shared)

    def test_renderer_identity_is_vortice_for_production_visual_proof(self) -> None:
        registry = _read("tools/mesh_harness/scenario_registry.py")
        capture = _read("tools/mesh_harness/visual_audit_capture.py")
        model_service = _read("cdmw/services/model_library_preview.py")

        self.assertIn('expected_renderer_backend="d3d11_vortice_shader"', registry)
        self.assertNotIn("legacy-cpp-d3d11", registry)
        self.assertIn('"backend": "d3d11_vortice_shader"', capture)
        self.assertIn('if backend != "d3d11_vortice_shader":', model_service)


if __name__ == "__main__":
    unittest.main()
