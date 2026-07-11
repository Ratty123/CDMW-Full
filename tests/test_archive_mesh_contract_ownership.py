from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_NAMES = (
    "ActiveFileAuthorityAuditResult",
    "ActiveFileAuthorityAuditRow",
    "ArchiveLooseExportResult",
    "MeshExportResult",
    "MeshImportPreviewResult",
    "MeshImportSupplementalFileSpec",
)


def test_core_archive_mesh_contracts_are_direct_domain_exports_in_both_orders() -> None:
    script = """
import importlib, sys
for name in sys.argv[1:]: importlib.import_module(name)
from cdmw.core import archive_mesh_types as core
from cdmw.domain.archives import mesh_contracts as domain
for name in %r:
    assert getattr(core, name) is getattr(domain, name), name
""" % (PUBLIC_NAMES,)
    for order in (
        ("cdmw.core.archive_mesh_types", "cdmw.domain.archives.mesh_contracts"),
        ("cdmw.domain.archives.mesh_contracts", "cdmw.core.archive_mesh_types"),
    ):
        completed = subprocess.run(
            [sys.executable, "-c", script, *order],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stderr


def test_ui_does_not_import_core_archive_mesh_contracts() -> None:
    offenders: list[str] = []
    for path in (ROOT / "cdmw" / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "cdmw.core.archive_mesh_types":
                offenders.append(path.relative_to(ROOT).as_posix())
            elif isinstance(node, ast.Import) and any(
                alias.name == "cdmw.core.archive_mesh_types" for alias in node.names
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders


def test_archive_modding_constants_are_domain_owned_and_ui_uses_domain_owner() -> None:
    from cdmw.core import archive_modding_constants as core
    from cdmw.domain.archives import constants as domain

    assert core.ARCHIVE_MESH_EXTENSIONS is domain.ARCHIVE_MESH_EXTENSIONS
    assert core.MESH_IMPORT_SIDECAR_EXTENSIONS is domain.MESH_IMPORT_SIDECAR_EXTENSIONS
    offenders: list[str] = []
    for path in (ROOT / "cdmw" / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "cdmw.core.archive_modding_constants":
                offenders.append(path.relative_to(ROOT).as_posix())
            elif isinstance(node, ast.Import) and any(
                alias.name == "cdmw.core.archive_modding_constants" for alias in node.names
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert not offenders
