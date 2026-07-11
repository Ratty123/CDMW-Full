from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

from cdmw.services.texture_workflow_exports import TEXTURE_WORKFLOW_EXPORTS


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_UI_MODULES = frozenset(module for module, _name in TEXTURE_WORKFLOW_EXPORTS.values())


def test_ui_texture_workflow_imports_use_service_boundary() -> None:
    imported_names: set[str] = set()
    violations: list[str] = []
    for path in (ROOT / "cdmw" / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "cdmw.services.texture_workflow_service":
                    imported_names.update(alias.name for alias in node.names)
                if node.module in FORBIDDEN_UI_MODULES:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.module}")
            elif isinstance(node, ast.Import):
                violations.extend(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{alias.name}"
                    for alias in node.names
                    if alias.name in FORBIDDEN_UI_MODULES
                )
    assert not violations, "UI bypasses texture workflow service:\n" + "\n".join(violations)
    assert imported_names - {"TextureWorkflowService"}
    assert imported_names - {"TextureWorkflowService"} <= set(TEXTURE_WORKFLOW_EXPORTS)


def test_texture_workflow_service_is_lazy_and_preserves_owner_identity() -> None:
    script = """
import sys
from cdmw.services import texture_workflow_service
assert 'cdmw.core.upscale_profiles' not in sys.modules
assert 'cdmw.core.recolor_variants' not in sys.modules
from cdmw.core import upscale_profiles
assert texture_workflow_service.derive_texture_group_key is upscale_profiles.derive_texture_group_key
assert 'cdmw.core.recolor_variants' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
