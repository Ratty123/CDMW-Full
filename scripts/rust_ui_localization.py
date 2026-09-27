"""Inventory text in the production Rust presentation modules (no dependencies).

The lexer excludes comments and test modules. Presentation modules also contain
protocol IDs: only prose/labels are inventoried, never lowercase machine keys.
Formatting fields are normalized to the same positional keys as the Qt scanner.
"""
from __future__ import annotations

import json
import re
import string
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

RUST_UI_DIRECTORY = Path("tools/rust_mesh_lab/apps/cdmw_mesh_lab/src")
RUST_UI_FILES = (
    "cdmw_ui.rs", "cdmw_hair.rs", "cdmw_rig.rs", "cdmw_cloth.rs",
    "cdmw_vertex_inspector.rs", "cdmw_islands.rs", "cdmw_emission.rs",
    "cdmw_shader_controls.rs", "viewport.rs", "camera.rs",
    "main.rs",
)


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    value: str | None = None


def tokens(source: str) -> list[Token]:
    result = []
    i = 0
    while i < len(source):
        start = i
        if source[i].isspace():
            i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
            continue
        if source.startswith("/*", i):
            i += 2
            depth = 1
            while i < len(source) and depth:
                if source.startswith("/*", i):
                    depth += 1
                    i += 2
                elif source.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        raw = re.match(r'r(\#*)"', source[i:])
        if raw:
            terminator = '"' + raw[1]
            begin = i + raw.end()
            end = source.find(terminator, begin)
            if end < 0:
                raise ValueError("Unterminated Rust raw string")
            i = end + len(terminator)
            result.append(Token(source[start:i], start, i, source[begin:end]))
            continue
        if source[i] == '"':
            i += 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                elif source[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            literal = source[start:i]
            normalized = re.sub(r"\\u\{([0-9a-fA-F_]+)\}",
                                lambda m: chr(int(m[1].replace("_", ""), 16)), literal)
            normalized = re.sub(r"\\\r?\n\s*", "", normalized)
            # Rust permits unescaped line breaks inside strings.
            normalized = normalized.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
            try:
                value = json.loads(normalized)
            except ValueError:
                value = None
            result.append(Token(literal, start, i, value))
            continue
        char = re.match(r"'(?:\\.|[^'\r\n])'", source[i:])
        if char:
            i += char.end()
        else:
            word = re.match(r"[A-Za-z_][A-Za-z_0-9]*", source[i:])
            i += word.end() if word else 1
        result.append(Token(source[start:i], start, i))
    return result


def matching(tokens_: list[Token]) -> dict[int, int]:
    pairs = {}
    stack = []
    for i, token in enumerate(tokens_):
        if token.value is not None:
            continue
        if token.text in {"(", "[", "{"}:
            stack.append(i)
        elif token.text in {")", "]", "}"}:
            if not stack:
                continue
            begin = stack.pop()
            pairs[begin] = i
    return pairs


def test_ranges(items: list[Token], pairs: dict[int, int]) -> list[tuple[int, int]]:
    ranges = []
    for i, token in enumerate(items):
        if token.text != "#" or i + 6 >= len(items):
            continue
        if [t.text for t in items[i:i+7]] != ["#", "[", "cfg", "(", "test", ")", "]"]:
            continue
        for j in range(i + 7, len(items)):
            if items[j].text == ";":
                ranges.append((i, j))
                break
            if items[j].text == "{" and j in pairs:
                ranges.append((i, pairs[j]))
                break
    return ranges


def normalized_template(value: str) -> str:
    try:
        parts = list(string.Formatter().parse(value))
    except ValueError:
        return value
    index = 0
    result = ""
    for literal, field, _spec, _conversion in parts:
        result += literal.replace("{", "{{").replace("}", "}}")
        if field is not None:
            result += "{value_" + str(index) + "}"
            index += 1
    return result


def is_presentation_text(value: str) -> bool:
    plain = re.sub(r"\{[^}]*\}", "", value).strip()
    if not re.search(r"[A-Za-z]{2}", plain):
        return False
    if re.fullmatch(r"[a-z0-9_.:/\\-]+", plain):
        return False
    if re.fullmatch(r"[A-Z0-9_]+", plain) and "_" in plain:
        return False
    if plain.startswith(("http:", "https:", "--", "#[", "../")):
        return False
    return True


def scan(root: Path) -> dict[str, list[dict[str, object]]]:
    origins = defaultdict(list)
    for filename in RUST_UI_FILES:
        relative = RUST_UI_DIRECTORY / filename
        path = root / relative
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        items = tokens(source)
        ranges = test_ranges(items, matching(items))
        for index, token in enumerate(items):
            if token.value is None or any(a <= index <= b for a, b in ranges):
                continue
            if not is_presentation_text(token.value):
                continue
            key = normalized_template(token.value)
            origins[key].append({"path": relative.as_posix(),
                                 "line": source.count("\n", 0, token.start) + 1,
                                 "sink": "rust-presentation"})
    return dict(origins)
