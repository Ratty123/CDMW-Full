from __future__ import annotations

import ast
from pathlib import Path


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_domain_does_not_import_pyside() -> None:
    for path in Path("cdmw/domain").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name.startswith("PySide6") for name in imports), path


def test_domain_does_not_import_modding_layer() -> None:
    for path in Path("cdmw/domain").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name == "cdmw.modding" or name.startswith("cdmw.modding.") for name in imports), path


def test_services_do_not_import_pyside_widgets() -> None:
    for path in Path("cdmw/services").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name.startswith("PySide6.QtWidgets") for name in imports), path


def test_workers_do_not_import_ui_packages() -> None:
    for path in Path("cdmw/workers").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name == "cdmw.ui" or name.startswith("cdmw.ui.") for name in imports), path


def test_rendering_does_not_import_ui_packages() -> None:
    for path in Path("cdmw/rendering").rglob("*.py"):
        imports = _imports_for(path)
        assert not any(name == "cdmw.ui" or name.startswith("cdmw.ui.") for name in imports), path


def test_entrypoint_does_not_import_ui_or_core_internals() -> None:
    imports = _imports_for(Path("cdmw_app.py"))
    assert imports == {"__future__", "cdmw.app.bootstrap"}
