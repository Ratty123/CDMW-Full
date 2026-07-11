from __future__ import annotations

import ast
from pathlib import Path

from cdmw.services.mesh_workflow_exports import MESH_WORKFLOW_EXPORTS


ROOT = Path(__file__).resolve().parents[1]


def test_ui_mesh_workflow_imports_use_the_service_boundary() -> None:
    imported_names: set[str] = set()
    forbidden: list[str] = []
    for path in (ROOT / "cdmw" / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "cdmw.services.mesh_workflow_service":
                imported_names.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and str(node.module or "").startswith("cdmw.modding"):
                forbidden.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.module}")
            if isinstance(node, ast.Import):
                forbidden.extend(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{alias.name}"
                    for alias in node.names
                    if alias.name.startswith("cdmw.modding")
                )
    assert not forbidden, "UI bypasses mesh service boundary:\n" + "\n".join(forbidden)
    assert imported_names
    assert imported_names <= set(MESH_WORKFLOW_EXPORTS)


def test_mesh_workflow_service_preserves_owner_identity_and_is_lazy() -> None:
    import sys

    sys.modules.pop("cdmw.modding.mesh_native_core", None)
    from cdmw.services import mesh_workflow_service

    assert "cdmw.modding.mesh_native_core" not in sys.modules
    from cdmw.modding import mesh_native_core, mesh_parser, scene_importer, static_mesh_replacer

    assert mesh_workflow_service.ParsedMesh is mesh_parser.ParsedMesh
    assert mesh_workflow_service.SceneImportResult is scene_importer.SceneImportResult
    assert mesh_workflow_service.StaticSubmeshMapping is static_mesh_replacer.StaticSubmeshMapping
    assert mesh_workflow_service.native_mesh_core_available is mesh_native_core.native_mesh_core_available
