"""Read diagnostic emissions without importing application or helper code.

The inventory keeps literal messages, formatted message patterns and dynamic
handoffs separate. A forwarded exception is not assigned an invented CDMW code.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
import re


PYTHON_ROOTS = ("cdmw", "tools")
NATIVE_ROOTS = ("native", "tools/rust_mesh_lab", "tools/dotnet_archive_backend/src")
SKIP_DIRS = frozenset({
    ".git", ".work", "__pycache__", "third_party", "vendor", "target",
    "build", "bin", "obj", "tests", "test", "examples", "research",
    "mesh_harness", "headless_stress", "compact_shell_visual", "problem_report_receiver",
    "qtquick3d_viewport_spike", "node_modules",
})
EXCLUDED_FILES = frozenset({
    "cdmw/ui/shell/error_reference.py", "cdmw/ui/shell/error_reference_data.py",
    "cdmw/ui/shell/error_reference_guidance.py",
})
ERROR_WORDS = re.compile(
    r"\b(?:error|fail(?:ed|ure)?|invalid|unsupported|unavailable|missing|cannot|can't|"
    r"could not|unable|refus(?:e|ed)|reject(?:ed)?|blocked|mismatch|exceed(?:s|ed)?|"
    r"truncated|corrupt|timeout|timed out|cancel(?:led|ed)|denied|not found|"
    r"not supported|not available|not valid|must (?:be|have|match|contain)|"
    r"requires?|nothing to|no (?:usable|valid|supported|matching)|already exists)\b", re.I,
)
DIAGNOSTIC_NAME = re.compile(r"error|fail|warn|issue|blocker|unavailable|reject", re.I)
DIAGNOSTIC_FIELDS = frozenset({
    "error", "errors", "warning", "warnings", "warning_text", "warning_badge",
    "error_text", "error_message", "error_detail", "failure_reason",
    "failure_message", "failure_detail", "blocking_reason",
})
REPORT_PARTS = re.compile(r"(?:^|[._])(?:lines|parts|notes|details)$")
CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.:/{}-]*\Z")


@dataclass(frozen=True)
class Emission:
    path: str
    line: int
    kind: str
    text: str = ""
    code: str = ""
    severity: str = ""


def source_files(root: Path) -> list[Path]:
    files = {root / 'cdmw_app.py'} if (root / 'cdmw_app.py').exists() else set()
    for name in (*PYTHON_ROOTS, *NATIVE_ROOTS):
        folder = root / name
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            relative = path.relative_to(root)
            if any(part in SKIP_DIRS or part.endswith('_tests') for part in relative.parts) or not path.is_file():
                continue
            if relative.as_posix() in EXCLUDED_FILES:
                continue
            if path.suffix not in {".py", ".rs", ".cpp", ".cc", ".c", ".h", ".hpp", ".cs"}:
                continue
            if any(word in path.stem for word in ("self_test", "_proof", "_bench", "_harness")) or path.stem.endswith(('_tests', '_test')) or path.stem in {'harness', 'tests', 'test'}:
                continue
            if relative.parts[0] == "tools" and path.name.startswith(("test_", "benchmark_", "probe_")):
                continue
            files.add(path)
    # Runtime research/capture helpers can live directly under tools/. Follow
    # explicit application imports, rather than including developer harnesses.
    for path in tuple(files):
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
            for module in modules:
                if module.startswith("tools."):
                    imported = root / (module.replace(".", "/") + ".py")
                    if imported.is_file() and not any(part in SKIP_DIRS for part in imported.relative_to(root).parts) and '_harness' not in imported.stem:
                        files.add(imported)
    return sorted(files)


def expression_text(node: ast.AST | None, bindings: dict[str, ast.AST], depth: int = 0) -> str:
    """Keep literal wording and mark values supplied only when the program runs."""
    if node is None or depth > 8:
        return "{detail}"
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, (ast.Name, ast.Attribute)):
        name = ast.unparse(node)
        if name in bindings:
            return expression_text(bindings[name], bindings, depth + 1)
        return "{" + name + "}"
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(value.value) if isinstance(value, ast.Constant)
            else "{" + ast.unparse(value.value) + "}"
            for value in node.values
        )
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            return expression_text(node.left, bindings, depth + 1) + expression_text(node.right, bindings, depth + 1)
        if isinstance(node.op, ast.Mod):
            return expression_text(node.left, bindings, depth + 1)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"format", "strip", "rstrip", "lstrip"}:
            return expression_text(node.func.value, bindings, depth + 1)
        if isinstance(node.func, ast.Name) and node.func.id in {"str", "repr", "tr", "translate"} and node.args:
            return expression_text(node.args[-1], bindings, depth + 1)
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"tr", "translate"} and node.args:
            return expression_text(node.args[-1], bindings, depth + 1)
        return "{detail}"
    return "{detail}"


def _literal_part(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2}", re.sub(r"\{[^{}]*\}|%\([^)]+\)[a-z]|%[sdrf]", "", text)))


def expression_variants(node, bindings, depth=0):
    if depth > 8:
        return ['{detail}']
    if isinstance(node, (ast.Name, ast.Attribute)) and ast.unparse(node) in bindings:
        value = bindings[ast.unparse(node)]
        variants = expression_variants(value, bindings, depth + 1)
        # Appends/updates may add runtime details after a collection is created.
        # Retain that handoff as well as its statically visible messages.
        if isinstance(value, (ast.List, ast.Set)):
            variants.append("{" + ast.unparse(node) + "}")
        return variants
    if isinstance(node, ast.IfExp):
        return expression_variants(node.body, bindings, depth + 1) + expression_variants(node.orelse, bindings, depth + 1)
    if isinstance(node, ast.BoolOp):
        return [text for value in node.values for text in expression_variants(value, bindings, depth + 1)]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [text for value in node.elts for text in expression_variants(value, bindings, depth + 1)]
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {"str", "repr", "tr", "translate", "list", "tuple", "set"} and node.args:
            return expression_variants(node.args[-1], bindings, depth + 1)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in {"tr", "translate"} and node.args:
                return expression_variants(node.args[-1], bindings, depth + 1)
            if node.func.attr in {"format", "strip", "lstrip", "rstrip"}:
                return expression_variants(node.func.value, bindings, depth + 1)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        if isinstance(node.left, (ast.List, ast.Tuple, ast.Set)) or isinstance(node.right, (ast.List, ast.Tuple, ast.Set)):
            return expression_variants(node.left, bindings, depth + 1) + expression_variants(node.right, bindings, depth + 1)
        return [a + b for a in expression_variants(node.left, bindings, depth + 1) for b in expression_variants(node.right, bindings, depth + 1)]
    return [expression_text(node, bindings, depth)]


def python_emissions(path: str, source: str, external_signatures=None, external_bindings=None) -> list[Emission]:
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    module_bindings = dict(external_bindings or {})
    scopes = {}
    signatures = dict(external_signatures or {})
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signatures[node.name] = [arg.arg for arg in node.args.args if arg.arg not in {"self", "cls"}]
        elif isinstance(node, ast.ClassDef):
            fields = [entry.target.id for entry in node.body if isinstance(entry, ast.AnnAssign) and isinstance(entry.target, ast.Name)]
            if DIAGNOSTIC_FIELDS.intersection(fields) or "code" in fields and any(key in fields for key in ("message", "detail", "severity")):
                signatures[node.name] = fields
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            parent = parents.get(node)
            while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                parent = parents.get(parent)
            bindings = module_bindings if isinstance(parent, ast.Module) else scopes.setdefault(parent, {})
            for target in targets:
                if isinstance(target, (ast.Name, ast.Attribute)) and isinstance(value, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.IfExp, ast.BoolOp, ast.Name, ast.Attribute, ast.Call, ast.List, ast.Tuple, ast.Set)):
                    name = ast.unparse(target)
                    if name in bindings:
                        bindings[name] = ast.BoolOp(op=ast.Or(), values=[bindings[name], value])
                    else:
                        bindings[name] = value
    emitted = []
    seen = set()

    def context(node):
        parent = node
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent = parents.get(parent)
        return parent

    def add(node, kind, value=None, *, code="", severity="", bindings=None):
        if isinstance(value, ast.IfExp):
            add(node, kind, value.body, code=code, severity=severity, bindings=bindings)
            add(node, kind, value.orelse, code=code, severity=severity, bindings=bindings)
            return
        if isinstance(value, ast.BoolOp):
            for part in value.values:
                add(node, kind, part, code=code, severity=severity, bindings=bindings)
            return
        # A sink forwarding an exception is retained as a dynamic handoff, not
        # silently dropped and not misrepresented as a literal error message.
        for text in expression_variants(value, bindings or {}) if value is not None else ['{detail}']:
            text = " ".join(text.split())
            if not text and not code:
                continue
            if re.fullmatch(r'#[0-9a-fA-F]{3,8}', text):
                continue  # Theme colours keyed by error/warning are not diagnostics.
            key = (node.lineno, kind, text, code)
            if key not in seen:
                seen.add(key)
                emitted.append(Emission(path, node.lineno, kind, text, code, severity))

    combined_bindings = {None: module_bindings}
    for node in ast.walk(tree):
        owner = context(node)
        if owner not in combined_bindings:
            combined_bindings[owner] = {**module_bindings, **scopes.get(owner, {})}
        bindings = combined_bindings[owner]
        if isinstance(node, ast.Raise):
            exc = node.exc
            if isinstance(exc, ast.Call):
                value = exc.args[0] if exc.args else next((k.value for k in exc.keywords if k.arg in {"message", "detail"}), None)
                # Structured exceptions may take a code before the detail.
                sig = signatures.get(ast.unparse(exc.func).split(".")[-1], [])
                if "message" in sig and sig.index("message") < len(exc.args):
                    value = exc.args[sig.index("message")]
                add(node, "raise", value or exc, bindings=bindings)
            else:
                add(node, "raise", exc, bindings=bindings)
        if isinstance(node, ast.Assert):
            add(node, "assertion", node.msg, bindings=bindings)
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            short = name.split(".")[-1]
            fields = {k.arg: k.value for k in node.keywords if k.arg}
            sig = signatures.get(short, []) if isinstance(node.func, ast.Name) or name.startswith(("self._", "cls._")) else []
            fields.update(zip(sig, node.args))
            # Result containers often have neutral names (ArchivePreviewResult,
            # replace, etc.). Their explicit diagnostic fields are still sinks.
            for key in DIAGNOSTIC_FIELDS & fields.keys():
                add(node, "diagnostic_field", fields[key], bindings=bindings)
            for key in ("message", "detail", "reason", "detail_text", "preview_text"):
                if key in fields and any(ERROR_WORDS.search(text) for text in expression_variants(fields[key], bindings)):
                    add(node, "report", fields[key], bindings=bindings)
            code_node = next((fields[key] for key in ("code", "error_code", "recovery_error_code", "failure_code", "reason_code") if key in fields), None)
            if not DIAGNOSTIC_NAME.search(name) and not any(key in fields for key in ('message', 'detail', 'severity')):
                code_node = None
            if code_node is None and DIAGNOSTIC_NAME.search(name):
                code_node = fields.get("reason")
            message_node = next((fields[key] for key in ("message", "detail", "stderr", "reason", "title") if key in fields), None)
            for code in expression_variants(code_node, bindings) if code_node is not None else []:
                if CODE.fullmatch(code) and _literal_part(code):
                    add(node, "code", message_node, code=code, bindings=bindings)
            if "QMessageBox" in name and len(node.args) >= 3 and (short in {"warning", "critical"} or short in {'information', 'question'} and ERROR_WORDS.search(expression_text(node.args[2], bindings))):
                add(node, "dialog", node.args[2], severity=short, bindings=bindings)
            elif short == 'QMessageBox' and len(node.args) >= 3 and ast.unparse(node.args[0]).endswith(('.Warning', '.Critical')):
                add(node, "dialog", node.args[2], bindings=bindings)
            elif short in {"warning", "error", "critical", "exception", "fatal", "warn"} and node.args:
                add(node, "log", node.args[0], severity=short, bindings=bindings)
            elif short == "emit" and DIAGNOSTIC_NAME.search(name) and node.args:
                add(node, "signal", node.args[-1], bindings=bindings)
            elif short in {"append", "extend", "add", "update"} and DIAGNOSTIC_NAME.search(name) and node.args:
                values = node.args[0].elts if isinstance(node.args[0], (ast.List, ast.Tuple, ast.Set)) else [node.args[0]]
                for value in values:
                    if short in {'add', 'update'} and isinstance(value, ast.Constant) and isinstance(value.value, str) and not re.search(r'\s', value.value):
                        continue  # Field names in an error-highlight set are not messages.
                    add(node, "finding", value, bindings=bindings)
            elif short in {"append", "extend"} and isinstance(node.func, ast.Attribute) and REPORT_PARTS.search(ast.unparse(node.func.value)) and node.args:
                for text in expression_variants(node.args[0], bindings):
                    if ERROR_WORDS.search(text):
                        add(node, "report", ast.Constant(text))
            elif (short.endswith(("Error", "Exception", "Warning")) or short in {"fail", "_fail", "_error", "_issue", "_diagnostic", "_warn_once"}) and node.args:
                if not isinstance(parents.get(node), ast.Raise):
                    add(node, "failure", message_node or node.args[-1], bindings=bindings)
            elif DIAGNOSTIC_NAME.search(short) and message_node is not None and not short.startswith(("get", "is_", "has_", "clear", "reset")):
                add(node, "failure", message_node, bindings=bindings)
            elif short in {"setText", "setPlainText", "showMessage", "on_log", "log", "set_status", "_set_status"} and node.args:
                value = node.args[0]
                text = expression_text(value, bindings)
                if ERROR_WORDS.search(text):
                    add(node, "display", value, bindings=bindings)
            elif re.search(r'log|status|message|notification|alert|toast', short, re.I):
                for value in node.args:
                    if isinstance(value, (ast.Constant, ast.JoinedStr, ast.BinOp)) and ERROR_WORDS.search(expression_text(value, bindings)):
                        add(node, "display", value, bindings=bindings)
        if isinstance(node, ast.Dict):
            if len(node.values) > 1 and all(isinstance(value, ast.Attribute) and value.attr.isupper() for value in node.values):
                continue  # Enum alias tables map state names, not error messages.
            fields = {key.value: value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            for key in ("code", "error_code", "recovery_error_code", "failure_code", "reason_code"):
                if key in fields:
                    if key == 'code' and any(name in fields for name in ('translations', 'native_name', 'english_name', 'display_name', 'language')):
                        continue
                    for code in expression_variants(fields[key], bindings):
                        if CODE.fullmatch(code) and _literal_part(code):
                            add(node, "code", fields.get("message", fields.get("detail")), code=code, bindings=bindings)
            for key in DIAGNOSTIC_FIELDS:
                if key in fields:
                    add(node, "report", fields[key], bindings=bindings)
            for key in ("reason", "detail", "message", "notes"):
                if key in fields and ERROR_WORDS.search(expression_text(fields[key], bindings)):
                    add(node, "report", fields[key], bindings=bindings)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = ast.unparse(target)
                field = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else target.slice.value if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) else ""
                if field in DIAGNOSTIC_FIELDS:
                    add(node, "diagnostic_field", node.value, bindings=bindings)
                elif REPORT_PARTS.search(name):
                    for text in expression_variants(node.value, bindings):
                        if ERROR_WORDS.search(text):
                            add(node, "report", ast.Constant(text))
            if isinstance(node.value, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                for target in targets:
                    if DIAGNOSTIC_NAME.search(ast.unparse(target)) and ERROR_WORDS.search(expression_text(node.value, bindings)):
                        add(node, "diagnostic_text", node.value, bindings=bindings)
        if isinstance(node, ast.Return) and node.value is not None:
            values = node.value.elts if isinstance(node.value, (ast.Tuple, ast.List)) else [node.value]
            for value in values:
                if isinstance(value, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                    text = expression_text(value, bindings)
                    if ERROR_WORDS.search(text):
                        add(node, "validation", value, bindings=bindings)
    return emitted


# Tokenizing before selecting native diagnostics avoids comments, escaped quotes
# and multiline literals being mistaken for independent messages.
_TOKEN = re.compile(
    r'(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|'
    r'(?P<raw>r(?P<hash>\#{0,5})"[\s\S]*?"(?P=hash))|'
    r'(?P<string>(?:\$@|@\$|\$|@|L|u8)?"(?:\\[\s\S]|""|[^"\\])*?")|'
    r"(?P<char>'(?:\\.|[^'\\])')|"
    r'(?P<id>[A-Za-z_][A-Za-z_0-9]*)|(?P<punct>[^\s])', re.M,
)


def native_tokens(source: str):
    newlines = [match.start() for match in re.finditer("\n", source)]
    return [(match.lastgroup, match[0], match.start(), bisect_right(newlines, match.start()) + 1)
            for match in _TOKEN.finditer(source) if match.lastgroup != "comment"]


def _native_literal(token: str) -> str:
    if token.startswith("r"):
        return token[token.index('"') + 1:token.rindex('"')]
    text = token[token.index('"') + 1:-1]
    if token.startswith(("@", "$@", "@$")):
        return text.replace('""', '"')
    text = re.sub(r'\\\r?\n\s*', '', text)
    return re.sub(r'\\([\\"nrt])', lambda m: {"n": "\n", "r": "\r", "t": "\t"}.get(m[1], m[1]), text)


def native_emissions(path: str, source: str) -> list[Emission]:
    tokens = native_tokens(source)
    # Rust embeds unit tests in production source files. Exclude each complete
    # cfg(test) module using token braces, not a cut-off that loses later code.
    excluded = []
    for match in re.finditer(r'#\[cfg\(test\)\]', source):
        start = next((i for i, token in enumerate(tokens) if token[2] > match.end() and token[1] == '{'), None)
        if start is None:
            continue
        depth = 0
        for token in tokens[start:]:
            depth += token[1] == "{"
            depth -= token[1] == "}"
            if depth == 0:
                excluded.append((match.start(), token[2] + 1))
                break
    emissions = []
    seen = set()
    # C++ concatenates message fragments with computed values. Capture the
    # complete pattern at an exception constructor, not only its first phrase.
    consumed = set()
    for i, token in enumerate(tokens):
        if any(start <= token[2] < end for start, end in excluded):
            continue
        if token[0] != "id" or not (token[1] in {"runtime_error", "invalid_argument", "out_of_range", "logic_error", "length_error"} or token[1].endswith(('Error', 'Failure', 'Exception')) or any(t[1] == 'throw' for t in tokens[max(0, i - 5):i])):
            continue
        if i + 1 >= len(tokens) or tokens[i + 1][1] != "(":
            continue
        argument_start = tokens[i + 2:i + 7]
        if not argument_start or (argument_start[0][0] not in {'string', 'raw'} and
                                  not re.match(r'(?:std|fmt) : : (?:string|format) \(', ' '.join(t[1] for t in argument_start))):
            # Structured exceptions can take paths/status objects before their
            # message. A string nested in such an argument is not the message.
            continue
        depth = 0
        end = i + 1
        for end in range(i + 1, len(tokens)):
            depth += tokens[end][1] == "("
            depth -= tokens[end][1] == ")"
            if depth == 0:
                break
        strings = [index for index in range(i + 2, end) if tokens[index][0] in {"string", "raw"}]
        if not strings:
            continue
        pieces = []
        previous = i + 1
        for index in strings:
            between = tokens[previous + 1:index]
            if pieces and any(part[0] == "id" for part in between):
                pieces.append("{detail}")
            pieces.append(_native_literal(tokens[index][1]))
            previous = index
        if any(part[0] == "id" for part in tokens[previous + 1:end]):
            pieces.append("{detail}")
        emissions.append(Emission(path, token[3], "native_message", " ".join(''.join(pieces).split())))
        consumed.update(strings)
    for i, (kind, token, offset, line) in enumerate(tokens):
        if any(start <= offset < end for start, end in excluded):
            continue
        if kind == "id" and token in {"throw", "Err", "bail", "panic"}:
            emissions.append(Emission(path, line, "native_handoff", "{native error detail}"))
        if kind not in {"string", "raw"}:
            continue
        if i in consumed:
            continue
        text = _native_literal(token)
        before = " ".join(t[1] for t in tokens[max(0, i - 18):i]).rsplit(';', 1)[-1]
        # Include native exception attributes, constructors and explicit failure
        # returns, including messages split across adjacent C++ string literals.
        explicit = re.search(r'\b(?:throw|Err|bail|panic|eprintln|runtime_error|invalid_argument|out_of_range|logic_error|ensure|fail|Failure|InvalidManifest|InvalidPayload|Protocol|error|warning|warn|set_error|write_error)\b', before, re.I)
        diagnostic = explicit or (len(text) < 1200 and ERROR_WORDS.search(text))
        if not diagnostic or not text.strip() or not re.search('[A-Za-z]', text):
            continue
        # Exclude ordinary JSON keys/flags and short selectors picked up from
        # nearby error-handling statements. Named enums are collected below.
        if len(text) < 4 or not re.search(r'\s', text):
            continue
        if text.lstrip().startswith(('{"', '{{"', '\\"', '"', ',"', '<', 'Usage:', '--')) or text.count('":"') > 1:
            continue
        if text in {"error", "warning", "failed", "failure", "missing", "blocked", "rejected", "invalid", "unsupported", "unavailable"}:
            continue
        key = (line, text)
        if key not in seen:
            seen.add(key)
            emissions.append(Emission(path, line, "native_message", " ".join(text.split())))
    for match in re.finditer(r'\b(CDMW_[A-Z_]*(?:ERROR|INVALID|UNSUPPORTED|MISMATCH|BUSY|REJECTED|NOT_FOUND|EXISTS|TOO_SMALL)[A-Z_]*)\s*=\s*(\d+)', source):
        emissions.append(Emission(path, source.count("\n", 0, match.start()) + 1, "native_status", f"{match[1]} = {match[2]}", match[1]))
    # thiserror's display strings are the public Rust error wording. The enum
    # variant is a native error kind and remains distinct from a CDMW code.
    if path.endswith('.rs'):
        enum_name = ""
        for index, token in enumerate(tokens):
            if token[1] == 'enum' and index + 1 < len(tokens):
                enum_name = tokens[index + 1][1]
            if token[1] != 'error' or not enum_name.endswith('Error') or index < 2 or tokens[index - 2][1] != '#':
                continue
            message = next((t for t in tokens[index + 1:index + 5] if t[0] in {'string', 'raw'}), None)
            close = next((j for j in range(index + 1, min(index + 12, len(tokens))) if tokens[j][1] == ']'), None)
            if close is not None and close + 1 < len(tokens):
                variant = tokens[close + 1][1]
                emissions.append(Emission(path, token[3], 'native_kind', _native_literal(message[1]) if message else '{upstream error}', enum_name + '::' + variant))
        # Handwritten Display implementations do not use thiserror attributes.
        for match in re.finditer(r'impl\s+(?:[\w:]+::)?Display\s+for\s+(\w+Error)\s*\{', source):
            start = next(i for i, token in enumerate(tokens) if token[2] >= match.end() - 1)
            depth = 0
            end = start
            for end in range(start, len(tokens)):
                depth += tokens[end][1] == '{'
                depth -= tokens[end][1] == '}'
                if depth == 0:
                    break
            body = tokens[start:end]
            for i in range(len(body) - 5):
                if body[i][1] != 'Self' or body[i + 1][1] != ':' or body[i + 2][1] != ':':
                    continue
                message = next((t for t in body[i + 4:i + 18] if t[0] in {'string', 'raw'}), None)
                if message:
                    emissions.append(Emission(path, body[i][3], 'native_kind', _native_literal(message[1]), match[1] + '::' + body[i + 3][1]))
    # Native structured file-error kinds are machine-readable identifiers even
    # though they have no natural-language sentence in the native producer.
    if 'file_error' in source:
        for match in re.finditer(r'\bkind\s*=\s*"([a-z][a-z_]+)"', source):
            emissions.append(Emission(path, source.count('\n', 0, match.start()) + 1, 'native_kind', '', match[1]))
    if path.endswith('.cs'):
        for match in re.finditer(r'WorkerProtocol\.Failure\(\s*\w+\s*,\s*"([a-z_]+)"\s*,\s*\$?"([^"\n]*)"', source):
            emissions.append(Emission(path, source.count('\n', 0, match.start()) + 1, 'native_kind', match[2], match[1]))
    excluded_lines = [(source.count('\n', 0, start) + 1, source.count('\n', 0, end) + 1) for start, end in excluded]
    return [item for item in emissions if not any(start <= item.line <= end for start, end in excluded_lines)]


def scan_sources(root: Path) -> tuple[list[Emission], dict[str, dict[str, int]]]:
    emissions = []
    coverage = {}
    files = source_files(root)
    sources = {file: file.read_text(encoding="utf-8-sig") for file in files}
    signatures = {}
    constant_values = defaultdict(list)
    for file, source in sources.items():
        if file.suffix != ".py":
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef):
                fields = [n.target.id for n in node.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
                if DIAGNOSTIC_FIELDS.intersection(fields) or "code" in fields and any(key in fields for key in ("message", "detail", "severity")):
                    signatures[node.name] = fields
                for member in node.body:
                    if isinstance(member, ast.Assign) and isinstance(member.value, ast.Constant) and isinstance(member.value.value, str):
                        for target in member.targets:
                            if isinstance(target, ast.Name):
                                constant_values[node.name + '.' + target.id].append(member.value)
                                constant_values[node.name + '.' + target.id + '.value'].append(member.value)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        constant_values[target.id].append(node.value)
    constants = {key: values[0] for key, values in constant_values.items() if len({value.value for value in values}) == 1}
    for file in files:
        path = file.relative_to(root).as_posix()
        source = sources[file]
        found = python_emissions(path, source, signatures, constants) if file.suffix == ".py" else native_emissions(path, source)
        kinds = defaultdict(int)
        for item in found:
            kinds[item.kind] += 1
        coverage[path] = dict(sorted(kinds.items()))
        emissions.extend(found)
    return emissions, coverage
