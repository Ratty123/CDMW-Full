from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re


from tests.architecture_limits import DEFAULT_FUNCTION_LINE_LIMIT


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "tests" / "architecture_size_baseline.json"
FUNCTION_LINE_LIMIT = DEFAULT_FUNCTION_LINE_LIMIT
_NATIVE_SUFFIXES = frozenset({".cc", ".cpp", ".cxx", ".h", ".hpp", ".rs"})
_CONTROL_NAMES = frozenset({"catch", "do", "else", "for", "if", "lock", "switch", "using", "while"})


def _owned_python_files() -> tuple[Path, ...]:
    paths = list(ROOT.glob("*.py"))
    for owner in ("cdmw", "pyinstaller_hooks", "scripts", "tests", "tools"):
        owner_root = ROOT / owner
        if owner_root.is_dir():
            paths.extend(owner_root.rglob("*.py"))
    return tuple(
        sorted(
            path
            for path in paths
            if not {"__pycache__", "bin", "build", "dist", "obj", "target", "third_party"}.intersection(path.parts)
        )
    )


def _owned_native_files() -> tuple[Path, ...]:
    paths: list[Path] = []
    for source_root in (ROOT / "native").glob("*/src"):
        paths.extend(path for path in source_root.rglob("*") if path.suffix.lower() in _NATIVE_SUFFIXES)
    common_root = ROOT / "native" / "common"
    if common_root.is_dir():
        paths.extend(path for path in common_root.rglob("*") if path.suffix.lower() in _NATIVE_SUFFIXES)
    return tuple(sorted(paths))


def _owned_files() -> tuple[Path, ...]:
    return (*_owned_python_files(), *_owned_native_files())


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


class _PythonFunctionCollector(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.scope: list[str] = []
        self.occurrences: Counter[str] = Counter()
        self.spans: dict[str, int] = {}

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = ".".join((*self.scope, node.name))
        self.occurrences[qualname] += 1
        suffix = f"#{self.occurrences[qualname]}" if self.occurrences[qualname] > 1 else ""
        start = min((item.lineno for item in node.decorator_list), default=node.lineno)
        self.spans[f"{_relative(self.path)}::{qualname}{suffix}"] = int(node.end_lineno or node.lineno) - start + 1
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _python_function_spans(path: Path) -> dict[str, int]:
    collector = _PythonFunctionCollector(path)
    collector.visit(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)))
    return collector.spans


def _mask_comments_and_strings(source: str) -> str:
    result = list(source)
    index = 0
    state = "code"
    while index < len(source):
        pair = source[index : index + 2]
        char = source[index]
        if state == "code" and pair in {"//", "/*"}:
            state = "line_comment" if pair == "//" else "block_comment"
            result[index] = result[index + 1] = " "
            index += 2
            continue
        if state == "code" and char in {'"', "'"}:
            state = "double_quote" if char == '"' else "single_quote"
            result[index] = " "
        elif state == "line_comment" and char == "\n":
            state = "code"
        elif state == "block_comment" and pair == "*/":
            result[index] = result[index + 1] = " "
            state = "code"
            index += 2
            continue
        elif state in {"double_quote", "single_quote"}:
            result[index] = " " if char != "\n" else "\n"
            if char == "\\":
                if index + 1 < len(source):
                    result[index + 1] = " " if source[index + 1] != "\n" else "\n"
                    index += 2
                    continue
            expected = '"' if state == "double_quote" else "'"
            if char == expected:
                state = "code"
        elif state != "code":
            result[index] = " " if char != "\n" else "\n"
        index += 1
    return "".join(result)


def _block_header(masked: str, brace_index: int) -> str:
    boundary = max(masked.rfind(token, 0, brace_index) for token in (";", "{", "}"))
    return masked[boundary + 1 : brace_index].strip()


def _function_name(header: str) -> str | None:
    if ")" not in header:
        return None
    depth = 0
    open_paren = -1
    for index in range(header.rfind(")"), -1, -1):
        if header[index] == ")":
            depth += 1
        elif header[index] == "(":
            depth -= 1
            if depth == 0:
                open_paren = index
                break
    if open_paren < 0:
        return None
    before_paren = header[:open_paren]
    names = re.findall(r"[A-Za-z_~][A-Za-z0-9_~]*", before_paren)
    if not names:
        return None
    name = names[-1]
    if name in _CONTROL_NAMES or re.search(r"\b(class|enum|namespace|struct)\b", before_paren):
        return None
    return name


def _brace_function_spans(path: Path) -> dict[str, int]:
    masked = _mask_comments_and_strings(path.read_text(encoding="utf-8-sig"))
    line_at = [0] * (len(masked) + 1)
    line = 1
    for index, char in enumerate(masked):
        line_at[index] = line
        if char == "\n":
            line += 1
    line_at[len(masked)] = line

    stack: list[tuple[int, str | None, bool]] = []
    occurrences: Counter[str] = Counter()
    spans: dict[str, int] = {}
    for index, char in enumerate(masked):
        if char == "{":
            inside_function = any(item[2] for item in stack)
            name = None if inside_function else _function_name(_block_header(masked, index))
            stack.append((line_at[index], name, name is not None))
        elif char == "}" and stack:
            start, name, is_function = stack.pop()
            if not is_function or name is None:
                continue
            occurrences[name] += 1
            key = f"{_relative(path)}::{name}#{occurrences[name]}"
            spans[key] = line_at[index] - start + 1
    return spans


def _current_oversized_functions() -> dict[str, int]:
    functions: dict[str, int] = {}
    for path in _owned_files():
        spans = _python_function_spans(path) if path.suffix.lower() == ".py" else _brace_function_spans(path)
        functions.update({key: span for key, span in spans.items() if span > FUNCTION_LINE_LIMIT})
    return dict(sorted(functions.items()))


def _load_baseline() -> dict[str, object]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    for supplement_path in sorted(BASELINE_PATH.parent.glob("architecture_size_baseline_functions_*.json")):
        supplement = json.loads(supplement_path.read_text(encoding="utf-8"))
        additions = supplement.get("functions", {})
        overlap = set(baseline["functions"]).intersection(additions)
        assert not overlap, f"Duplicate function ratchets in {supplement_path.name}: {sorted(overlap)}"
        baseline["functions"].update(additions)
    return baseline


def test_size_ratchet_covers_each_owned_language_family() -> None:
    paths = {_relative(path) for path in _owned_files()}
    assert "cdmw/models.py" in paths
    assert "tests/test_architecture_size_ratchets.py" in paths
    assert "native/cdmw_mesh_core/src/main.cpp" in paths
    assert "native/cd_hkx/src/lib.rs" in paths


def test_size_ratchet_is_function_only() -> None:
    """File length is a review signal; only oversized functions are gated."""
    baseline = _load_baseline()
    assert baseline["limits"] == {"function_lines": FUNCTION_LINE_LIMIT}
    assert set(baseline) == {"functions", "limits", "schema"}


def test_baseline_updater_writes_only_function_ratchets(tmp_path: Path, monkeypatch) -> None:
    from scripts import update_architecture_size_baseline as updater

    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(updater, "ROOT", tmp_path)
    monkeypatch.setattr(
        updater,
        "_current_oversized_functions",
        lambda: {"cdmw/core/example.py::large_function": FUNCTION_LINE_LIMIT + 1},
    )

    assert updater.main() == 0
    baseline = json.loads(
        (tmp_path / "tests" / "architecture_size_baseline.json").read_text(encoding="utf-8")
    )
    assert baseline == {
        "functions": {},
        "limits": {"function_lines": FUNCTION_LINE_LIMIT},
        "schema": 1,
    }
    assert not (tmp_path / "tests" / "architecture_size_baseline_files.json").exists()
    core = json.loads(
        (tmp_path / "tests" / "architecture_size_baseline_functions_core.json").read_text(encoding="utf-8")
    )
    assert core == {"functions": {"cdmw/core/example.py::large_function": FUNCTION_LINE_LIMIT + 1}}


def test_oversized_functions_do_not_grow_beyond_their_recorded_size() -> None:
    """New oversized functions fail, and recorded ones may not grow."""
    baseline = _load_baseline()
    current = _current_oversized_functions()
    baseline_functions = baseline["functions"]
    problems: list[str] = []
    current_keys = set(current)
    baseline_keys = set(baseline_functions)
    unrecorded = sorted(current_keys - baseline_keys)
    if unrecorded:
        problems.append(f"Oversized functions absent from the baseline: {unrecorded}")
    growth = {
        key: (baseline_functions[key], current[key])
        for key in current_keys & baseline_keys
        if current[key] > baseline_functions[key]
    }
    if growth:
        problems.append(f"Oversized functions grew: {growth}")
    assert not problems, "\n".join(problems)
