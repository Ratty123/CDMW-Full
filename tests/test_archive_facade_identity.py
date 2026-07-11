from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from cdmw.core.archive_compat_exports import ARCHIVE_EXPORTS
from cdmw.core.archive_modding_compat_exports import ARCHIVE_MODDING_EXPORTS


ROOT = Path(__file__).resolve().parents[1]
SKIPPED_PARTS = {".git", ".venv", "build", "dist", "workspace", "__pycache__"}
FACADE_MAPS = {
    "cdmw.core.archive": ARCHIVE_EXPORTS,
    "cdmw.core.archive_modding": ARCHIVE_MODDING_EXPORTS,
}


def _owned_python_paths() -> tuple[Path, ...]:
    roots = (ROOT / "cdmw", ROOT / "tests", ROOT / "tools", ROOT / "scripts")
    return tuple(
        path
        for root in roots
        for path in root.rglob("*.py")
        if not SKIPPED_PARTS.intersection(path.parts)
    )


def _used_facade_symbols() -> dict[str, set[str]]:
    used = {name: set() for name in FACADE_MAPS}
    for path in _owned_python_paths():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError):
            continue
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in FACADE_MAPS:
                used[node.module].update(alias.name for alias in node.names if alias.name != "*")
            elif isinstance(node, ast.ImportFrom) and node.module == "cdmw.core":
                for alias in node.names:
                    module_name = f"cdmw.core.{alias.name}"
                    if module_name in FACADE_MAPS:
                        aliases[alias.asname or alias.name] = module_name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FACADE_MAPS:
                        aliases[alias.asname or alias.name.rsplit(".", 1)[-1]] = alias.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                module_name = aliases.get(node.value.id)
                if module_name is not None:
                    used[module_name].add(node.attr)
    return used


def _run_clean(script: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_every_repo_used_facade_symbol_has_one_explicit_focused_owner() -> None:
    used = _used_facade_symbols()
    for facade_name, symbols in used.items():
        exports = FACADE_MAPS[facade_name]
        missing = sorted(symbols - exports.keys())
        assert missing == [], f"{facade_name} missing explicit compatibility owners: {missing}"
        for symbol in symbols:
            owner, attribute = exports[symbol]
            assert owner not in FACADE_MAPS
            assert owner.startswith("cdmw.")
            assert attribute


def test_core_owners_do_not_import_compatibility_facades() -> None:
    violations: list[tuple[str, int, str]] = []
    facade_files = {"archive.py", "archive_modding.py"}
    for path in (ROOT / "cdmw" / "core").rglob("*.py"):
        if path.name in facade_files:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in FACADE_MAPS:
                violations.append((path.relative_to(ROOT).as_posix(), node.lineno, node.module))
            elif isinstance(node, ast.ImportFrom) and node.module == "cdmw.core":
                for alias in node.names:
                    module_name = f"cdmw.core.{alias.name}"
                    if module_name in FACADE_MAPS:
                        violations.append((path.relative_to(ROOT).as_posix(), node.lineno, module_name))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FACADE_MAPS:
                        violations.append((path.relative_to(ROOT).as_posix(), node.lineno, alias.name))
    assert violations == []


def test_archive_facades_preserve_identity_for_both_clean_import_orders() -> None:
    for facade_name, mapping_module, mapping_name in (
        ("cdmw.core.archive", "cdmw.core.archive_compat_exports", "ARCHIVE_EXPORTS"),
        (
            "cdmw.core.archive_modding",
            "cdmw.core.archive_modding_compat_exports",
            "ARCHIVE_MODDING_EXPORTS",
        ),
    ):
        _run_clean(
            "from importlib import import_module; "
            f"exports=getattr(import_module({mapping_module!r}), {mapping_name!r}); "
            "owners={name: import_module(module) for name,(module,_attr) in exports.items()}; "
            f"facade=import_module({facade_name!r}); "
            "assert all(getattr(facade,name) is getattr(owners[name],attr) "
            "for name,(_module,attr) in exports.items()); "
            "assert all(facade.__dict__.get(name) is getattr(owners[name],attr) "
            "for name,(_module,attr) in exports.items())"
        )
        _run_clean(
            "from importlib import import_module; "
            f"facade=import_module({facade_name!r}); "
            f"exports=getattr(import_module({mapping_module!r}), {mapping_name!r}); "
            "values={name:getattr(facade,name) for name in exports}; "
            "assert all(values[name] is getattr(import_module(module),attr) "
            "for name,(module,attr) in exports.items()); "
            "assert all(getattr(facade,name) is values[name] for name in exports)"
        )


def test_archive_facades_are_cached_lazy_and_have_no_wildcard_imports() -> None:
    for relative_path, exports in (
        ("cdmw/core/archive.py", ARCHIVE_EXPORTS),
        ("cdmw/core/archive_modding.py", ARCHIVE_MODDING_EXPORTS),
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
            for node in ast.walk(tree)
        )
        assert "globals()[name] = value" in source
        expected_public = {name for name in exports if not name.startswith("_")}
        module_name = relative_path.removesuffix(".py").replace("/", ".")
        module = __import__(module_name, fromlist=["*"])
        assert set(module.__all__) == expected_public


def test_cold_facade_import_does_not_import_implementation_owners() -> None:
    _run_clean(
        "import sys; import cdmw.core.archive; "
        "assert 'cdmw.core.archive_format' not in sys.modules; "
        "assert 'cdmw.core.archive_model_textures' not in sys.modules"
    )
    _run_clean(
        "import sys; import cdmw.core.archive_modding; "
        "assert 'cdmw.core.archive_mesh_import_preview' not in sys.modules; "
        "assert 'cdmw.core.archive_patching' not in sys.modules"
    )
