from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_SOURCES = tuple(sorted((ROOT / "cdmw").rglob("*.py")))
MUTABLE_DEFAULT_NODES = (ast.Dict, ast.List, ast.Set)


def _mutable_default_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
            continue
        callable_name = getattr(node, "name", "<lambda>")
        positional = (*node.args.posonlyargs, *node.args.args)
        positional_defaults = zip(positional[-len(node.args.defaults) :], node.args.defaults)
        keyword_defaults = zip(node.args.kwonlyargs, node.args.kw_defaults)
        for argument, default in (*positional_defaults, *keyword_defaults):
            if isinstance(default, MUTABLE_DEFAULT_NODES):
                violations.append(
                    f"{path.relative_to(ROOT)}:{default.lineno}:{callable_name}:{argument.arg}"
                )
    return violations


def test_python_sources_have_no_mutable_literal_defaults() -> None:
    violations = [violation for path in PYTHON_SOURCES for violation in _mutable_default_violations(path)]

    assert violations == []


def test_python_source_bytes_are_utf8_without_bom_markers() -> None:
    violations = [
        path.relative_to(ROOT).as_posix()
        for path in PYTHON_SOURCES
        if b"\xef\xbb\xbf" in path.read_bytes()
    ]

    assert violations == []
