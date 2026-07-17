from __future__ import annotations

import ast
import importlib
from pathlib import Path
import subprocess
import sys

from cdmw.modding import mesh_native_core
from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]
OWNER_PATHS = tuple(
    path
    for path in sorted((ROOT / "cdmw/modding").glob("mesh_native_*.py"))
    if path.name != "mesh_native_core.py"
)


def test_native_mesh_owners_obey_new_size_ceiling() -> None:
    for path in OWNER_PATHS:
        source = path.read_text(encoding="utf-8-sig")
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT, path
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert (node.end_lineno or node.lineno) - node.lineno + 1 <= 150, f"{path}:{node.name}"


def test_native_mesh_facade_is_materially_smaller_and_directly_reexports_owners() -> None:
    facade_path = ROOT / "cdmw/modding/mesh_native_core.py"
    assert len(facade_path.read_text(encoding="utf-8-sig").splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT

    owners = [
        (
            importlib.import_module(f"cdmw.modding.{path.stem}"),
            {
                node.name
                for node in ast.parse(path.read_text(encoding="utf-8-sig")).body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            },
        )
        for path in OWNER_PATHS
    ]
    for name in mesh_native_core.__all__:
        facade_value = getattr(mesh_native_core, name)
        if not callable(facade_value) or getattr(facade_value, "__module__", "") == mesh_native_core.__name__:
            continue
        matching = [getattr(owner, name) for owner, definitions in owners if name in definitions]
        assert any(facade_value is value for value in matching), name

    assert mesh_native_core._ensure_native_mesh_session_submesh is importlib.import_module(
        "cdmw.modding.mesh_native_session_state"
    )._ensure_native_mesh_session_submesh
    assert mesh_native_core._run_native_mesh_core_job is importlib.import_module(
        "cdmw.modding.mesh_native_dispatch"
    )._run_native_mesh_core_job


def test_native_mesh_owner_and_facade_import_order_preserves_identity() -> None:
    scripts = (
        """
import ast, importlib
from pathlib import Path
root = Path.cwd()
owners = []
for path in sorted((root / 'cdmw/modding').glob('mesh_native_*.py')):
    if path.name == 'mesh_native_core.py':
        continue
    module = importlib.import_module(f'cdmw.modding.{path.stem}')
    definitions = {node.name for node in ast.parse(path.read_text(encoding='utf-8-sig')).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    owners.append((module, definitions))
facade = importlib.import_module('cdmw.modding.mesh_native_core')
for name in facade.__all__:
    value = getattr(facade, name)
    if not callable(value) or getattr(value, '__module__', '') == facade.__name__:
        continue
    assert any(value is getattr(owner, name) for owner, definitions in owners if name in definitions), name
""",
        "import cdmw.modding.mesh_native_morph as o; import cdmw.modding.mesh_native_core as f; assert f.apply_native_morph_slider_values is o.apply_native_morph_slider_values",
        "import cdmw.modding.mesh_native_core as f; import cdmw.modding.mesh_native_uv as o; assert f.apply_native_mesh_uv_transform is o.apply_native_mesh_uv_transform",
        "import cdmw.modding.mesh_native_session_state as o; import cdmw.modding.mesh_native_core as f; assert f._native_mesh_core_session_cache is o._native_mesh_core_session_cache",
        "import cdmw.modding.mesh_native_core as f; import cdmw.modding.mesh_native_dispatch as o; assert f._run_native_mesh_core_job is o._run_native_mesh_core_job",
    )
    for script in scripts:
        subprocess.run([sys.executable, "-c", script], cwd=ROOT, check=True, timeout=30)
