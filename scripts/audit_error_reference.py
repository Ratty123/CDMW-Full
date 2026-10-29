"""Independent emission-site check for the generated diagnostic reference.

This intentionally does not import the collector or its expression/token parser.
It checks source literals at language-level failure sinks against the published
data, and checks dynamic sinks against the explicitly documented handoff owners.
It is a second coverage check, not a claim to enumerate external runtime text.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def literal_fragments(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        for value in node.values:
            if isinstance(value, ast.Constant):
                yield str(value.value)
    elif isinstance(node, ast.BinOp):
        yield from literal_fragments(node.left)
        if isinstance(node.op, ast.Add):
            yield from literal_fragments(node.right)
    elif isinstance(node, ast.IfExp):
        yield from literal_fragments(node.body)
        yield from literal_fragments(node.orelse)
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
        yield from literal_fragments(node.func.value)


def audit(root=ROOT):
    from cdmw.ui.shell.error_reference_data import ERROR_REFERENCE, MESSAGE_REFERENCE, DYNAMIC_REFERENCE, SOURCE_COVERAGE
    text_by_path = defaultdict(list)
    for row in ERROR_REFERENCE:
        for path in row['sources']:
            text_by_path[path].extend([row['code'], *row['messages']])
    for row in MESSAGE_REFERENCE:
        for path in row['sources']:
            text_by_path[path].append(row['message'])
    indexed = {path: '\n'.join(texts) for path, texts in text_by_path.items()}
    dynamic = {path for paths in DYNAMIC_REFERENCE.values() for path in paths}
    missing = []
    counts = defaultdict(int)

    def check(path, line, parts, kind):
        parts = [' '.join(part.split()) for part in parts if re.search(r'[A-Za-z]{2}', part)]
        counts[kind] += 1
        if not parts:
            if path not in dynamic:
                missing.append((path, line, kind, '<dynamic handoff>'))
        else:
            for part in parts:
                if part not in indexed.get(path, ''):
                    missing.append((path, line, kind, part))

    for path in SOURCE_COVERAGE:
        source = (root / path).read_text(encoding='utf-8-sig')
        if path.endswith('.py'):
            tree = ast.parse(source)
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            def scope(node):
                while node in parents:
                    node = parents[node]
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        return node
                return tree
            # Independently resolve the simple local aliases used by raises.
            aliases = defaultdict(list)
            for assignment in ast.walk(tree):
                if isinstance(assignment, ast.Assign):
                    for target in assignment.targets:
                        if isinstance(target, ast.Name):
                            aliases[(scope(assignment), target.id)].extend(literal_fragments(assignment.value))
            for node in ast.walk(tree):
                value = None
                kind = ''
                if isinstance(node, ast.Raise):
                    kind = 'Python raise'
                    value = node.exc.args[0] if isinstance(node.exc, ast.Call) and node.exc.args else node.exc
                elif isinstance(node, ast.Assert):
                    kind, value = 'Python assertion', node.msg
                elif isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    if name.endswith(('.warning', '.critical')) and 'QMessageBox' in name and len(node.args) >= 3:
                        kind, value = 'Qt warning/critical dialog', node.args[2]
                    elif name.endswith(('.error', '.exception', '.fatal')) and node.args:
                        kind, value = 'Python error log', node.args[0]
                if kind:
                    fragments = aliases[(scope(node), value.id)] or aliases[(tree, value.id)] if isinstance(value, ast.Name) else literal_fragments(value)
                    check(path, node.lineno, fragments, kind)
        else:
            # Deliberately separate regex recognizer for direct native throws,
            # Rust error attributes/macros and C# exception messages. Ignore
            # comments and inline Rust test modules before looking at sinks.
            text = re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', lambda m: '\n' * m[0].count('\n'), source)
            text = re.split(r'#\[cfg\(test\)\]', text)[0]
            pattern = r'(?:throw\s+(?:new\s+)?[\w:]+\s*\(|(?:bail|panic|ensure)!\s*\(|#\[error\s*\()\s*(?:\$|L|u8)?"((?:\\[\s\S]|[^"\\])*)"'
            for match in re.finditer(pattern, text):
                literal = re.sub(r'\\\r?\n\s*', '', match[1])
                literal = re.sub(r'\\([\\"nrt])', lambda m: {'n':'\n','r':'\r','t':'\t'}.get(m[1],m[1]), literal)
                # Pure formatting placeholders are upstream details rather than
                # a locally authored sentence (e.g. panic!("{error}")).
                parts = [] if not re.search('[A-Za-z]', re.sub(r'\{[^}]*\}', '', literal)) else [literal]
                check(path, text.count('\n', 0, match.start()) + 1, parts, 'Native direct failure literal')
    return dict(sorted(counts.items())), missing


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    counts, missing = audit()
    for kind, count in counts.items():
        print(f'{kind}: {count}')
    for row in missing[:50]:
        print('MISSING', *row)
    print(f'Unaccounted emission sites/fragments: {len(missing)}')
    raise SystemExit(bool(missing))
