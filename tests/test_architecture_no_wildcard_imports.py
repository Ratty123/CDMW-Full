from __future__ import annotations

import ast
from pathlib import Path


CHECK_ROOTS = (
    Path("cdmw/app"),
    Path("cdmw/domain"),
    Path("cdmw/services"),
    Path("cdmw/workers"),
    Path("cdmw/ui/archive_browser"),
    Path("cdmw/ui/item_icons"),
    Path("cdmw/ui/mesh_editor"),
    Path("cdmw/ui/model_library"),
    Path("cdmw/ui/research"),
    Path("cdmw/ui/text_search"),
    Path("cdmw/ui/texture_workflow"),
    Path("cdmw/ui/shell"),
)

ALLOWLIST = set()


def test_refactored_packages_do_not_use_wildcard_imports() -> None:
    for root in CHECK_ROOTS:
        for path in root.rglob("*.py"):
            if path in ALLOWLIST:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert "*" not in [alias.name for alias in node.names], path
