from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

from cdmw.core import archive_binary_preview


ROOT = Path(__file__).resolve().parents[1]
OWNER_STEMS = (
    "archive_binary_preview_common_0",
    "archive_binary_preview_paa_0",
    "archive_binary_preview_format_0",
    "archive_binary_preview_sidecar_0",
    "archive_binary_preview_paseq_0",
    "archive_binary_preview_papr_0",
    "archive_binary_preview_groups_0",
)


def test_binary_preview_helper_facade_keeps_direct_owner_identity() -> None:
    for stem in OWNER_STEMS:
        path = ROOT / "cdmw" / "core" / f"{stem}.py"
        owner = importlib.import_module(f"cdmw.core.{stem}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert getattr(archive_binary_preview, node.name) is getattr(owner, node.name), (stem, node.name)


def test_binary_preview_helper_owners_obey_size_caps() -> None:
    facade = ROOT / "cdmw" / "core" / "archive_binary_preview.py"
    facade_source = facade.read_text(encoding="utf-8")
    facade_tree = ast.parse(facade_source)
    assert len(facade_source.splitlines()) <= 700
    assert max(
        (
            int(node.end_lineno or node.lineno) - node.lineno + 1
            for node in ast.walk(facade_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        default=0,
    ) <= 250
    paths = [ROOT / "cdmw" / "core" / f"{stem}.py" for stem in OWNER_STEMS]
    paths.append(ROOT / "cdmw" / "core" / "archive_binary_preview_compat.py")
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert len(source.splitlines()) <= 800, path
        assert max(
            (
                int(node.end_lineno or node.lineno) - node.lineno + 1
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            default=0,
        ) <= 150, path


def test_binary_preview_helper_owner_first_import_keeps_identity() -> None:
    script = (
        "import cdmw.core.archive_binary_preview_paseq_0 as owner; "
        "import cdmw.core.archive_binary_preview as facade; "
        "assert facade._paseq_timing_evidence is owner._paseq_timing_evidence"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
