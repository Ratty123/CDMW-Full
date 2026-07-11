from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


CHECK_ROOTS = (
    Path("cdmw"),
    Path("tools"),
    Path("scripts"),
)

# Legacy facades preserving broad pre-restructure import surfaces. Each exact
# path/module pair is counted once; new wildcard imports require explicit review.
WILDCARD_IMPORT_GRANDFATHER = (
    ("cdmw/core/chainner.py", "cdmw.constants"),
    ("cdmw/core/chainner.py", "cdmw.core.common"),
    ("cdmw/core/chainner.py", "cdmw.models"),
    ("cdmw/core/pipeline.py", "cdmw.constants"),
    ("cdmw/core/pipeline.py", "cdmw.core.chainner"),
    ("cdmw/core/pipeline.py", "cdmw.core.common"),
    ("cdmw/core/pipeline.py", "cdmw.core.realesrgan_ncnn"),
    ("cdmw/core/pipeline.py", "cdmw.models"),
    ("cdmw/ui/archive_browser_model.py", "cdmw.ui.archive_browser.model"),
)
SKIP_DIR_NAMES = {
    ".venv",
    ".tools",
    "__pycache__",
    "build",
    "dist",
    "generated",
    "vendor",
    "vendored",
    "workspace",
}
DEFINITION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@lru_cache(maxsize=1)
def _parsed_python_files() -> tuple[tuple[Path, ast.Module], ...]:
    paths = set(Path(".").glob("*.py"))
    for root in CHECK_ROOTS:
        paths.update(
            path
            for path in root.rglob("*.py")
            if not SKIP_DIR_NAMES.intersection(path.parts)
        )
    return tuple(
        (path, ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)))
        for path in sorted(paths)
    )


def _definitions_bound_in_scope(
    statements: list[ast.stmt],
) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    definitions: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, DEFINITION_TYPES):
            definitions.append(node)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    for statement in statements:
        visit(statement)
    return definitions


def _property_accessor_group(definitions: list[ast.AST]) -> bool:
    kinds: list[str] = []
    for definition in definitions:
        if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        kind = ""
        for decorator in definition.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "property":
                kind = "property"
            elif (
                isinstance(decorator, ast.Attribute)
                and isinstance(decorator.value, ast.Name)
                and decorator.value.id == definition.name
                and decorator.attr in {"getter", "setter", "deleter"}
            ):
                kind = decorator.attr
        if not kind:
            return False
        kinds.append(kind)
    return kinds.count("property") == 1 and len(kinds) == len(set(kinds))


def _overload_group(definitions: list[ast.AST]) -> bool:
    if len(definitions) < 2 or not all(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in definitions
    ):
        return False

    def is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return any(
            (isinstance(decorator, ast.Name) and decorator.id == "overload")
            or (isinstance(decorator, ast.Attribute) and decorator.attr == "overload")
            for decorator in node.decorator_list
        )

    return all(is_overload(node) for node in definitions[:-1]) and not is_overload(definitions[-1])


def _duplicate_definition_violations(path: Path, scope: str, statements: list[ast.stmt]) -> list[str]:
    definitions = _definitions_bound_in_scope(statements)
    by_name: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]] = {}
    for definition in definitions:
        by_name.setdefault(definition.name, []).append(definition)

    violations = [
        f"{path.as_posix()}:{scope}:{name} lines {', '.join(str(node.lineno) for node in duplicates)}"
        for name, duplicates in by_name.items()
        if len(duplicates) > 1
        and not _property_accessor_group(duplicates)
        and not _overload_group(duplicates)
    ]
    for definition in definitions:
        violations.extend(
            _duplicate_definition_violations(
                path,
                f"{scope}.{definition.name}@{definition.lineno}",
                definition.body,
            )
        )
    return violations


def test_repository_python_does_not_add_wildcard_imports() -> None:
    found: list[tuple[str, str]] = []
    for path, tree in _parsed_python_files():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                found.append((path.as_posix(), node.module or ""))

    assert sorted(found) == sorted(WILDCARD_IMPORT_GRANDFATHER), (
        "Wildcard imports changed. Replace new imports with explicit names; remove stale grandfather entries.\n"
        f"expected={sorted(WILDCARD_IMPORT_GRANDFATHER)!r}\nfound={sorted(found)!r}"
    )


def test_repository_python_has_no_unintended_duplicate_definitions() -> None:
    violations = [
        violation
        for path, tree in _parsed_python_files()
        for violation in _duplicate_definition_violations(path, "<module>", tree.body)
    ]
    assert not violations, "Unintended duplicate definitions:\n" + "\n".join(violations)
