"""Every module the app imports by name is one the release build packages (P9).

PyInstaller cannot see ``importlib.import_module("cdmw....")``. Those modules reach the
onefile build only through the spec's ``collect_submodules("cdmw", filter=...)``. This
test keeps the two together: each by-name literal under cdmw/ must name a module that
exists and that the spec's own filter keeps, so a typo or a module moved to the retired
list fails here instead of at first use in the packaged app.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "CrimsonDesertModWorkbench.spec"
FILTER = "_should_collect_cdmw_submodule"


def _spec_filter():
    """The spec's own filter function, run on its own (the rest of the spec is not executed)."""

    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    node = next((item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == FILTER), None)
    assert node is not None, f"{SPEC.name} no longer defines {FILTER}"
    namespace: dict = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SPEC), "exec"), namespace)  # noqa: S102
    return namespace[FILTER]


def _by_name_imports():
    found = []
    for path in sorted((ROOT / "cdmw").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)):
                continue
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
            target = node.args[0].value
            if name == "import_module" and isinstance(target, str) and target.startswith("cdmw."):
                found.append((path.relative_to(ROOT).as_posix(), node.lineno, target))
    return found


def test_the_spec_still_collects_cdmw_with_its_filter() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert f'collect_submodules("cdmw", filter={FILTER})' in text


def test_every_module_imported_by_name_exists_and_is_packaged() -> None:
    keep = _spec_filter()
    imports = _by_name_imports()
    assert imports, "no by-name cdmw imports found: the scan is broken"
    missing = [f"{where}:{line} {name}" for where, line, name in imports if importlib.util.find_spec(name) is None]
    assert not missing, "by-name imports of modules that do not exist:\n" + "\n".join(missing)
    dropped = [f"{where}:{line} {name}" for where, line, name in imports if not keep(name)]
    assert not dropped, "by-name imports of modules the release build leaves out:\n" + "\n".join(dropped)
