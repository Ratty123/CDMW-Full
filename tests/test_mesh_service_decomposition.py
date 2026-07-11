from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

import cdmw.services.mesh_service as facade
from cdmw.services import mesh_service_history, mesh_service_kernel, mesh_service_payloads, mesh_service_reports
from cdmw.services.mesh_service_rebuild import MeshRebuildServiceMixin
from cdmw.services.mesh_service_rigging import MeshRiggingServiceMixin


ROOT = Path(__file__).resolve().parents[1]
OWNER_PATHS = (
    ROOT / "cdmw/services/mesh_service_state.py",
    ROOT / "cdmw/services/mesh_service_payloads.py",
    ROOT / "cdmw/services/mesh_service_reports.py",
    ROOT / "cdmw/services/mesh_service_history.py",
    ROOT / "cdmw/services/mesh_service_kernel.py",
    ROOT / "cdmw/services/mesh_service_rigging.py",
    ROOT / "cdmw/services/mesh_service_rebuild.py",
)


class MeshServiceDecompositionTests(unittest.TestCase):
    def test_facade_reexports_original_owner_objects(self) -> None:
        self.assertIs(facade._native_editor_edit_payload, mesh_service_payloads._native_editor_edit_payload)
        self.assertIs(
            facade._native_editor_report_changed_vertices,
            mesh_service_reports._native_editor_report_changed_vertices,
        )
        self.assertIs(facade._history_metrics, mesh_service_history._history_metrics)
        self.assertIs(facade._command_may_change_topology, mesh_service_kernel._command_may_change_topology)
        self.assertIs(facade.MeshService.skeleton_summary, MeshRiggingServiceMixin.skeleton_summary)
        self.assertIs(facade.MeshService.rebuild_asset, MeshRebuildServiceMixin.rebuild_asset)
        self.assertIs(facade.MeshService.undo, mesh_service_history.MeshHistoryServiceMixin.undo)

    def test_new_owners_and_service_class_obey_size_ceiling(self) -> None:
        for path in OWNER_PATHS:
            source = path.read_text(encoding="utf-8-sig")
            self.assertLessEqual(len(source.splitlines()), 800, path)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertLessEqual((node.end_lineno or node.lineno) - node.lineno + 1, 150, f"{path}:{node.name}")
        facade_source = (ROOT / "cdmw/services/mesh_service.py").read_text(encoding="utf-8-sig")
        facade_tree = ast.parse(facade_source)
        service = next(node for node in facade_tree.body if isinstance(node, ast.ClassDef) and node.name == "MeshService")
        self.assertLessEqual((service.end_lineno or service.lineno) - service.lineno + 1, 800)
        self.assertLess(len(facade_source.splitlines()), 2_600)

    def test_owner_first_and_facade_first_imports_keep_identity(self) -> None:
        scripts = (
            "import cdmw.services.mesh_service_payloads as o; import cdmw.services.mesh_service as f; assert f._native_editor_edit_payload is o._native_editor_edit_payload",
            "import cdmw.services.mesh_service as f; import cdmw.services.mesh_service_payloads as o; assert f._native_editor_edit_payload is o._native_editor_edit_payload",
        )
        for script in scripts:
            subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
