from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class _FunctionSpan:
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int


@dataclass(frozen=True)
class _SourceFunctionMap:
    line_starts: tuple[int, ...]
    spans: dict[str, _FunctionSpan]


@lru_cache(maxsize=8)
def _source_function_map(source: str) -> _SourceFunctionMap:
    tree = ast.parse(source)
    spans: dict[str, _FunctionSpan] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.end_lineno is None or node.end_col_offset is None:
            continue
        spans.setdefault(
            node.name,
            _FunctionSpan(
                lineno=node.lineno,
                col_offset=node.col_offset,
                end_lineno=node.end_lineno,
                end_col_offset=node.end_col_offset,
            ),
        )
    line_starts = [0]
    line_starts.extend(index + 1 for index, char in enumerate(source) if char == "\n")
    return _SourceFunctionMap(tuple(line_starts), spans)


def function_source(source: str, name: str) -> str:
    source_map = _source_function_map(source)
    try:
        span = source_map.spans[name]
    except KeyError as exc:
        raise AssertionError(f"function not found: {name}") from exc

    start_line = source_map.line_starts[span.lineno - 1]
    end_line = source_map.line_starts[span.end_lineno - 1]
    start = start_line + _byte_column_to_character_offset(
        source,
        start_line,
        span.col_offset,
    )
    end = end_line + _byte_column_to_character_offset(
        source,
        end_line,
        span.end_col_offset,
    )
    return source[start:end]


def _byte_column_to_character_offset(source: str, line_start: int, byte_column: int) -> int:
    line_end = source.find("\n", line_start)
    if line_end < 0:
        line_end = len(source)
    line = source[line_start:line_end]
    return len(line.encode("utf-8")[:byte_column].decode("utf-8"))
